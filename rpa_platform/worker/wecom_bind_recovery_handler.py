from typing import Any, Dict

from rpa_platform.domain.redaction import mask_identifier, redact_context
from rpa_platform.worker.c360_worker_runtime import WorkerTaskResult


class WecomBindRecoveryTaskHandler:
    def __init__(self, recovery: Any):
        self.recovery = recovery

    async def handle(self, dispatch: Dict[str, Any]) -> WorkerTaskResult:
        task_type = _task_type(dispatch)
        if task_type != "wecom_bind_service":
            raise ValueError("Unsupported task_type: %s" % task_type)

        task_id = str(dispatch.get("task_id", ""))
        payload = dispatch.get("payload") if isinstance(dispatch.get("payload"), dict) else {}
        recovery_result = self.recovery.run(task_id=task_id, context=dict(payload))
        safe_result = _redact_bind_payload(dict(recovery_result))
        status = str(safe_result.get("status") or "failed")

        if status == "waiting_login":
            safe_result["manual_action"] = "scan_wecom_admin_qr"
            return WorkerTaskResult(
                status="manual_action_required",
                result=safe_result,
                progress=[
                    {
                        "status": "waiting_login",
                        "message": "wecom admin QR notification sent",
                    }
                ],
            )

        return WorkerTaskResult(
            status=status,
            result=safe_result,
            progress=[
                {
                    "status": status,
                    "message": "wecom bind readonly preflight completed",
                }
            ],
        )


def _task_type(dispatch: Dict[str, Any]) -> str:
    payload = dispatch.get("payload")
    if isinstance(payload, dict) and payload.get("task_type"):
        return str(payload["task_type"])
    return str(dispatch.get("task_type") or dispatch.get("route_key") or "")


def _redact_bind_payload(value: Dict[str, Any]) -> Dict[str, Any]:
    redacted = redact_context(value)
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
