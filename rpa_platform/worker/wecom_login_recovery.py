import os
import json
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol
from urllib import error, parse, request

from rpa_platform.domain.redaction import mask_identifier, redact_context
from rpa_platform.notifications.wecom_bot import build_image_payload, build_markdown_payload, build_text_payload

WECOM_BASE_URL = "https://open.work.weixin.qq.com"
WECOM_LOGIN_URL = "https://open.work.weixin.qq.com/wwopen/developers/tools"
DEFAULT_QR_SELECTOR = (
    "canvas, img[src*='qr'], img[src*='qrcode'], img[src*='login'], "
    "[class*='qr'] canvas, [class*='qr'] img, [class*='qrcode'] img, [class*='login'] img"
)


class LoginSessionStatus(str, Enum):
    EXPIRED = "expired"
    RESTORED = "restored"
    ERROR = "error"


@dataclass(frozen=True)
class LoginSessionCheckResult:
    status: LoginSessionStatus
    reason: str
    detail: str = ""


ReadonlyProbe = Callable[[], Any]


class LoginSessionHealthChecker:
    def __init__(self, readonly_probe: ReadonlyProbe):
        self.readonly_probe = readonly_probe

    def check(self) -> LoginSessionCheckResult:
        try:
            response = self.readonly_probe()
        except Exception as exc:
            return LoginSessionCheckResult(LoginSessionStatus.ERROR, "probe_error", str(exc))
        return classify_readonly_response(response)


def classify_readonly_response(response: Any) -> LoginSessionCheckResult:
    if isinstance(response, str):
        lowered = response.lower()
        if "outsession" in lowered or "<html" in lowered or "登录" in response:
            return LoginSessionCheckResult(LoginSessionStatus.EXPIRED, "login_required")
        return LoginSessionCheckResult(LoginSessionStatus.ERROR, "unexpected_text_response")

    if not isinstance(response, dict):
        return LoginSessionCheckResult(LoginSessionStatus.ERROR, "unexpected_response_type")

    status_code = response.get("status_code")
    if status_code in (401, 403):
        return LoginSessionCheckResult(LoginSessionStatus.EXPIRED, "http_forbidden")

    body = response.get("body")
    if isinstance(body, str):
        body_result = classify_readonly_response(body)
        if body_result.status == LoginSessionStatus.EXPIRED:
            return body_result

    result = response.get("result")
    if isinstance(result, dict):
        message = str(result.get("message", "")).lower()
        err_code = result.get("errCode")
        if err_code == -3 or message == "outsession" or "outsession" in message:
            return LoginSessionCheckResult(LoginSessionStatus.EXPIRED, "outsession", "outsession")
        if err_code not in (None, 0, "0"):
            return LoginSessionCheckResult(LoginSessionStatus.ERROR, "api_error", str(result))

    data = response.get("data")
    if isinstance(data, dict) and (
        "corpapp" in data
        or "corpapp_list" in data
        or "total" in data
        or "customized_app" in data
    ):
        return LoginSessionCheckResult(LoginSessionStatus.RESTORED, "readonly_api_ok")

    return LoginSessionCheckResult(LoginSessionStatus.ERROR, "unexpected_json_shape")


