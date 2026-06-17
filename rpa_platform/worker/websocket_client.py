import socket
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from rpa_platform.worker.diagnostics import sanitize_diagnostic_payload
from rpa_platform.worker.websocket_protocol import (
    WorkerRegisterPayload,
    build_envelope,
    parse_envelope,
)


def _now_iso() -> str:
    return datetime.now().isoformat()


class WorkerWebSocketClient:
    def __init__(
        self,
        transport: Any,
        machine_id: str,
        robot_id: str,
        hostname: Optional[str] = None,
        service_version: str = "0.1.0",
        capabilities: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.transport = transport
        self.machine_id = machine_id
        self.robot_id = robot_id
        self.hostname = hostname or socket.gethostname()
        self.service_version = service_version
        self.capabilities = capabilities or {}

    def register(self, login_health: Dict[str, Any], current_task: Optional[Dict[str, Any]]) -> None:
        payload = WorkerRegisterPayload(
            hostname=self.hostname,
            service_version=self.service_version,
            capabilities=self.capabilities,
            login_health=login_health,
            current_task=current_task,
        ).to_dict()
        self.transport.send_json(self._envelope("worker.register", payload))

    def heartbeat(
        self,
        status: str,
        current_task_id: Optional[str],
        login_health: Dict[str, Any],
        queue_depth_local: int = 0,
    ) -> None:
        self.transport.send_json(
            self._envelope(
                "worker.heartbeat",
                {
                    "status": status,
                    "current_task_id": current_task_id,
                    "queue_depth_local": queue_depth_local,
                    "login_health": login_health,
                },
            )
        )

    def receive_once(self, dispatch_handler: Callable[[Dict[str, Any]], Any]) -> Optional[Dict[str, Any]]:
        raw = self.transport.receive_json()
        if raw is None:
            return None
        envelope = parse_envelope(raw)
        if envelope["type"] != "task.dispatch":
            return envelope
        payload = envelope["payload"]
        handler_result = dispatch_handler(payload)
        if not isinstance(handler_result, dict):
            handler_result = {
                "accepted": False,
                "local_execution_id": None,
                "reject_reason": "handler_result_missing",
            }
        self.transport.send_json(
            self._envelope(
                "task.ack",
                {
                    "task_id": payload["task_id"],
                    "dispatch_message_id": envelope["message_id"],
                    "accepted": bool(handler_result.get("accepted")),
                    "local_execution_id": handler_result.get("local_execution_id"),
                    "reject_reason": handler_result.get("reject_reason", ""),
                },
            )
        )
        return envelope

    def send_progress(self, payload: Dict[str, Any]) -> None:
        self.transport.send_json(self._envelope("task.progress", payload))

    def send_result(self, payload: Dict[str, Any]) -> None:
        self.transport.send_json(self._envelope("task.result", payload))

    def send_error(self, payload: Dict[str, Any]) -> None:
        self.transport.send_json(self._envelope("task.error", payload))

    def send_diagnostics(self, payload: Dict[str, Any]) -> None:
        self.transport.send_json(self._envelope("worker.diagnostics", sanitize_diagnostic_payload(payload)))

    def _envelope(self, message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_envelope(
            message_type=message_type,
            machine_id=self.machine_id,
            robot_id=self.robot_id,
            payload=payload,
            message_id="msg_%s" % uuid.uuid4(),
            sent_at=_now_iso(),
        )
