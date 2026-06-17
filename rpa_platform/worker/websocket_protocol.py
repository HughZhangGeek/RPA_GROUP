from dataclasses import dataclass
from typing import Any, Dict, Optional


SENSITIVE_KEYS = {
    "api-key",
    "api_key",
    "authorization",
    "cookie",
    "cookies",
    "encoding_aes_key",
    "encodingaeskey",
    "headers",
    "kitsecret",
    "monitor",
    "password",
    "secret",
    "sid",
    "token",
    "vst",
}

SAFE_KEY_EXCEPTIONS = {
    "idempotency_key",
    "step_key",
    "task_id",
}


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower()
    if normalized in SAFE_KEY_EXCEPTIONS:
        return False
    return normalized in SENSITIVE_KEYS or "secret" in normalized or "token" in normalized


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_sensitive_key(key):
                return True
            if _contains_sensitive_key(child):
                return True
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def build_envelope(
    message_type: str,
    machine_id: str,
    robot_id: str,
    payload: Dict[str, Any],
    message_id: str,
    sent_at: str,
) -> Dict[str, Any]:
    envelope = {
        "type": message_type,
        "message_id": message_id,
        "sent_at": sent_at,
        "machine_id": machine_id,
        "robot_id": robot_id,
        "payload": payload,
    }
    if _contains_sensitive_key(envelope):
        raise ValueError("WebSocket envelope contains sensitive keys")
    return envelope


def parse_envelope(raw: Dict[str, Any]) -> Dict[str, Any]:
    required = ["type", "message_id", "sent_at", "machine_id", "robot_id", "payload"]
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError("Missing envelope fields: %s" % ", ".join(missing))
    if not isinstance(raw["payload"], dict):
        raise ValueError("Envelope payload must be an object")
    if _contains_sensitive_key(raw):
        raise ValueError("WebSocket envelope contains sensitive keys")
    return dict(raw)


@dataclass(frozen=True)
class WorkerRegisterPayload:
    hostname: str
    service_version: str
    capabilities: Dict[str, Any]
    login_health: Dict[str, Any]
    current_task: Optional[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hostname": self.hostname,
            "service_version": self.service_version,
            "capabilities": dict(self.capabilities),
            "login_health": dict(self.login_health),
            "current_task": self.current_task,
        }
