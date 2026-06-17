import uuid
from typing import Any, Dict, List, Optional


SENSITIVE_KEYS = {
    "cookie",
    "cookies",
    "sid",
    "vst",
    "monitor",
    "token",
    "encoding_aes_key",
    "encodingaeskey",
    "kitsecret",
    "headers",
}


def _clean_error(error: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key in ("at", "error_type", "step_key", "message"):
        value = error.get(key)
        if value is not None:
            cleaned[key] = str(value)
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
    rendered = str(summary).lower()
    for key in SENSITIVE_KEYS:
        if key in rendered:
            raise ValueError("Diagnostic summary contains sensitive key: %s" % key)
    return summary
