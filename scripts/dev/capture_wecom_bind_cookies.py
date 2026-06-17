import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.dev.check_wecom_bind_real_readonly import main as preflight_main


JDY_URL = "https://dc.jdydevelop.com/fx_sa/wework_bind"
WECOM_URL = "https://open.work.weixin.qq.com/wwopen/developers/tools"


class CookieCaptureError(RuntimeError):
    """Raised when browser cookie capture fails."""


def default_capture_paths(repo_root: Path = REPO_ROOT) -> Dict[str, Path]:
    local_dir = repo_root / ".local"
    return {
        "profile_dir": local_dir / "wecom-bind-browser-profile",
        "node_work_dir": local_dir / "playwright-cookie-capture",
        "jdy_cookie_file": local_dir / "jdy-admin.cookie",
        "wecom_cookie_file": local_dir / "wecom-admin.cookie",
    }


def write_cookie_file(path: Path, cookie_header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cookie_header.strip(), encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except PermissionError:
        pass


def capture_cookies_with_playwright(
    profile_dir: Path,
    node_work_dir: Path,
    jdy_url: str = JDY_URL,
    wecom_url: str = WECOM_URL,
    browser_channel: str = "chrome",
    assume_logged_in: bool = False,
    auto_wait_seconds: int = 0,
) -> Dict[str, Any]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    ensure_playwright_node_package(node_work_dir)
    script = _node_capture_script()
    node_work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".mjs",
        encoding="utf-8",
        delete=False,
        dir=str(node_work_dir),
    ) as temp:
        temp.write(script)
        script_path = Path(temp.name)
    try:
        command = [
            "node",
            str(script_path),
            "--profile-dir",
            str(profile_dir),
            "--jdy-url",
            jdy_url,
            "--wecom-url",
            wecom_url,
            "--browser-channel",
            browser_channel,
            "--assume-logged-in",
            "1" if assume_logged_in else "0",
            "--auto-wait-seconds",
            str(auto_wait_seconds),
        ]
        completed = subprocess.run(command, check=False, text=True, cwd=str(node_work_dir))
    finally:
        try:
            script_path.unlink()
        except OSError:
            pass

    if completed.returncode != 0:
        raise CookieCaptureError("Playwright cookie capture failed with exit code %s" % completed.returncode)

    payload_path = profile_dir / "last-cookie-capture.json"
    if not payload_path.exists():
        raise CookieCaptureError("Playwright cookie capture did not produce a result file")
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CookieCaptureError("Playwright cookie capture result is not valid JSON") from exc
    if not payload.get("jdy_cookie") or not payload.get("wecom_cookie"):
        raise CookieCaptureError("missing required Jiandaoyun or WeCom cookies after manual login")
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Capture Jiandaoyun and WeCom admin cookies into .local files.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--profile-dir", default=None)
    parser.add_argument("--node-work-dir", default=None)
    parser.add_argument("--jdy-cookie-file", default=None)
    parser.add_argument("--wecom-cookie-file", default=None)
    parser.add_argument("--jdy-url", default=JDY_URL)
    parser.add_argument("--wecom-url", default=WECOM_URL)
    parser.add_argument(
        "--browser-channel",
        default="chrome",
        help="Playwright browser channel. Use 'bundled' to require Playwright-managed Chromium.",
    )
    parser.add_argument(
        "--assume-logged-in",
        action="store_true",
        help="Export cookies from the dedicated profile immediately without waiting for manual login.",
    )
    parser.add_argument(
        "--auto-wait-seconds",
        type=int,
        default=0,
        help="Poll cookies until both admin sessions are present, then save automatically.",
    )
    parser.add_argument("--run-preflight", action="store_true")
    parser.add_argument("--enterprise-name", default=None)
    parser.add_argument("--enterprise-short-name", default="")
    parser.add_argument("--plain-corp-id", default=None)
    parser.add_argument("--requested-user-id", default=None)
    parser.add_argument("--suite-id", type=int, default=1)
    parser.add_argument("--suite-scenario", default="main")
    parser.add_argument("--wecom-suiteid", type=int, default=1009479)
    parser.add_argument("--suite-name", default="简道云")
    parser.add_argument("--use-fake-capture-for-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--use-fake-preflight-for-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    defaults = default_capture_paths(repo_root)
    profile_dir = Path(args.profile_dir).resolve() if args.profile_dir else defaults["profile_dir"]
    node_work_dir = Path(args.node_work_dir).resolve() if args.node_work_dir else defaults["node_work_dir"]
    jdy_cookie_file = Path(args.jdy_cookie_file).resolve() if args.jdy_cookie_file else defaults["jdy_cookie_file"]
    wecom_cookie_file = (
        Path(args.wecom_cookie_file).resolve() if args.wecom_cookie_file else defaults["wecom_cookie_file"]
    )

    if args.use_fake_capture_for_test:
        capture = {
            "jdy_cookie": "sid=jdy_sid_secret",
            "wecom_cookie": "wwrtx.sid=fake_sid",
            "jdy_cookie_count": 1,
            "wecom_cookie_count": 1,
        }
    else:
        capture = capture_cookies_with_playwright(
            profile_dir=profile_dir,
            node_work_dir=node_work_dir,
            jdy_url=args.jdy_url,
            wecom_url=args.wecom_url,
            browser_channel=args.browser_channel,
            assume_logged_in=args.assume_logged_in,
            auto_wait_seconds=args.auto_wait_seconds,
        )

    write_cookie_file(jdy_cookie_file, str(capture["jdy_cookie"]))
    write_cookie_file(wecom_cookie_file, str(capture["wecom_cookie"]))

    result: Dict[str, Any] = {
        "status": "cookies_saved",
        "profile_dir": str(profile_dir),
        "node_work_dir": str(node_work_dir),
        "jdy_cookie_file": str(jdy_cookie_file),
        "wecom_cookie_file": str(wecom_cookie_file),
        "jdy_cookie_count": int(capture.get("jdy_cookie_count") or 0),
        "wecom_cookie_count": int(capture.get("wecom_cookie_count") or 0),
    }

    if args.run_preflight:
        preflight_args = _preflight_args(args, jdy_cookie_file, wecom_cookie_file)
        preflight_output = _capture_preflight_stdout(preflight_args)
        result["preflight"] = json.loads(preflight_output)

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("preflight", {"status": "ok"})["status"] in {"ok", "review"} else 2


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
        raise CookieCaptureError("npm install playwright failed with exit code %s" % completed.returncode)


def _npm_install_command() -> List[str]:
    executable = "npm.cmd" if os.name == "nt" else "npm"
    return [executable, "install", "--no-audit", "--no-fund", "playwright@1.61.0"]


def _preflight_args(args: argparse.Namespace, jdy_cookie_file: Path, wecom_cookie_file: Path) -> List[str]:
    required = {
        "--enterprise-name": args.enterprise_name,
        "--plain-corp-id": args.plain_corp_id,
        "--requested-user-id": args.requested_user_id,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise CookieCaptureError("--run-preflight requires %s" % ", ".join(missing))
    preflight_args = [
        "--enterprise-name",
        args.enterprise_name,
        "--enterprise-short-name",
        args.enterprise_short_name,
        "--plain-corp-id",
        args.plain_corp_id,
        "--requested-user-id",
        args.requested_user_id,
        "--suite-id",
        str(args.suite_id),
        "--suite-scenario",
        args.suite_scenario,
        "--wecom-suiteid",
        str(args.wecom_suiteid),
        "--suite-name",
        args.suite_name,
        "--jdy-cookie-file",
        str(jdy_cookie_file),
        "--wecom-cookie-file",
        str(wecom_cookie_file),
    ]
    if args.use_fake_preflight_for_test:
        preflight_args.append("--use-fake-transport-for-test")
    return preflight_args


def _capture_preflight_stdout(argv: List[str]) -> str:
    from contextlib import redirect_stdout
    from io import StringIO

    output = StringIO()
    with redirect_stdout(output):
        exit_code = preflight_main(argv)
    if exit_code not in {0, 2}:
        raise CookieCaptureError("readonly preflight returned unexpected exit code %s" % exit_code)
    return output.getvalue()


def _node_capture_script() -> str:
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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function waitForEnter() {
  return new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once('data', () => resolve());
  });
}

