import json
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from rpa_platform.notifications.wecom_bot import WecomBotClient
from rpa_platform.services.wecom_bind_service import JdyWecomBindInput, RandomWecomSecretGenerator
from rpa_platform.worker.wecom_bind_recovery_handler import WecomBindRecoveryTaskHandler
from rpa_platform.worker.wecom_login_recovery import (
    GenericQrLoginNotifier,
    JdyCookieFileReadonlyProbe,
    LoginRecoveryConfig,
    LoginSessionHealthChecker,
    PlaywrightQrArtifactProvider,
    PlaywrightWecomCookieExporter,
    WecomCookieFileReadonlyProbe,
    WecomCookieSessionRefresher,
    WecomLoginRecoveryOrchestrator,
    WecomQrLoginNotifier,
    DEFAULT_QR_SELECTOR,
)
from scripts.dev.check_wecom_bind_real_readonly import CookieSourceError, build_real_clients, run_readonly_preflight


BUSINESS_UNEXECUTABLE_REASONS = {
    "missing_enterprise_name",
    "missing_corp_id",
    "missing_userid",
    "missing_required_bind_context",
    "jdy_corp_not_unique_or_missing",
    "owner_cannot_bind_or_update_corp_secret",
    "wecom_app_not_unique_or_missing",
    "wecom_app_not_found",
    "wecom_app_ambiguous",
    "wecom_app_lookup_conflict",
    "wecom_app_id_missing",
    "wecom_aes_app_id_missing",
}


