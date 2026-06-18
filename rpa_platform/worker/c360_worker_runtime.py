import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

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
    ) -> None:
        self.config = config
        self.transport = transport
        self.handlers = handlers
        self.diagnostics = diagnostics if diagnostics is not None else getattr(handlers, "diagnostics", {})

    async def run_until_idle(self) -> None:
        await self.transport.send_json(build_worker_hello(self.config, self.diagnostics))
        while True:
            message = await self.transport.receive_json()
            if message is None:
                return
            message_type = message.get("type")
            if message_type == "worker.accepted":
                continue
            if message_type == "task.dispatch":
                await self._handle_dispatch(message)

    async def _handle_dispatch(self, dispatch: Dict[str, Any]) -> None:
        task_id = str(dispatch.get("task_id", ""))
        await self.transport.send_json({"type": "task.accepted", "task_id": task_id})
        await self.transport.send_json(
            {
                "type": "task.progress",
                "task_id": task_id,
                "status": "running",
                "message": "simulated handler started" if self.config.simulate else "handler started",
            }
        )
        try:
            result = await self.handlers.handle(dispatch)
        except Exception as exc:
            await self.transport.send_json(
                {
                    "type": "task.completed",
                    "task_id": task_id,
                    "status": "failed",
                    "error_message": _redact_string(str(exc)),
                }
            )
            return
        if isinstance(result, WorkerTaskResult):
            for progress in result.progress:
                payload = {"type": "task.progress", "task_id": task_id}
                payload.update(progress)
                await self.transport.send_json(payload)
            await self.transport.send_json(
                {
                    "type": "task.completed",
                    "task_id": task_id,
                    "status": result.status,
                    "result": result.result,
                }
            )
            return
        await self.transport.send_json(
            {
                "type": "task.completed",
                "task_id": task_id,
                "status": "succeeded",
                "result": result,
            }
        )


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
