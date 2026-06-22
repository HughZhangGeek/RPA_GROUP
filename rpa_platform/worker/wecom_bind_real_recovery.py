from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from rpa_platform.notifications.wecom_bot import WecomBotClient
from rpa_platform.services.wecom_bind_service import JdyWecomBindInput, RandomWecomSecretGenerator
from rpa_platform.worker.wecom_bind_recovery_handler import WecomBindRecoveryTaskHandler
from rpa_platform.worker.wecom_login_recovery import (
    LoginRecoveryConfig,
    LoginSessionHealthChecker,
    PlaywrightQrArtifactProvider,
    PlaywrightWecomCookieExporter,
    WecomCookieFileReadonlyProbe,
    WecomCookieSessionRefresher,
    WecomLoginRecoveryOrchestrator,
    WecomQrLoginNotifier,
)
from scripts.dev.check_wecom_bind_real_readonly import build_real_clients, run_readonly_preflight


class RealWecomBindRecovery:
    def __init__(self, orchestrator_factory: Callable[[Dict[str, Any]], Any]):
        self.orchestrator_factory = orchestrator_factory

    def run(self, task_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        missing = _missing_required_fields(context)
        if missing:
            return {
                "status": "blocked",
                "reason": "missing_required_bind_context",
                "missing_fields": missing,
            }
        build_bind_input_from_context(context)
        orchestrator = self.orchestrator_factory(context)
        return dict(orchestrator.run(task_id=task_id, context=context))


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
            return {
                "mode": "unattended_write",
                "status": "blocked",
                "reason": "missing_required_bind_context",
                "missing_fields": missing,
            }

        from rpa_platform.worker.wecom_bind_unattended_write import (
            default_context_file,
            default_lock_file,
            run_unattended_wecom_bind_write,
        )

        login_recovery = self._build_login_recovery(context)
        recoverable_preflight = dict(login_recovery.run(task_id=task_id, context=context))
        if recoverable_preflight.get("status") not in {"ready_for_real_bind", "manual_confirm_required"}:
            result = dict(recoverable_preflight)
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
            context_file=default_context_file(task_id),
            lock_file=default_lock_file(),
            wait_seconds=self.wait_seconds,
        )

    def _build_login_recovery(self, context: Dict[str, Any]) -> Any:
        if self.login_recovery_factory is not None:
            return self.login_recovery_factory(context)
        config = LoginRecoveryConfig.from_env(self.env)
        return _build_orchestrator(config, context)


def build_bind_input_from_context(context: Dict[str, Any]) -> JdyWecomBindInput:
    return JdyWecomBindInput(
        enterprise_name=str(context.get("enterprise_name") or context.get("企业客户名称") or "").strip(),
        enterprise_short_name=str(context.get("enterprise_short_name") or context.get("企业简称") or "").strip(),
        plain_corp_id=str(context.get("plain_corp_id") or context.get("corp_id") or "").strip(),
        requested_user_id=str(context.get("requested_user_id") or context.get("user_id") or "").strip(),
        suite_id=_parse_int(context.get("suite_id"), 1),
        suite_scenario=str(context.get("suite_scenario") or "main").strip(),
        wecom_suiteid=_parse_int(context.get("wecom_suiteid"), 1009479),
        suite_name=str(context.get("suite_name") or "简道云").strip(),
    )


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
        clients = build_real_clients(
            jdy_cookie_file=str(context.get("jdy_cookie_file") or ""),
            wecom_cookie_file=config.cookie_file,
        )
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


def _missing_required_fields(context: Dict[str, Any]) -> list[str]:
    bind_input = build_bind_input_from_context(context)
    missing = []
    if not bind_input.enterprise_name:
        missing.append("enterprise_name")
    if not bind_input.plain_corp_id:
        missing.append("plain_corp_id")
    if not bind_input.requested_user_id:
        missing.append("requested_user_id")
    return missing


def _parse_int(raw: Any, default: int) -> int:
    try:
        if raw is not None and str(raw).strip() != "":
            return int(str(raw).strip())
    except ValueError:
        return default
    return default
