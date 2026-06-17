import re
import uuid
from typing import Any, Dict, Iterable, List, Optional


SENSITIVE_FIELD_NAMES = {
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

REDACTION_PATTERNS = (
    re.compile(r"Authorization:\s*Bearer\s+[^\s,;]+", re.IGNORECASE),
    re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE),
    re.compile(r"([\"']?\b(?:token|secret|password|api[_-]key)[\"']?\s*[:=]\s*[\"']?)([^\"'\s&;,}]+)([\"']?)", re.IGNORECASE),
)

MAX_ERROR_MESSAGE_LENGTH = 500


def _iter_sensitive_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in SENSITIVE_FIELD_NAMES:
                yield normalized
            yield from _iter_sensitive_keys(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_sensitive_keys(item)


def ensure_diagnostic_payload_safe(payload: Dict[str, Any]) -> None:
    for key in _iter_sensitive_keys(payload):
        raise ValueError("Diagnostic payload contains sensitive key: %s" % key)


def sanitize_diagnostic_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_diagnostic_payload_safe(payload)
    return _sanitize_value(payload)


def _redact_string(value: str) -> str:
    redacted = value
    redacted = REDACTION_PATTERNS[0].sub("Authorization: Bearer [REDACTED]", redacted)
    redacted = REDACTION_PATTERNS[1].sub("Bearer [REDACTED]", redacted)
    redacted = REDACTION_PATTERNS[2].sub(lambda match: "%s[REDACTED]%s" % (match.group(1), match.group(3)), redacted)
    if len(redacted) > MAX_ERROR_MESSAGE_LENGTH:
        return redacted[:MAX_ERROR_MESSAGE_LENGTH] + "...[truncated]"
    return redacted


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _clean_error(error: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key in ("at", "error_type", "step_key", "message"):
        value = error.get(key)
        if value is not None:
            text = str(value)
            if key == "message":
                text = _redact_string(text)
            cleaned[key] = text
    return cleaned


def build_diagnostic_summary(
    machine_id: str,
    robot_id: str,
    task_id: Optional[str],
    mode: str,
    hostname: str,
    session_name: str,
    interactive_desktop: bool,
    screen_resolution: str,
    display_scaling: str,
    pid: int,
    service_version: str,
    started_at: str,
    current_task_id: Optional[str],
    wss_connected: bool,
    last_heartbeat_at: Optional[str],
    log_path: str,
    artifact_dir: str,
    sqlite_path: str,
    recent_errors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = {
        "diagnostic_id": "diag_%s" % uuid.uuid4(),
        "machine_id": machine_id,
        "robot_id": robot_id,
        "task_id": task_id,
        "mode": mode,
        "windows": {
            "hostname": hostname,
            "session_name": session_name,
            "interactive_desktop": interactive_desktop,
            "screen_resolution": screen_resolution,
            "display_scaling": display_scaling,
        },
        "worker": {
            "pid": pid,
            "service_version": service_version,
            "started_at": started_at,
            "current_task_id": current_task_id,
        },
        "network": {
            "wss_connected": wss_connected,
            "last_heartbeat_at": last_heartbeat_at,
        },
        "local_refs": {
            "log_path_hint": log_path,
            "artifact_dir_hint": artifact_dir,
            "sqlite_path_hint": sqlite_path,
        },
        "recent_errors": [_clean_error(error) for error in recent_errors],
    }
    return sanitize_diagnostic_payload(summary)