@dataclass(frozen=True)
class LoginRecoveryConfig:
    enabled: bool = False
    qr_notify_enabled: bool = False
    qr_notify_webhook_url: str = ""
    qr_notify_mode: str = "image"
    qr_notify_mention_mobiles: List[str] = field(default_factory=list)
    ttl_seconds: int = 120
    poll_interval_seconds: int = 5
    max_notify_times: int = 3
    artifact_dir: str = ".local/wecom-login-qr"
    cookie_file: str = ".local/wecom-admin.cookie"
    browser_profile_dir: str = ".local/wecom-bind-browser-profile"
    node_work_dir: str = ".local/playwright-wecom-login-recovery"
    login_url: str = WECOM_LOGIN_URL
    qr_selector: str = DEFAULT_QR_SELECTOR
    browser_channel: str = "chrome"

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "LoginRecoveryConfig":
        values = env or os.environ
        return cls(
            enabled=_parse_bool(values.get("WECOM_LOGIN_RECOVERY_ENABLED", "false")),
            qr_notify_enabled=_parse_bool(values.get("WECOM_QR_NOTIFY_ENABLED", "false")),
            qr_notify_webhook_url=values.get("WECOM_QR_NOTIFY_WEBHOOK_URL", "").strip(),
            qr_notify_mode=values.get("WECOM_QR_NOTIFY_MODE", "image").strip() or "image",
            qr_notify_mention_mobiles=_split_csv(values.get("WECOM_QR_NOTIFY_MENTION_MOBILES", "")),
            ttl_seconds=_parse_int(values.get("WECOM_QR_TTL_SECONDS"), 120),
            poll_interval_seconds=_parse_int(values.get("WECOM_QR_POLL_INTERVAL_SECONDS"), 5),
            max_notify_times=_parse_int(values.get("WECOM_QR_MAX_NOTIFY_TIMES"), 3),
            artifact_dir=values.get("WECOM_QR_ARTIFACT_DIR", ".local/wecom-login-qr"),
            cookie_file=values.get("WECOM_ADMIN_COOKIE_FILE", ".local/wecom-admin.cookie"),
            browser_profile_dir=values.get("WECOM_BROWSER_PROFILE_DIR", ".local/wecom-bind-browser-profile"),
            node_work_dir=values.get("WECOM_LOGIN_RECOVERY_NODE_WORK_DIR", ".local/playwright-wecom-login-recovery"),
            login_url=values.get("WECOM_LOGIN_URL", WECOM_LOGIN_URL),
            qr_selector=values.get("WECOM_QR_SELECTOR", DEFAULT_QR_SELECTOR),
            browser_channel=values.get("WECOM_BROWSER_CHANNEL", "chrome"),
        )


class QrProvider(Protocol):
    def capture(self) -> Path:
        raise NotImplementedError


class LocalQrArtifactProvider:
    def __init__(self, artifact_dir: str):
        self.artifact_dir = Path(artifact_dir)

    def capture(self) -> Path:
        candidates = [
            path
            for path in self.artifact_dir.glob("*")
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ]
        if not candidates:
            raise FileNotFoundError("No WeCom login QR artifact found in %s" % self.artifact_dir)
        return max(candidates, key=lambda path: path.stat().st_mtime_ns)


