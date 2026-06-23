import asyncio
import inspect
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from rpa_platform.worker.c360_worker_client import (
    C360WorkerConfig,
    authorization_headers,
    build_worker_hello,
)
from rpa_platform.worker.diagnostics import _redact_string


class AsyncJsonTransport(Protocol):
    async def send_json(self, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    async def receive_json(self) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


@dataclass(frozen=True)
class WorkerTaskResult:
    status: str
    result: Dict[str, Any] = field(default_factory=dict)
    progress: List[Dict[str, Any]] = field(default_factory=list)


class C360WorkerRuntime:
    def __init__(
        self,
        config: C360WorkerConfig,
        transport: AsyncJsonTransport,
        handlers: Any,
        diagnostics: Optional[Dict[str, Any]] = None,
        event_logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.handlers = handlers
        self.diagnostics = diagnostics if diagnostics is not None else getattr(handlers, "diagnostics", {})
        self.event_logger = event_logger
        self._pending_messages: List[Dict[str, Any]] = []

    async def run_until_idle(self) -> None:
        await self.transport.send_json(build_worker_hello(self.config, self.diagnostics))
        self._log("worker hello sent worker_id=%s simulate=%s" % (self.config.worker_id, self.config.simulate))
        while True:
            message = await self._receive_next_message()
            if message is None:
                self._log("worker idle")
                return
            message_type = message.get("type")
            if message_type == "worker.accepted":
                self._log("worker accepted worker_id=%s" % _safe_text(message.get("worker_id")))
                continue
            if message_type == "worker.message_ack":
                self._log(
                    "worker message ack task_id=%s message_type=%s handled=%s"
                    % (
                        _safe_text(message.get("task_id")),
                        _safe_text(message.get("message_type")),
                        bool(message.get("handled")),
                    )
                )
                continue
            if message_type == "task.dispatch":
                self._log(
                    "task received task_id=%s task_type=%s simulate=%s"
                    % (
                        _safe_text(message.get("task_id")),
                        _safe_text(message.get("task_type") or message.get("route_key")),
                        bool(message.get("simulate")),
                    )
                )
                await self._handle_dispatch(message)

    async def _handle_dispatch(self, dispatch: Dict[str, Any]) -> None:
        task_id = str(dispatch.get("task_id", ""))
        await self.transport.send_json({"type": "task.accepted", "task_id": task_id})
        self._log("task accepted task_id=%s" % _safe_text(task_id))
        await self.transport.send_json(
            {
                "type": "task.progress",
                "task_id": task_id,
                "status": "running",
                "message": "simulated handler started" if self.config.simulate else "handler started",
            }
        )
        self._log("task progress task_id=%s status=running" % _safe_text(task_id))
        try:
            result = await self.handlers.handle(dispatch)
        except Exception as exc:
            completed_payload = {
                "type": "task.completed",
                "task_id": task_id,
                "status": "failed",
                "error_message": _redact_string(str(exc)),
            }
            await self.transport.send_json(completed_payload)
            self._log("task completed task_id=%s status=failed" % _safe_text(task_id))
            await self._ensure_completed_ack(completed_payload)
            return
        if isinstance(result, WorkerTaskResult):
            for progress in result.progress:
                payload = {"type": "task.progress", "task_id": task_id}
                payload.update(progress)
                await self.transport.send_json(payload)
                self._log(
                    "task progress task_id=%s status=%s"
                    % (_safe_text(task_id), _safe_text(progress.get("status")))
                )
            completed_payload = {
                "type": "task.completed",
                "task_id": task_id,
                "status": _worker_completed_status(result.status),
                "result": result.result,
            }
            await self.transport.send_json(completed_payload)
            self._log("task completed task_id=%s status=%s" % (_safe_text(task_id), _safe_text(result.status)))
            await self._ensure_completed_ack(completed_payload)
            return
        completed_payload = {
            "type": "task.completed",
            "task_id": task_id,
            "status": "succeeded",
            "result": result,
        }
        await self.transport.send_json(completed_payload)
        self._log("task completed task_id=%s status=succeeded" % _safe_text(task_id))
        await self._ensure_completed_ack(completed_payload)

    async def _receive_next_message(self) -> Optional[Dict[str, Any]]:
        if self._pending_messages:
            return self._pending_messages.pop(0)
        return await self.transport.receive_json()

    async def _ensure_completed_ack(self, completed_payload: Dict[str, Any]) -> None:
        task_id = str(completed_payload.get("task_id") or "")
        timeout_seconds = float(self.config.completion_ack_timeout_seconds)
        try:
            while True:
                message = await asyncio.wait_for(self.transport.receive_json(), timeout=timeout_seconds)
                if message is None:
                    break
                if _is_matching_ack(message, task_id=task_id, message_type="task.completed"):
                    if message.get("handled"):
                        self._log("task completed ack task_id=%s handled=True" % _safe_text(task_id))
                        return
                    break
                self._pending_messages.append(message)
        except asyncio.TimeoutError:
            pass

        if not self.config.http_event_fallback_enabled:
            self._log("task completed ack missing task_id=%s fallback=disabled" % _safe_text(task_id))
            return
        self._log("task completed ack missing task_id=%s fallback=http" % _safe_text(task_id))
        await asyncio.to_thread(_post_worker_message_fallback, self.config, completed_payload)
        self._log("task completed fallback sent task_id=%s" % _safe_text(task_id))

    def _log(self, message: str) -> None:
        if self.event_logger is not None:
            self.event_logger(_redact_string(message))


def _safe_text(value: Any) -> str:
    return _redact_string(str(value or ""))


def _worker_completed_status(status: str) -> str:
    return "failed" if status in {"failed", "blocked"} else "succeeded"


def _is_matching_ack(message: Dict[str, Any], *, task_id: str, message_type: str) -> bool:
    return (
        message.get("type") == "worker.message_ack"
        and str(message.get("task_id") or "") == task_id
        and message.get("message_type") == message_type
    )


def _post_worker_message_fallback(config: C360WorkerConfig, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config.message_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-RPA-Worker-Token": config.worker_token,
            "X-RPA-Worker-Id": config.worker_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(3.0, config.completion_ack_timeout_seconds)) as response:
            if response.status >= 400:
                raise RuntimeError("fallback HTTP status %s" % response.status)
    except urllib.error.URLError as exc:
        raise RuntimeError("fallback HTTP failed: %s" % exc) from exc


class WebSocketsJsonTransport:
    def __init__(self, websocket: Any):
        self.websocket = websocket

    @classmethod
    async def connect(cls, config: C360WorkerConfig) -> "WebSocketsJsonTransport":
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Python package 'websockets' is required to connect C360 worker WSS") from exc

        connect = websockets.connect
        headers = authorization_headers(config)
        signature = inspect.signature(connect)
        header_arg = "additional_headers" if "additional_headers" in signature.parameters else "extra_headers"
        websocket = await connect(config.ws_url, **{header_arg: headers})
        return cls(websocket)

    async def send_json(self, payload: Dict[str, Any]) -> None:
        import json

        await self.websocket.send(json.dumps(payload, ensure_ascii=False))

    async def receive_json(self) -> Optional[Dict[str, Any]]:
        import json

        try:
            raw = await self.websocket.recv()
        except asyncio.CancelledError:
            raise
        except Exception:
            return None
        return json.loads(raw)


class AioHttpJsonTransport:
    def __init__(self, websocket: Any, session: Any):
        self.websocket = websocket
        self.session = session

    @classmethod
    async def connect(cls, config: C360WorkerConfig) -> "AioHttpJsonTransport":
        try:
            import aiohttp
        except ImportError as exc:
            raise RuntimeError("Python package 'aiohttp' is required to connect C360 worker WSS") from exc

        session = aiohttp.ClientSession()
        try:
            websocket = await session.ws_connect(config.ws_url, headers=authorization_headers(config))
        except Exception:
            await session.close()
            raise
        return cls(websocket, session)

    async def send_json(self, payload: Dict[str, Any]) -> None:
        import json

        await self.websocket.send_str(json.dumps(payload, ensure_ascii=False))

    async def receive_json(self) -> Optional[Dict[str, Any]]:
        import json

        try:
            message = await self.websocket.receive()
        except asyncio.CancelledError:
            raise
        except Exception:
            return None
        data = getattr(message, "data", None)
        if not data:
            return None
        if not isinstance(data, (str, bytes, bytearray)):
            return None
        return json.loads(data)

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()


async def connect_json_transport(config: C360WorkerConfig) -> AsyncJsonTransport:
    try:
        return await WebSocketsJsonTransport.connect(config)
    except RuntimeError as exc:
        if "websockets" not in str(exc):
            raise
    return await AioHttpJsonTransport.connect(config)