async function readPayload(context, jdyUrl, wecomUrl) {
  const jdyCookies = await context.cookies([jdyUrl]);
  const wecomCookies = await context.cookies([wecomUrl]);
  const allCookies = await context.cookies();
  const cookieDomainCounts = {};
  for (const cookie of allCookies) {
    cookieDomainCounts[cookie.domain] = (cookieDomainCounts[cookie.domain] || 0) + 1;
  }
  return {
    jdy_cookie: cookieHeader(jdyCookies),
    wecom_cookie: cookieHeader(wecomCookies),
    jdy_cookie_count: jdyCookies.length,
    wecom_cookie_count: wecomCookies.length,
    cookie_domain_counts: cookieDomainCounts,
  };
}

const profileDir = argValue('--profile-dir');
const jdyUrl = argValue('--jdy-url');
const wecomUrl = argValue('--wecom-url');
const browserChannel = argValue('--browser-channel');
const assumeLoggedIn = argValue('--assume-logged-in') === '1';
const autoWaitSeconds = Number(argValue('--auto-wait-seconds') || '0');
const resultPath = `${profileDir}/last-cookie-capture.json`;

const launchOptions = {
  headless: false,
  viewport: { width: 1440, height: 960 },
};
if (browserChannel && browserChannel !== 'bundled') {
  launchOptions.channel = browserChannel;
}

const context = await chromium.launchPersistentContext(profileDir, launchOptions);

try {
  const jdyPage = await context.newPage();
  await jdyPage.goto(jdyUrl, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch((error) => {
    console.log(`简道云页面打开未完成，继续等待人工处理：${error.message}`);
  });
  const wecomPage = await context.newPage();
  await wecomPage.goto(wecomUrl, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch((error) => {
    console.log(`企微页面打开未完成，继续等待人工处理：${error.message}`);
  });

  if (autoWaitSeconds > 0) {
    console.log('');
    console.log(`正在等待登录态，最多 ${autoWaitSeconds} 秒；检测到两边 Cookie 后会自动保存。`);
    const deadline = Date.now() + autoWaitSeconds * 1000;
    while (Date.now() < deadline) {
      const payload = await readPayload(context, jdyUrl, wecomUrl);
      console.log(`当前 Cookie 数：简道云=${payload.jdy_cookie_count}，企微=${payload.wecom_cookie_count}`);
      if (payload.jdy_cookie && payload.wecom_cookie) {
        fs.writeFileSync(resultPath, JSON.stringify(payload), { encoding: 'utf8', mode: 0o600 });
        process.exit(0);
      }
      await sleep(3000);
    }
  } else if (!assumeLoggedIn) {
    console.log('');
    console.log('请在打开的浏览器中完成简道云后台和企微开发者后台登录。');
    console.log('两个页面都确认已登录后，回到这个终端按 Enter 保存 Cookie。');
    await waitForEnter();
  }

  const payload = await readPayload(context, jdyUrl, wecomUrl);
  fs.writeFileSync(resultPath, JSON.stringify(payload), { encoding: 'utf8', mode: 0o600 });
} finally {
  await context.close();
}
"""


if __name__ == "__main__":
    raise SystemExit(main())