class PlaywrightQrArtifactProvider:
    def __init__(
        self,
        profile_dir: Path,
        artifact_dir: Path,
        node_work_dir: Path,
        login_url: str = WECOM_LOGIN_URL,
        qr_selector: str = DEFAULT_QR_SELECTOR,
        browser_channel: str = "chrome",
        ensure_package: Optional[Callable[[Path], None]] = None,
        run_command: Optional[Callable[[List[str], str], Any]] = None,
        start_process: Optional[Callable[[List[str], str], Any]] = None,
        keepalive_seconds: int = 120,
        wait_timeout_seconds: int = 30,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ):
        self.profile_dir = Path(profile_dir)
        self.artifact_dir = Path(artifact_dir)
        self.node_work_dir = Path(node_work_dir)
        self.login_url = login_url
        self.qr_selector = qr_selector
        self.browser_channel = browser_channel
        self.ensure_package = ensure_package or ensure_playwright_node_package
        self.run_command = run_command or _run_command
        self.start_process = start_process or _start_process
        self.keepalive_seconds = keepalive_seconds
        self.wait_timeout_seconds = wait_timeout_seconds
        self.sleep = sleep
        self.now = now
        self.process = None
        self.script_path: Optional[Path] = None

    def capture(self) -> Path:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.node_work_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_package(self.node_work_dir)
        output_path = self.artifact_dir / ("wecom-login-qr-%s.png" % int(self.now()))
        script_path = _write_temp_node_script(self.node_work_dir, _node_qr_capture_script())
        self.script_path = script_path
        try:
            command = [
                "node",
                str(script_path),
                "--profile-dir",
                str(self.profile_dir),
                "--login-url",
                self.login_url,
                "--qr-selector",
                self.qr_selector,
                "--output-path",
                str(output_path),
                "--browser-channel",
                self.browser_channel,
                "--keepalive-seconds",
                str(self.keepalive_seconds),
            ]
            if self.keepalive_seconds > 0:
                self.process = self.start_process(command, str(self.node_work_dir))
                self._wait_for_artifact(output_path)
                return output_path
            completed = self.run_command(command, str(self.node_work_dir))
        finally:
            if self.keepalive_seconds <= 0:
                try:
                    script_path.unlink()
                except OSError:
                    pass
                self.script_path = None
        if getattr(completed, "returncode", 1) != 0:
            raise RuntimeError("WeCom login QR capture failed with exit code %s" % getattr(completed, "returncode", "unknown"))
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise FileNotFoundError("WeCom login QR capture did not produce an image artifact")
        return output_path

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if getattr(process, "poll", lambda: None)() is None:
            terminate = getattr(process, "terminate", None)
            if terminate is not None:
                terminate()
        script_path = self.script_path
        self.script_path = None
        if script_path is not None:
            try:
                script_path.unlink()
            except OSError:
                pass

    def _wait_for_artifact(self, output_path: Path) -> None:
        deadline = time.time() + self.wait_timeout_seconds
        while time.time() < deadline:
            if output_path.exists() and output_path.stat().st_size > 0:
                return
            process = self.process
            if process is not None and getattr(process, "poll", lambda: None)() is not None:
                break
            self.sleep(0.25)
        raise FileNotFoundError("WeCom login QR capture did not produce an image artifact")


class WecomCookieSessionRefresher:
    def __init__(self, cookie_file: Path, export_cookie_header: Callable[[], str]):
        self.cookie_file = Path(cookie_file)
        self.export_cookie_header = export_cookie_header

    def refresh(self) -> bool:
        cookie_header = self.export_cookie_header().strip()
        if not cookie_header:
            return False
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self.cookie_file.write_text(cookie_header, encoding="utf-8")
        try:
            self.cookie_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except PermissionError:
            pass
        return True


class PlaywrightWecomCookieExporter:
    def __init__(
        self,
        profile_dir: Path,
        node_work_dir: Path,
        wecom_url: str = WECOM_LOGIN_URL,
        browser_channel: str = "chrome",
        ensure_package: Optional[Callable[[Path], None]] = None,
        run_command: Optional[Callable[[List[str], str], Any]] = None,
    ):
        self.profile_dir = Path(profile_dir)
        self.node_work_dir = Path(node_work_dir)
        self.wecom_url = wecom_url
        self.browser_channel = browser_channel
        self.ensure_package = ensure_package or ensure_playwright_node_package
        self.run_command = run_command or _run_command

    def __call__(self) -> str:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.node_work_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_package(self.node_work_dir)
        output_path = self.node_work_dir / "last-wecom-cookie-export.json"
        script_path = _write_temp_node_script(self.node_work_dir, _node_cookie_export_script())
        try:
            command = [
                "node",
                str(script_path),
                "--profile-dir",
                str(self.profile_dir),
                "--wecom-url",
                self.wecom_url,
                "--output-path",
                str(output_path),
                "--browser-channel",
                self.browser_channel,
            ]
            completed = self.run_command(command, str(self.node_work_dir))
        finally:
            try:
                script_path.unlink()
            except OSError:
                pass
        if getattr(completed, "returncode", 1) != 0:
            raise RuntimeError("WeCom cookie export failed with exit code %s" % getattr(completed, "returncode", "unknown"))
        if not output_path.exists():
            raise FileNotFoundError("WeCom cookie export did not produce a result file")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("WeCom cookie export result is not valid JSON") from exc
        cookie_header = str(payload.get("wecom_cookie") or "").strip()
        if not cookie_header:
            raise RuntimeError("WeCom cookie export result is missing cookie header")
        return cookie_header