class RealWecomBindRecovery:
    def __init__(self, orchestrator_factory: Callable[[Dict[str, Any]], Any]):
        self.orchestrator_factory = orchestrator_factory

    def run(self, task_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        missing = _missing_required_fields(context)
        if missing:
            return _missing_required_business_result(missing)
        build_bind_input_from_context(context)
        orchestrator = self.orchestrator_factory(context)
        return _coerce_business_unexecutable_result(dict(orchestrator.run(task_id=task_id, context=context)))


class RealWecomBindUnattendedWriteRecovery:
    def __init__(
        self,
        env: Optional[Mapping[str, str]] = None,
        wait_seconds: int = 300,
        login_recovery_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
        clients_builder: Callable[..., Dict[str, Any]] = build_real_clients,
        write_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    ):
        self.env = dict(env or {})
        self.wait_seconds = wait_seconds
        self.login_recovery_factory = login_recovery_factory
        self.clients_builder = clients_builder
        self.write_runner = write_runner

    def run(self, task_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        missing = _missing_required_fields(context)
        if missing:
            return _missing_required_business_result(missing, mode="unattended_write")

        from rpa_platform.worker.wecom_bind_unattended_write import (
            default_context_file,
            default_lock_file,
            run_unattended_wecom_bind_write,
        )

        context_file = default_context_file(task_id)
        has_pending_auditorder = _has_pending_auditorder_context_file(context_file)
        login_recovery = self._build_login_recovery(context)
        recoverable_preflight = dict(login_recovery.run(task_id=task_id, context=context))
        if (
            recoverable_preflight.get("status") not in {"ready_for_real_bind", "manual_confirm_required"}
            and not has_pending_auditorder
        ):
            result = _coerce_business_unexecutable_result(dict(recoverable_preflight))
            result["mode"] = "unattended_write"
            return result

        try:
            clients = self.clients_builder(
                jdy_cookie_file=str(context.get("jdy_cookie_file") or self.env.get("JDY_ADMIN_COOKIE_FILE") or ""),
                wecom_cookie_file=str(
                    context.get("wecom_cookie_file")
                    or self.env.get("WECOM_ADMIN_COOKIE_FILE")
                    or ""
                ),
            )
        except Exception as exc:
            return {
                "mode": "unattended_write",
                "status": "blocked",
                "reason": "missing_cookie_source",
                "detail": str(exc),
            }
        runner = self.write_runner or run_unattended_wecom_bind_write
        return runner(
            task_id=task_id,
            context=context,
            jdy_client=clients["jdy_client"],
            wecom_client=clients["wecom_client"],
            secret_generator=RandomWecomSecretGenerator(),
            preflight_runner=lambda *_args, **_kwargs: recoverable_preflight,
            login_recovery=recoverable_preflight.get("login_recovery", {}),
            context_file=context_file,
            lock_file=default_lock_file(),
            wait_seconds=self.wait_seconds,
        )

    def _build_login_recovery(self, context: Dict[str, Any]) -> Any:
        if self.login_recovery_factory is not None:
            return self.login_recovery_factory(context)
        return _build_chained_login_recovery(self.env, context)


class ChainedLoginRecoveryOrchestrator:
    def __init__(self, jdy_recovery: Any, wecom_recovery: Any):
        self.jdy_recovery = jdy_recovery
        self.wecom_recovery = wecom_recovery

    def run(self, task_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        jdy_result = dict(self.jdy_recovery.run(task_id=task_id, context=context))
        if jdy_result.get("reason") == "wecom_session_expired":
            return dict(self.wecom_recovery.run(task_id=task_id, context=context))
        return jdy_result


def build_bind_input_from_context(context: Dict[str, Any]) -> JdyWecomBindInput:
    return JdyWecomBindInput(
        enterprise_name=_first_text(context, "enterprise_name", "企业客户名称"),
        enterprise_short_name=_first_text(context, "enterprise_short_name", "企业简称"),
        plain_corp_id=_first_text(context, "plain_corp_id", "corp_id", "企业微信明文 CorpID"),
        requested_user_id=_first_text(context, "requested_user_id", "userid", "user_id", "User_ID"),
        suite_id=_parse_int(context.get("suite_id"), 1),
        suite_scenario=str(context.get("suite_scenario") or "main").strip(),
        wecom_suiteid=_parse_int(context.get("wecom_suiteid"), 1009479),
        suite_name=str(context.get("suite_name") or "简道云").strip(),
    )


def _has_pending_auditorder_context_file(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    wecom = data.get("wecom") if isinstance(data.get("wecom"), dict) else {}
    auditorderid = str(wecom.get("auditorderid") or "").strip()
    if not auditorderid:
        return False
    try:
        auditorder_status = int(wecom.get("auditorder_status"))
    except (TypeError, ValueError):
        auditorder_status = None
    return auditorder_status != 5


def build_wecom_bind_recovery_handler_from_env(
    env: Optional[Mapping[str, str]] = None,
) -> WecomBindRecoveryTaskHandler:
    config = LoginRecoveryConfig.from_env(dict(env) if env is not None else None)
    recovery = RealWecomBindRecovery(orchestrator_factory=lambda context: _build_orchestrator(config, context))
    return WecomBindRecoveryTaskHandler(recovery)


def build_wecom_bind_unattended_write_handler_from_env(
    env: Optional[Mapping[str, str]] = None,
) -> WecomBindRecoveryTaskHandler:
    wait_seconds = _parse_int((env or {}).get("RPA_WORKER_UNATTENDED_WRITE_WAIT_SECONDS"), 300)
    return WecomBindRecoveryTaskHandler(RealWecomBindUnattendedWriteRecovery(env=env, wait_seconds=wait_seconds))


def _build_orchestrator(config: LoginRecoveryConfig, context: Dict[str, Any]) -> WecomLoginRecoveryOrchestrator:
    bind_input = build_bind_input_from_context(context)

    def preflight() -> Dict[str, Any]:
        try:
            clients = build_real_clients(
                jdy_cookie_file=str(context.get("jdy_cookie_file") or ""),
                wecom_cookie_file=config.cookie_file,
            )
        except CookieSourceError as exc:
            return {"status": "blocked", "reason": "wecom_session_expired", "detail": str(exc)}
        return run_readonly_preflight(bind_input, **clients)

    health_checker = LoginSessionHealthChecker(
        WecomCookieFileReadonlyProbe(
            cookie_file=Path(config.cookie_file),
            suiteid=bind_input.wecom_suiteid,
            enterprise_name=bind_input.enterprise_short_name or bind_input.enterprise_name,
        )
    )
    qr_provider = PlaywrightQrArtifactProvider(
        profile_dir=Path(config.browser_profile_dir),
        artifact_dir=Path(config.artifact_dir),
        node_work_dir=Path(config.node_work_dir),
        login_url=config.login_url,
        qr_selector=config.qr_selector,
        browser_channel=config.browser_channel,
        keepalive_seconds=config.ttl_seconds,
    )
    notifier = WecomQrLoginNotifier(
        WecomBotClient(config.qr_notify_webhook_url),
        mentioned_mobile_list=config.qr_notify_mention_mobiles,
        notify_mode=config.qr_notify_mode,
    )
    session_refresher = WecomCookieSessionRefresher(
        Path(config.cookie_file),
        PlaywrightWecomCookieExporter(
            profile_dir=Path(config.browser_profile_dir),
            node_work_dir=Path(config.node_work_dir),
            wecom_url=config.login_url,
            browser_channel=config.browser_channel,
        ),
    )
    return WecomLoginRecoveryOrchestrator(
        config=config,
        preflight=preflight,
        health_checker=health_checker,
        qr_provider=qr_provider,
        notifier=notifier,
        session_refresher=session_refresher,
    )


def _build_chained_login_recovery(env: Mapping[str, str], context: Dict[str, Any]) -> ChainedLoginRecoveryOrchestrator:
    return ChainedLoginRecoveryOrchestrator(
        jdy_recovery=_build_jdy_orchestrator(_jdy_login_recovery_config_from_env(env), env, context),
        wecom_recovery=_build_orchestrator(LoginRecoveryConfig.from_env(dict(env)), context),
    )


def _build_jdy_orchestrator(
    config: LoginRecoveryConfig,
    env: Mapping[str, str],
    context: Dict[str, Any],
) -> WecomLoginRecoveryOrchestrator:
    bind_input = build_bind_input_from_context(context)

    def preflight() -> Dict[str, Any]:
        try:
            clients = build_real_clients(
                jdy_cookie_file=config.cookie_file,
                wecom_cookie_file=str(context.get("wecom_cookie_file") or env.get("WECOM_ADMIN_COOKIE_FILE") or ""),
            )
        except CookieSourceError as exc:
            detail = str(exc)
            reason = "wecom_session_expired" if "WECOM_ADMIN_COOKIE" in detail or "wecom" in detail.lower() else "jdy_session_expired"
            return {"status": "blocked", "reason": reason, "detail": detail}
        return run_readonly_preflight(bind_input, **clients)

    health_checker = LoginSessionHealthChecker(
        JdyCookieFileReadonlyProbe(
            cookie_file=Path(config.cookie_file),
            filter_text=bind_input.plain_corp_id or bind_input.enterprise_short_name or bind_input.enterprise_name,
        )
    )
    qr_provider = PlaywrightQrArtifactProvider(
        profile_dir=Path(config.browser_profile_dir),
        artifact_dir=Path(config.artifact_dir),
        node_work_dir=Path(config.node_work_dir),
        login_url=config.login_url,
        qr_selector=config.qr_selector,
        browser_channel=config.browser_channel,
        keepalive_seconds=config.ttl_seconds,
    )
    notifier = GenericQrLoginNotifier(
        WecomBotClient(config.qr_notify_webhook_url),
        title="简道眼登录",
        status_text="简道眼登录态失效，等待管理员扫码恢复",
        mentioned_mobile_list=config.qr_notify_mention_mobiles,
        notify_mode=config.qr_notify_mode,
    )
    session_refresher = WecomCookieSessionRefresher(
        Path(config.cookie_file),
        PlaywrightWecomCookieExporter(
            profile_dir=Path(config.browser_profile_dir),
            node_work_dir=Path(config.node_work_dir),
            wecom_url=config.login_url,
            browser_channel=config.browser_channel,
        ),
    )
    return WecomLoginRecoveryOrchestrator(
        config=config,
        preflight=preflight,
        health_checker=health_checker,
        qr_provider=qr_provider,
        notifier=notifier,
        session_refresher=session_refresher,
    )


def _jdy_login_recovery_config_from_env(env: Mapping[str, str]) -> LoginRecoveryConfig:
    return LoginRecoveryConfig(
        enabled=_truthy_env(env, "JDY_LOGIN_RECOVERY_ENABLED", env.get("WECOM_LOGIN_RECOVERY_ENABLED", "false")),
        qr_notify_enabled=_truthy_env(env, "JDY_QR_NOTIFY_ENABLED", env.get("WECOM_QR_NOTIFY_ENABLED", "false")),
        qr_notify_webhook_url=str(env.get("JDY_QR_NOTIFY_WEBHOOK_URL") or env.get("WECOM_QR_NOTIFY_WEBHOOK_URL") or "").strip(),
        qr_notify_mode=str(env.get("JDY_QR_NOTIFY_MODE") or env.get("WECOM_QR_NOTIFY_MODE") or "image").strip() or "image",
        qr_notify_mention_mobiles=_split_csv(str(env.get("JDY_QR_NOTIFY_MENTION_MOBILES") or env.get("WECOM_QR_NOTIFY_MENTION_MOBILES") or "")),
        ttl_seconds=_parse_int(env.get("JDY_QR_TTL_SECONDS") or env.get("WECOM_QR_TTL_SECONDS"), 120),
        poll_interval_seconds=_parse_int(env.get("JDY_QR_POLL_INTERVAL_SECONDS") or env.get("WECOM_QR_POLL_INTERVAL_SECONDS"), 5),
        max_notify_times=_parse_int(env.get("JDY_QR_MAX_NOTIFY_TIMES") or env.get("WECOM_QR_MAX_NOTIFY_TIMES"), 3),
        artifact_dir=str(env.get("JDY_QR_ARTIFACT_DIR") or ".local/jdy-login-qr"),
        cookie_file=str(env.get("JDY_ADMIN_COOKIE_FILE") or ".local/jdy-admin.cookie"),
        browser_profile_dir=str(env.get("JDY_BROWSER_PROFILE_DIR") or ".local/jdy-admin-browser-profile"),
        node_work_dir=str(env.get("JDY_LOGIN_RECOVERY_NODE_WORK_DIR") or ".local/playwright-jdy-login-recovery"),
        login_url=str(env.get("JDY_LOGIN_URL") or "https://dc.jdydevelop.com"),
        qr_selector=_jdy_qr_selector_from_env(env),
        browser_channel=str(env.get("JDY_BROWSER_CHANNEL") or env.get("WECOM_BROWSER_CHANNEL") or "chrome"),
        trigger_reason="jdy_session_expired",
        login_not_restored_reason="jdy_login_not_restored",
        retry_action="retry_jdy_login_qr",
    )


def _truthy_env(env: Mapping[str, str], key: str, default: str) -> bool:
    return str(env.get(key, default)).strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _jdy_qr_selector_from_env(env: Mapping[str, str]) -> str:
    configured = str(env.get("JDY_QR_SELECTOR") or env.get("WECOM_QR_SELECTOR") or "").strip()
    return _merge_selector_lists(configured, DEFAULT_QR_SELECTOR)


def _merge_selector_lists(*selector_lists: str) -> str:
    selectors = []
    seen = set()
    for selector_list in selector_lists:
        for selector in str(selector_list or "").split(","):
            item = selector.strip()
            if item and item not in seen:
                selectors.append(item)
                seen.add(item)
    return ", ".join(selectors)


def _missing_required_fields(context: Dict[str, Any]) -> list[str]:
    bind_input = build_bind_input_from_context(context)
    missing = []
    if not bind_input.enterprise_name:
        missing.append("enterprise_name")
    if not bind_input.plain_corp_id:
        missing.append("corp_id")
    if not bind_input.requested_user_id:
        missing.append("userid")
    return missing


def _missing_required_business_result(missing: list[str], mode: Optional[str] = None) -> Dict[str, Any]:
    reason_by_field = {
        "enterprise_name": "missing_enterprise_name",
        "corp_id": "missing_corp_id",
        "userid": "missing_userid",
    }
    result = {
        "status": "business_unexecutable",
        "reason": reason_by_field.get(missing[0], "missing_required_bind_context")
        if len(missing) == 1
        else "missing_required_bind_context",
        "missing_fields": list(missing),
    }
    if mode:
        result["mode"] = mode
    return result


def _coerce_business_unexecutable_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("status") == "blocked" and result.get("reason") in BUSINESS_UNEXECUTABLE_REASONS:
        result["status"] = "business_unexecutable"
    return result


def _first_text(context: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = context.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _parse_int(raw: Any, default: int) -> int:
    try:
        if raw is not None and str(raw).strip() != "":
            return int(str(raw).strip())
    except ValueError:
        return default
    return default
