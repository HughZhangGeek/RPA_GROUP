from typing import Any, Dict

from rpa_platform.worker.diagnostics import sanitize_diagnostic_payload


class SimulatedTaskHandlers:
    def __init__(self, diagnostics: Dict[str, Any]):
        self.diagnostics = diagnostics

    async def handle(self, dispatch: Dict[str, Any]) -> Dict[str, Any]:
        task_type = _task_type(dispatch)
        if task_type == "runtime_health_check":
            return {"ok": True, "simulated": True}
        if task_type == "diagnostics":
            return sanitize_diagnostic_payload(dict(self.diagnostics))
        if task_type == "wecom_bind_service":
            return {"simulated": True, "handler": "wecom_bind_service"}
        raise ValueError("Unsupported task_type: %s" % task_type)


def _task_type(dispatch: Dict[str, Any]) -> str:
    payload = dispatch.get("payload")
    if isinstance(payload, dict) and payload.get("task_type"):
        return str(payload["task_type"])
    return str(dispatch.get("task_type") or dispatch.get("route_key") or "")