class WecomCookieFileReadonlyProbe:
    def __init__(
        self,
        cookie_file: Path,
        suiteid: int,
        enterprise_name: str,
        base_url: str = WECOM_BASE_URL,
        timeout: int = 20,
        request_json: Optional[Callable[[str, Dict[str, Any], Dict[str, str]], Dict[str, Any]]] = None,
    ):
        self.cookie_file = Path(cookie_file)
        self.suiteid = suiteid
        self.enterprise_name = enterprise_name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.request_json = request_json or self._request_json

    def __call__(self) -> Dict[str, Any]:
        cookie = self._read_cookie()
        if not cookie:
            return {"status_code": 401, "body": "missing wecom cookie source"}
        return self.request_json(
            "/wwopen/developer/customApp/tpl/app/list",
            {
                "lang": "zh_CN",
                "ajax": 1,
                "f": "json",
                "suiteid": str(self.suiteid),
                "scene": 1,
                "corp_name_keyword": self.enterprise_name,
                "offset": 0,
                "limit": 10,
                "random": 0,
            },
            {
                "content-type": "application/json",
                "cookie": cookie,
                "origin": self.base_url,
                "referer": self.base_url + "/wwopen/developers/tools",
                "x-wecom-developer-page": "/sass/customApp/tpl/info",
                "x-wecom-developer-perm": "50",
            },
        )

    def _read_cookie(self) -> str:
        if not self.cookie_file.exists():
            return ""
        return self.cookie_file.read_text(encoding="utf-8").strip()

    def _request_json(self, path: str, params: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        query = parse.urlencode(params)
        url = self.base_url + path + ("?" + query if query else "")
        req = request.Request(url=url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            return {"status_code": exc.code, "body": "wecom readonly probe HTTP error"}
        except Exception as exc:
            return {"status_code": 0, "body": "wecom readonly probe failed: %s" % exc.__class__.__name__}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"status_code": 0, "body": raw[:200]}
        if not isinstance(data, dict):
            return {"status_code": 0, "body": "wecom readonly probe returned non-object JSON"}
        return data


class LoginRecoveryNotifier(Protocol):
    def notify_qr(self, *, task_id: str, qr_path: Path, expires_at: float, context: Dict[str, Any]) -> None:
        raise NotImplementedError


class SessionRefresher(Protocol):
    def refresh(self) -> bool:
        raise NotImplementedError


class WecomLoginRecoveryOrchestrator:
    def __init__(
        self,
        config: LoginRecoveryConfig,
        preflight: Callable[[], Dict[str, Any]],
        health_checker: LoginSessionHealthChecker,
        qr_provider: QrProvider,
        notifier: LoginRecoveryNotifier,
        session_refresher: Optional[SessionRefresher] = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ):
        self.config = config
        self.preflight = preflight
        self.health_checker = health_checker
        self.qr_provider = qr_provider
        self.notifier = notifier
        self.session_refresher = session_refresher
        self.sleep = sleep
        self.now = now

    def run(self, task_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        first = self.preflight()
        if first.get("reason") != "wecom_session_expired":
            return _map_preflight_result(first)
        if not self.config.enabled:
            return first

        qr_path = self.qr_provider.capture()
        try:
            expires_at = self.now() + self.config.ttl_seconds
            if self.config.qr_notify_enabled and self.config.max_notify_times > 0:
                self.notifier.notify_qr(
                    task_id=task_id,
                    qr_path=qr_path,
                    expires_at=expires_at,
                    context=dict(context),
                )

            attempts = max(1, int(self.config.ttl_seconds / max(1, self.config.poll_interval_seconds)))
            last_check = LoginSessionCheckResult(LoginSessionStatus.EXPIRED, "not_checked")
            for attempt in range(attempts):
                if self.session_refresher is not None:
                    try:
                        self.session_refresher.refresh()
                    except Exception as exc:
                        last_check = LoginSessionCheckResult(
                            LoginSessionStatus.ERROR,
                            "session_refresh_failed",
                            exc.__class__.__name__,
                        )
                        if attempt < attempts - 1:
                            self.sleep(self.config.poll_interval_seconds)
                        continue
                last_check = self.health_checker.check()
                if last_check.status == LoginSessionStatus.RESTORED:
                    return _map_preflight_result(self.preflight())
                if attempt < attempts - 1:
                    self.sleep(self.config.poll_interval_seconds)

            return {
                "status": "waiting_login",
                "reason": "wecom_login_not_restored",
                "detail": last_check.detail or last_check.reason,
                "expires_at": expires_at,
            }
        finally:
            close = getattr(self.qr_provider, "close", None)
            if close is not None:
                close()


class WecomQrLoginNotifier:
    def __init__(
        self,
        bot_client: Any,
        mentioned_mobile_list: Optional[List[str]] = None,
        notify_mode: str = "image",
    ):
        self.bot_client = bot_client
        self.mentioned_mobile_list = list(mentioned_mobile_list or [])
        self.notify_mode = notify_mode

    def notify_qr(self, *, task_id: str, qr_path: Path, expires_at: float, context: Dict[str, Any]) -> None:
        safe_context = _redact_notification_context(context)
        enterprise_name = str(safe_context.get("enterprise_name") or safe_context.get("企业客户名称") or "")
        lines = [
            "任务：%s" % task_id,
            "客户：%s" % enterprise_name,
            "状态：企微后台登录态失效，等待管理员扫码恢复",
            "过期时间戳：%s" % int(expires_at),
        ]
        self.bot_client.send(build_markdown_payload("企微后台登录态恢复", lines))
        if self.mentioned_mobile_list:
            self.bot_client.send(
                build_text_payload(
                    "请扫码恢复企微开发者后台登录态，任务 %s。" % task_id,
                    mentioned_mobile_list=self.mentioned_mobile_list,
                )
            )
        if self.notify_mode == "image":
            self.bot_client.send(build_image_payload(qr_path))


def _map_preflight_result(preflight: Dict[str, Any]) -> Dict[str, Any]:
    status = preflight.get("status")
    if status == "ok":
        mapped = dict(preflight)
        mapped["status"] = "ready_for_real_bind"
        mapped["preflight"] = dict(preflight)
        return mapped
    if status == "review":
        mapped = dict(preflight)
        mapped["status"] = "manual_confirm_required"
        mapped["preflight"] = dict(preflight)
        return mapped
    return preflight


def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _parse_int(raw: Optional[str], default: int) -> int:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _split_csv(raw: str) -> List[str]:
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _redact_notification_context(context: Dict[str, Any]) -> Dict[str, Any]:
    redacted = redact_context(context)
    _mask_key(redacted, "plain_corp_id")
    _mask_key(redacted, "requested_user_id")
    return redacted


def _mask_key(value: Any, key_name: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == key_name and isinstance(child, str):
                value[key] = mask_identifier(child)
            else:
                _mask_key(child, key_name)
    elif isinstance(value, list):
        for item in value:
            _mask_key(item, key_name)


def ensure_playwright_node_package(node_work_dir: Path) -> None:
    package_file = node_work_dir / "node_modules" / "playwright" / "package.json"
    if package_file.exists():
        return
    node_work_dir.mkdir(parents=True, exist_ok=True)
    package_json = node_work_dir / "package.json"
    if not package_json.exists():
        package_json.write_text(
            json.dumps({"private": True, "type": "module"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    completed = subprocess.run(
        _npm_install_command(),
        cwd=str(node_work_dir),
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("npm install playwright failed with exit code %s" % completed.returncode)


def _npm_install_command() -> List[str]:
    executable = "npm.cmd" if os.name == "nt" else "npm"
    return [executable, "install", "--no-audit", "--no-fund", "playwright@1.61.0"]


def _run_command(command: List[str], cwd: str) -> Any:
    return subprocess.run(command, cwd=cwd, check=False, text=True)


def _start_process(command: List[str], cwd: str) -> Any:
    return subprocess.Popen(command, cwd=cwd)


def _write_temp_node_script(node_work_dir: Path, script: str) -> Path:
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".mjs",
        encoding="utf-8",
        delete=False,
        dir=str(node_work_dir),
    ) as temp:
        temp.write(script)
        return Path(temp.name)


def _node_qr_capture_script() -> str:
    return r"""
import { chromium } from 'playwright';

function argValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) {
    throw new Error(`Missing ${name}`);
  }
  return process.argv[index + 1];
}

const profileDir = argValue('--profile-dir');
const loginUrl = argValue('--login-url');
const qrSelector = argValue('--qr-selector');
const outputPath = argValue('--output-path');
const browserChannel = argValue('--browser-channel');
const keepaliveSeconds = Number(argValue('--keepalive-seconds') || '0');

const launchOptions = {
  headless: false,
  viewport: { width: 1440, height: 960 },
};
if (browserChannel && browserChannel !== 'bundled') {
  launchOptions.channel = browserChannel;
}

async function findQrLocator(page, selector) {
  const pageLocator = page.locator(selector).first();
  try {
    await pageLocator.waitFor({ state: 'visible', timeout: 5000 });
    return pageLocator;
  } catch (_error) {
    // Continue into child frames. WeCom renders the login QR inside a visible iframe.
  }

  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    for (const frame of page.frames()) {
      if (frame === page.mainFrame()) {
        continue;
      }
      const frameLocator = frame.locator(selector).first();
      try {
        await frameLocator.waitFor({ state: 'visible', timeout: 1000 });
        return frameLocator;
      } catch (_error) {
        // Try the next frame until the global deadline expires.
      }
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`No visible WeCom login QR matched selector: ${selector}`);
}

const context = await chromium.launchPersistentContext(profileDir, launchOptions);
try {
  const page = await context.newPage();
  await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
  const locator = await findQrLocator(page, qrSelector);
  await locator.screenshot({ path: outputPath });
  if (keepaliveSeconds > 0) {
    await new Promise((resolve) => setTimeout(resolve, keepaliveSeconds * 1000));
  }
} finally {
  await context.close();
}
"""


def _node_cookie_export_script() -> str:
    return r"""
import fs from 'node:fs';
import { chromium } from 'playwright';

function argValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) {
    throw new Error(`Missing ${name}`);
  }
  return process.argv[index + 1];
}

function cookieHeader(cookies) {
  return cookies
    .filter((cookie) => cookie.name && cookie.value)
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join('; ');
}

const profileDir = argValue('--profile-dir');
const wecomUrl = argValue('--wecom-url');
const outputPath = argValue('--output-path');
const browserChannel = argValue('--browser-channel');

const launchOptions = {
  headless: false,
  viewport: { width: 1440, height: 960 },
};
if (browserChannel && browserChannel !== 'bundled') {
  launchOptions.channel = browserChannel;
}

const context = await chromium.launchPersistentContext(profileDir, launchOptions);
try {
  const cookies = await context.cookies([wecomUrl]);
  const payload = {
    wecom_cookie: cookieHeader(cookies),
    wecom_cookie_count: cookies.length,
  };
  fs.writeFileSync(outputPath, JSON.stringify(payload), { encoding: 'utf8', mode: 0o600 });
} finally {
  await context.close();
}
"""
