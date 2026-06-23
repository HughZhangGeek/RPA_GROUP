import asyncio
import inspect
import json
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
        message_reporter: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.handlers = handlers
        self.diagnostics = diagnostics if diagnostics is not None else getattr(handlers, "diagnostics", {})
        self.event_logger = event_logger
        self.message_reporter = message_reporter

    async def run_until_idle(self) -> None:
        await self.transport.send_json(build_worker_hello(self.config, self.diagnostics))
        self._log("worker hello sent worker_id=%s simulate=%s" % (self.config.worker_id, self.config.simulate))
        while True:
            message = await self.transport.receive_json()
            if message is None:
                self._log("worker idle")
                return
            message_type = message.get("type")
            if message_type == "worker.accepted":
                self._log("worker accepted worker_id=%s" % _safe_text(message.get("worker_id")))
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
        await self._send_worker_message({"type": "task.accepted", "task_id": task_id})
        self._log("task accepted task_id=%s" % _safe_text(task_id))
        await self._send_worker_message(
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
            await self._send_worker_message(
                {
                    "type": "task.completed",
                    "task_id": task_id,
                    "status": "failed",
                    "error_message": _redact_string(str(exc)),
                }
            )
            self._log("task completed task_id=%s status=failed" % _safe_text(task_id))
            return
        if isinstance(result, WorkerTaskResult):
            for progress in result.progress:
                payload = {"type": "task.progress", "task_id": task_id}
                payload.update(progress)
                await self._send_worker_message(payload)
                self._log(
                    "task progress task_id=%s status=%s"
                    % (_safe_text(task_id), _safe_text(progress.get("status")))
                )
            await self._send_worker_message(
                {
                    "type": "task.completed",
                    "task_id": task_id,
                    "status": _worker_completed_status(result.status),
                    "result": result.result,
                }
            )
            self._log("task completed task_id=%s status=%s" % (_safe_text(task_id), _safe_text(result.status)))
            return
        await self._send_worker_message(
            {
                "type": "task.completed",
                "task_id": task_id,
                "status": "succeeded",
                "result": result,
            }
        )
        self._log("task completed task_id=%s status=succeeded" % _safe_text(task_id))

    async def _send_worker_message(self, payload: Dict[str, Any]) -> None:
        send_error = None
        try:
            await self.transport.send_json(payload)
        except Exception as exc:
            send_error = exc
        if self.message_reporter is not None:
            try:
                reported = self.message_reporter(dict(payload))
                if inspect.isawaitable(reported):
                    await reported
            except Exception as exc:
                self._log("worker message reporter failed: %s" % _safe_text(exc))
        if send_error is not None:
            raise send_error

    def _log(self, message: str) -> None:
        if self.event_logger is not None:
            self.event_logger(_redact_string(message))


def _safe_text(value: Any) -> str:
    return _redact_string(str(value or ""))


def _worker_completed_status(status: str) -> str:
    return "failed" if status in {"failed", "blocked"} else "succeeded"


class HttpWorkerMessageReporter:
    def __init__(self, config: C360WorkerConfig, timeout_seconds: float = 10.0):
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.url = "%s/v1/rpa/workers/messages" % config.base_url.rstrip("/")

    async def __call__(self, payload: Dict[str, Any]) -> None:
        await asyncio.to_thread(self._post, payload)

    def _post(self, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-RPA-Worker-Token": self.config.worker_token,
                "X-RPA-Worker-Id": self.config.worker_id,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            response.read()


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
