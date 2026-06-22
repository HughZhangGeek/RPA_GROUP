import os
from typing import Any, Dict, Mapping, Optional

from rpa_platform.worker.c360_worker_client import C360WorkerConfig
from rpa_platform.worker.simulated_handlers import SimulatedTaskHandlers


class C360TaskHandlers:
    def __init__(
        self,
        diagnostics: Dict[str, Any],
        wecom_bind_handler: Any,
        wecom_bind_unattended_handler: Any = None,
        env: Optional[Mapping[str, str]] = None,
    ):
        self.diagnostics = diagnostics
        self._safe_handlers = SimulatedTaskHandlers(diagnostics)
        self._wecom_bind_handler = wecom_bind_handler
        self._wecom_bind_unattended_handler = wecom_bind_unattended_handler
        self._env = dict(env or {})

    async def handle(self, dispatch: Dict[str, Any]) -> Any:
        task_type = _task_type(dispatch)
        if task_type in {"diagnostics", "runtime_health_check"}:
            return await self._safe_handlers.handle(dispatch)
        if task_type == "wecom_bind_service":
            payload = dispatch.get("payload") if isinstance(dispatch.get("payload"), dict) else {}
            if (
                self._wecom_bind_unattended_handler is not None
                and is_unattended_write_enabled(self._env, payload)
            ):
                return await self._wecom_bind_unattended_handler.handle(dispatch)
            return await self._wecom_bind_handler.handle(dispatch)
        raise ValueError("Unsupported task_type: %s" % task_type)


def build_c360_task_handlers(
    config: C360WorkerConfig,
    diagnostics: Dict[str, Any],
    env: Optional[Mapping[str, str]] = None,
) -> Any:
    if config.simulate:
        return SimulatedTaskHandlers(diagnostics)
    from rpa_platform.worker.wecom_bind_real_recovery import (
        build_wecom_bind_recovery_handler_from_env,
        build_wecom_bind_unattended_write_handler_from_env,
    )

    effective_env = dict(env) if env is not None else dict(os.environ)
    return C360TaskHandlers(
        diagnostics=diagnostics,
        wecom_bind_handler=build_wecom_bind_recovery_handler_from_env(effective_env),
        wecom_bind_unattended_handler=build_wecom_bind_unattended_write_handler_from_env(effective_env),
        env=effective_env,
    )


def _task_type(dispatch: Dict[str, Any]) -> str:
    payload = dispatch.get("payload")
    if isinstance(payload, dict) and payload.get("task_type"):
        return str(payload["task_type"])
    return str(dispatch.get("task_type") or dispatch.get("route_key") or "")


def is_unattended_write_enabled(env: Mapping[str, str], payload: Mapping[str, Any]) -> bool:
    return _truthy(env.get("RPA_WORKER_ALLOW_UNATTENDED_WRITE")) and (
        _truthy(payload.get("unattended_write")) or _truthy(payload.get("confirm_write"))
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
