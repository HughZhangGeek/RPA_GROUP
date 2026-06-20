from typing import Any, Dict, Mapping, Optional

from rpa_platform.worker.c360_worker_client import C360WorkerConfig
from rpa_platform.worker.simulated_handlers import SimulatedTaskHandlers


class C360TaskHandlers:
    def __init__(self, diagnostics: Dict[str, Any], wecom_bind_handler: Any):
        self.diagnostics = diagnostics
        self._safe_handlers = SimulatedTaskHandlers(diagnostics)
        self._wecom_bind_handler = wecom_bind_handler

    async def handle(self, dispatch: Dict[str, Any]) -> Any:
        task_type = _task_type(dispatch)
        if task_type in {"diagnostics", "runtime_health_check"}:
            return await self._safe_handlers.handle(dispatch)
        if task_type == "wecom_bind_service":
            return await self._wecom_bind_handler.handle(dispatch)
        raise ValueError("Unsupported task_type: %s" % task_type)


def build_c360_task_handlers(
    config: C360WorkerConfig,
    diagnostics: Dict[str, Any],
    env: Optional[Mapping[str, str]] = None,
) -> Any:
    if config.simulate:
        return SimulatedTaskHandlers(diagnostics)
    from rpa_platform.worker.wecom_bind_real_recovery import build_wecom_bind_recovery_handler_from_env

    return C360TaskHandlers(
        diagnostics=diagnostics,
        wecom_bind_handler=build_wecom_bind_recovery_handler_from_env(env),
    )


def _task_type(dispatch: Dict[str, Any]) -> str:
    payload = dispatch.get("payload")
    if isinstance(payload, dict) and payload.get("task_type"):
        return str(payload["task_type"])
    return str(dispatch.get("task_type") or dispatch.get("route_key") or "")
