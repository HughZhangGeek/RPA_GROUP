import os
import platform
import socket
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlparse, urlunparse

from rpa_platform.worker.diagnostics import sanitize_diagnostic_payload


C360_WORKER_WS_PATH = "/v1/rpa/workers/ws"
C360_WORKER_MESSAGE_PATH = "/v1/rpa/workers/messages"
DEFAULT_CAPABILITIES = ["wecom_bind_service", "diagnostics", "runtime_health_check"]


class C360WorkerConfigError(ValueError):
    pass


@dataclass(frozen=True)
class C360WorkerConfig:
    base_url: str
    ws_url: str
    message_url: str
    worker_token: str
    worker_id: str
    capabilities: List[str]
    simulate: bool = True
    completion_ack_timeout_seconds: float = 5.0
    http_event_fallback_enabled: bool = True


def build_c360_worker_ws_url(base_url: str) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    if parsed.scheme not in ("http", "https", "ws", "wss"):
        raise C360WorkerConfigError("C360_BASE_URL must start with http:// or https://")
    if not parsed.netloc:
        raise C360WorkerConfigError("C360_BASE_URL must include host")

    scheme = "wss" if parsed.scheme in ("https", "wss") else "ws"
    base_path = parsed.path.rstrip("/")
    return urlunparse((scheme, parsed.netloc, "%s%s" % (base_path, C360_WORKER_WS_PATH), "", "", ""))


def build_c360_worker_message_url(base_url: str) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    if parsed.scheme not in ("http", "https", "ws", "wss"):
        raise C360WorkerConfigError("C360_BASE_URL must start with http:// or https://")
    if not parsed.netloc:
        raise C360WorkerConfigError("C360_BASE_URL must include host")

    scheme = "https" if parsed.scheme in ("https", "wss") else "http"
    base_path = parsed.path.rstrip("/")
    return urlunparse((scheme, parsed.netloc, "%s%s" % (base_path, C360_WORKER_MESSAGE_PATH), "", "", ""))


def load_c360_worker_config_from_env(env: Optional[Mapping[str, str]] = None) -> C360WorkerConfig:
    values = env or os.environ
    base_url = _required(values, "C360_BASE_URL")
    token = _required(values, "RPA_WORKER_TOKEN")
    worker_id = values.get("RPA_WORKER_ID") or values.get("RPA_ROBOT_ID") or "win-sim-001"
    capabilities = _split_capabilities(values.get("RPA_WORKER_CAPABILITIES", ""))
    simulate = _parse_bool(values.get("RPA_WORKER_SIMULATE", "true"))
    ack_timeout = _parse_float(values.get("RPA_WORKER_COMPLETION_ACK_TIMEOUT_SECONDS", "5"), default=5.0)
    fallback_enabled = _parse_bool(values.get("RPA_WORKER_HTTP_EVENT_FALLBACK_ENABLED", "true"))
    return C360WorkerConfig(
        base_url=base_url.rstrip("/"),
        ws_url=build_c360_worker_ws_url(base_url),
        message_url=build_c360_worker_message_url(base_url),
        worker_token=token,
        worker_id=worker_id,
        capabilities=capabilities,
        simulate=simulate,
        completion_ack_timeout_seconds=max(0.1, ack_timeout),
        http_event_fallback_enabled=fallback_enabled,
    )


def build_worker_hello(config: C360WorkerConfig, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "worker.hello",
        "worker_id": config.worker_id,
        "capabilities": list(config.capabilities),
        "simulate": bool(config.simulate),
        "diagnostics": sanitize_diagnostic_payload(diagnostics),
    }


def build_default_diagnostics(
    config: C360WorkerConfig,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    values = env or os.environ
    session_name = values.get("SESSIONNAME") or values.get("TERM_SESSION_ID") or "unknown"
    diagnostics = {
        "machine_id": config.worker_id,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "interactive_desktop": bool(session_name and session_name != "unknown"),
        "session_name": session_name,
        "resolution": values.get("RPA_SCREEN_RESOLUTION", "unknown"),
        "dpi_scale": values.get("RPA_DPI_SCALE", "unknown"),
    }
    return sanitize_diagnostic_payload(diagnostics)


def authorization_headers(config: C360WorkerConfig) -> Dict[str, str]:
    return {"X-RPA-Worker-Token": config.worker_token}


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise C360WorkerConfigError("%s is required" % key)
    return value


def _split_capabilities(raw: str) -> List[str]:
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items or list(DEFAULT_CAPABILITIES)


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _parse_float(raw: str, *, default: float) -> float:
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default
