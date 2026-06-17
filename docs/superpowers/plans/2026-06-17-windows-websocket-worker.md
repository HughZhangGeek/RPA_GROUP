# Windows WebSocket Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows RPA worker service that WebSocket-connects back to jdycsm, receives dispatched tasks, executes existing `rpa_platform` runner logic one task at a time, and reports progress/results without uploading sensitive browser credentials.

**Architecture:** jdycsm remains the control plane and owns external HTTP APIs, task persistence, dispatch, and audit. Windows owns browser Profile, local execution state, screenshots/logs, and single-concurrency execution through existing `TaskScheduler.run_once()` / runner boundaries. The first implementation should keep transport, protocol models, and runner execution separate so the control-plane API can evolve without rewriting task execution.

**Tech Stack:** Python, FastAPI/WebSocket client library to be selected, SQLite, existing `rpa_platform.storage.SQLiteStore`, existing `rpa_platform.worker.TaskScheduler`, `unittest`/`pytest`.

---

## File Structure

- Create: `rpa_platform/worker/websocket_protocol.py`
  - Dataclasses or typed helpers for message envelopes and payload validation.
- Create: `rpa_platform/worker/machine_identity.py`
  - Stable local `machine_id` loader/generator backed by JSON config.
- Create: `rpa_platform/worker/websocket_client.py`
  - Reconnect loop, register, heartbeat, dispatch receive, ack/progress/result send.
- Create: `rpa_platform/worker/websocket_worker.py`
  - CLI entrypoint that wires env config, machine identity, store, scheduler, runner, and WebSocket client.
- Create: `rpa_platform/worker/diagnostics.py`
  - Windows-safe diagnostic summary builder for session, display, process, paths, and recent errors.
- Modify: `rpa_platform/storage/sqlite_store.py`
  - Add minimal local execution tracking only if existing task tables cannot safely store remote dispatch state.
- Modify: `rpa_platform/domain/state_machine.py`
  - Add remote-only states only if storing them locally is required; otherwise keep `worker_offline` in jdycsm control-plane state.
- Create: `tests/test_platform_websocket_protocol.py`
  - Protocol envelope validation, manual action notification contract, and redaction tests.
- Create: `tests/test_platform_machine_identity.py`
  - Stable UUID persistence tests.
- Create: `tests/test_platform_websocket_worker.py`
  - Fake WebSocket transport tests for register, heartbeat, dispatch ack, idempotent result replay.
- Create: `tests/test_platform_windows_diagnostics.py`
  - Redacted diagnostic summary tests.
- Modify: `docs/rpa_platform_windows_websocket_protocol.md`
  - Keep protocol examples synchronized with code.
- Modify: `docs/rpa_platform_windows_websocket_runbook.md`
  - Keep deployment commands synchronized with entrypoint.

## Task 1: Protocol Message Models

**Files:**
- Create: `rpa_platform/worker/websocket_protocol.py`
- Test: `tests/test_platform_websocket_protocol.py`

- [ ] **Step 1: Write failing protocol tests**

```python
import unittest

from rpa_platform.worker.websocket_protocol import (
    WorkerRegisterPayload,
    build_envelope,
    parse_envelope,
)


class WebSocketProtocolTest(unittest.TestCase):
    def test_builds_register_envelope_without_sensitive_values(self):
        payload = WorkerRegisterPayload(
            hostname="WIN-RPA-01",
            service_version="0.1.0",
            capabilities={"wecom_bind_service": True},
            login_health={"jdy_admin": "ok", "wecom_admin": "ok"},
            current_task=None,
        )

        envelope = build_envelope(
            message_type="worker.register",
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            payload=payload.to_dict(),
            message_id="msg-001",
            sent_at="2026-06-17T10:00:00+08:00",
        )

        self.assertEqual(envelope["type"], "worker.register")
        self.assertEqual(envelope["machine_id"], "mch-001")
        self.assertEqual(envelope["payload"]["hostname"], "WIN-RPA-01")
        self.assertNotIn("cookie", str(envelope).lower())
        self.assertNotIn("encoding_aes_key", str(envelope).lower())

    def test_waiting_login_error_uses_link_only_manual_action(self):
        envelope = build_envelope(
            message_type="task.error",
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            payload={
                "task_id": "task-001",
                "status": "waiting_login",
                "error_type": "LOGIN_REQUIRED",
                "error_message": "企微后台登录态失效，需要人工扫码",
                "step_key": "wecom_submit_online",
                "retryable": True,
                "manual_action": {
                    "action_type": "login_required",
                    "target": "wecom_admin",
                    "notify_audience": "rpa_admins",
                    "notification_channel": "wecom_bot",
                    "notification_mode": "link_only",
                    "handle_url": "https://jdycsm.example.com/rpa/manual-actions/action-001",
                    "qr_delivery": "not_uploaded",
                },
                "artifact_refs": [],
            },
            message_id="msg-002",
            sent_at="2026-06-17T10:03:00+08:00",
        )

        manual_action = envelope["payload"]["manual_action"]
        self.assertEqual(manual_action["notify_audience"], "rpa_admins")
        self.assertEqual(manual_action["notification_mode"], "link_only")
        self.assertEqual(manual_action["qr_delivery"], "not_uploaded")
        self.assertNotIn("qr_image", str(envelope))

    def test_parse_rejects_missing_message_id(self):
        with self.assertRaises(ValueError):
            parse_envelope(
                {
                    "type": "worker.heartbeat",
                    "sent_at": "2026-06-17T10:00:00+08:00",
                    "machine_id": "mch-001",
                    "robot_id": "windows-rpa-01",
                    "payload": {},
                }
            )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_platform_websocket_protocol -v
```

Expected: FAIL because `rpa_platform.worker.websocket_protocol` does not exist.

- [ ] **Step 3: Implement protocol helpers**

```python
from dataclasses import dataclass
from typing import Any, Dict, Optional


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
}


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
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
```

- [ ] **Step 4: Run protocol tests**

```bash
python -m unittest tests.test_platform_websocket_protocol -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rpa_platform/worker/websocket_protocol.py tests/test_platform_websocket_protocol.py
git commit -m "新增 Windows Worker WebSocket 协议模型"
```

## Task 2: Stable Machine Identity

**Files:**
- Create: `rpa_platform/worker/machine_identity.py`
- Test: `tests/test_platform_machine_identity.py`

- [ ] **Step 1: Write failing identity tests**

```python
import json
import tempfile
import unittest
from pathlib import Path

from rpa_platform.worker.machine_identity import load_or_create_machine_id


class MachineIdentityTest(unittest.TestCase):
    def test_creates_and_reuses_machine_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "machine.json"

            first = load_or_create_machine_id(path)
            second = load_or_create_machine_id(path)

            self.assertEqual(first, second)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["machine_id"], first)
            self.assertTrue(first.startswith("mch_"))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_platform_machine_identity -v
```

Expected: FAIL because `machine_identity.py` does not exist.

- [ ] **Step 3: Implement machine identity helper**

```python
import json
import uuid
from datetime import datetime
from pathlib import Path


def load_or_create_machine_id(path: Path) -> str:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        machine_id = data.get("machine_id", "")
        if machine_id:
            return machine_id
    path.parent.mkdir(parents=True, exist_ok=True)
    machine_id = "mch_%s" % str(uuid.uuid4())
    path.write_text(
        json.dumps(
            {
                "machine_id": machine_id,
                "created_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return machine_id
```

- [ ] **Step 4: Run identity tests**

```bash
python -m unittest tests.test_platform_machine_identity -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rpa_platform/worker/machine_identity.py tests/test_platform_machine_identity.py
git commit -m "新增 Windows Worker 稳定机器标识"
```

## Task 3: WebSocket Client with Fake Transport

**Files:**
- Create: `rpa_platform/worker/websocket_client.py`
- Test: `tests/test_platform_websocket_worker.py`

- [ ] **Step 1: Write fake transport tests**

```python
import unittest

from rpa_platform.worker.websocket_client import WorkerWebSocketClient


class FakeTransport:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []

    def send_json(self, payload):
        self.sent.append(payload)

    def receive_json(self):
        if not self.incoming:
            return None
        return self.incoming.pop(0)


class WorkerWebSocketClientTest(unittest.TestCase):
    def test_registers_before_receiving_tasks(self):
        transport = FakeTransport(incoming=[])
        client = WorkerWebSocketClient(
            transport=transport,
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            hostname="WIN-RPA-01",
            service_version="0.1.0",
            capabilities={"wecom_bind_service": True},
        )

        client.register(login_health={"jdy_admin": "ok", "wecom_admin": "ok"}, current_task=None)

        self.assertEqual(transport.sent[0]["type"], "worker.register")
        self.assertEqual(transport.sent[0]["payload"]["hostname"], "WIN-RPA-01")

    def test_dispatch_handler_sends_ack(self):
        transport = FakeTransport(
            incoming=[
                {
                    "type": "task.dispatch",
                    "message_id": "msg-dispatch",
                    "sent_at": "2026-06-17T10:01:00+08:00",
                    "machine_id": "mch-001",
                    "robot_id": "windows-rpa-01",
                    "payload": {
                        "task_id": "task-001",
                        "idempotency_key": "wecom_bind_service:ww001:user-1",
                        "flow_type": "wecom_bind_service",
                        "requested_capability": "wecom_bind_service",
                        "task_payload": {},
                        "runtime_context": {},
                    },
                }
            ]
        )
        handled = []
        client = WorkerWebSocketClient(
            transport=transport,
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            hostname="WIN-RPA-01",
            service_version="0.1.0",
            capabilities={"wecom_bind_service": True},
        )

        client.receive_once(lambda task: handled.append(task) or {"accepted": True, "local_execution_id": "local-001"})

        self.assertEqual(handled[0]["task_id"], "task-001")
        self.assertEqual(transport.sent[0]["type"], "task.ack")
        self.assertTrue(transport.sent[0]["payload"]["accepted"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_platform_websocket_worker -v
```

Expected: FAIL because `websocket_client.py` does not exist.

- [ ] **Step 3: Implement fake-transport client core**

```python
import socket
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from rpa_platform.worker.websocket_protocol import WorkerRegisterPayload, build_envelope, parse_envelope


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

    def receive_once(self, dispatch_handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        raw = self.transport.receive_json()
        if raw is None:
            return None
        envelope = parse_envelope(raw)
        if envelope["type"] != "task.dispatch":
            return envelope
        payload = envelope["payload"]
        handler_result = dispatch_handler(payload)
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

    def _envelope(self, message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_envelope(
            message_type=message_type,
            machine_id=self.machine_id,
            robot_id=self.robot_id,
            payload=payload,
            message_id="msg_%s" % uuid.uuid4(),
            sent_at=_now_iso(),
        )
```

- [ ] **Step 4: Run WebSocket worker tests**

```bash
python -m unittest tests.test_platform_websocket_worker -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rpa_platform/worker/websocket_client.py tests/test_platform_websocket_worker.py
git commit -m "新增 Windows Worker WebSocket 客户端骨架"
```

## Task 4: CLI Entrypoint and Local Dispatch Execution

**Files:**
- Create: `rpa_platform/worker/websocket_worker.py`
- Modify: `tests/test_platform_websocket_worker.py`
- Modify: `docs/rpa_platform_windows_websocket_runbook.md`

- [ ] **Step 1: Add CLI config tests**

```python
import os
import tempfile
import unittest
from pathlib import Path

from rpa_platform.worker.websocket_worker import load_worker_config


class WorkerConfigTest(unittest.TestCase):
    def test_loads_worker_env_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "worker.env"
            env_path.write_text(
                "\n".join(
                    [
                        "RPA_WS_URL=wss://jdycsm.example.com/rpa/ws/worker",
                        "RPA_MACHINE_TOKEN=secret-token",
                        "RPA_ROBOT_ID=windows-rpa-01",
                        "RPA_DB_PATH=C:/rpa_group/data/platform-worker.db",
                        "RPA_MACHINE_CONFIG=C:/rpa_group/config/machine.json",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_worker_config(env_path)

            self.assertEqual(config.ws_url, "wss://jdycsm.example.com/rpa/ws/worker")
            self.assertEqual(config.robot_id, "windows-rpa-01")
            self.assertEqual(config.db_path, "C:/rpa_group/data/platform-worker.db")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_platform_websocket_worker -v
```

Expected: FAIL because `websocket_worker.py` does not exist.

- [ ] **Step 3: Implement env config loader and CLI stub**

```python
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class WorkerConfig:
    ws_url: str
    machine_token: str
    robot_id: str
    db_path: str
    machine_config: str
    capabilities: List[str]


def _read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_worker_config(path: Path) -> WorkerConfig:
    values = _read_env_file(path)
    return WorkerConfig(
        ws_url=values["RPA_WS_URL"],
        machine_token=values["RPA_MACHINE_TOKEN"],
        robot_id=values["RPA_ROBOT_ID"],
        db_path=values["RPA_DB_PATH"],
        machine_config=values.get("RPA_MACHINE_CONFIG", "C:/rpa_group/config/machine.json"),
        capabilities=[
            item.strip()
            for item in values.get("RPA_CAPABILITIES", "").split(",")
            if item.strip()
        ],
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Windows RPA WebSocket worker.")
    parser.add_argument("--env", required=True, help="Path to worker.env")
    args = parser.parse_args(argv)
    config = load_worker_config(Path(args.env))
    print("Loaded worker config for robot_id=%s ws_url=%s" % (config.robot_id, config.ws_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_platform_websocket_worker -v
```

Expected: PASS.

- [ ] **Step 5: Update runbook command if needed**

Ensure `docs/rpa_platform_windows_websocket_runbook.md` uses:

```powershell
python -m rpa_platform.worker.websocket_worker --env C:\rpa_group\config\worker.env
```

- [ ] **Step 6: Commit**

```bash
git add rpa_platform/worker/websocket_worker.py tests/test_platform_websocket_worker.py docs/rpa_platform_windows_websocket_runbook.md
git commit -m "新增 Windows Worker 启动入口"
```

## Task 5: Windows Diagnostics

**Files:**
- Create: `rpa_platform/worker/diagnostics.py`
- Test: `tests/test_platform_windows_diagnostics.py`
- Modify: `rpa_platform/worker/websocket_worker.py`
- Modify: `rpa_platform/worker/websocket_client.py`
- Modify: `docs/rpa_platform_windows_websocket_protocol.md`
- Modify: `docs/rpa_platform_windows_websocket_runbook.md`

- [x] **Step 1: Write failing diagnostics tests**

```python
import unittest

from rpa_platform.worker.diagnostics import build_diagnostic_summary


class WindowsDiagnosticsTest(unittest.TestCase):
    def test_builds_diagnostic_summary_without_sensitive_values(self):
        summary = build_diagnostic_summary(
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            task_id="task-001",
            mode="manual_debug",
            hostname="WIN-RPA-01",
            session_name="console",
            interactive_desktop=True,
            screen_resolution="1920x1080",
            display_scaling="100%",
            pid=1234,
            service_version="0.1.0",
            started_at="2026-06-17T09:55:00+08:00",
            current_task_id="task-001",
            wss_connected=True,
            last_heartbeat_at="2026-06-17T10:03:45+08:00",
            log_path="C:/rpa_group/logs/worker.log",
            artifact_dir="C:/rpa_group/artifacts/task-001",
            sqlite_path="C:/rpa_group/data/platform-worker.db",
            recent_errors=[
                {
                    "at": "2026-06-17T10:03:00+08:00",
                    "error_type": "LOGIN_REQUIRED",
                    "step_key": "wecom_submit_online",
                    "message": "企微后台登录态失效，需要人工扫码",
                    "cookie": "must-not-leak",
                }
            ],
        )

        self.assertEqual(summary["task_id"], "task-001")
        self.assertTrue(summary["windows"]["interactive_desktop"])
        self.assertEqual(summary["windows"]["screen_resolution"], "1920x1080")
        self.assertEqual(summary["local_refs"]["log_path_hint"], "C:/rpa_group/logs/worker.log")
        rendered = str(summary).lower()
        self.assertNotIn("must-not-leak", rendered)
        self.assertNotIn("cookie", rendered)
        self.assertNotIn("encoding_aes_key", rendered)
        self.assertNotIn("kitsecret", rendered)
```

- [x] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_platform_windows_diagnostics -v
```

Expected: FAIL because `rpa_platform.worker.diagnostics` does not exist.

- [x] **Step 3: Implement diagnostic summary builder**

```python
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
```

- [x] **Step 4: Run diagnostics tests**

```bash
python -m unittest tests.test_platform_windows_diagnostics -v
```

Expected: PASS.

- [x] **Step 5: Add worker.diagnostics sending helper**

Add this method to `WorkerWebSocketClient` in `rpa_platform/worker/websocket_client.py`:

```python
    def send_diagnostics(self, payload: Dict[str, Any]) -> None:
        self.transport.send_json(self._envelope("worker.diagnostics", payload))
```

- [x] **Step 6: Add --diagnose CLI branch**

Extend `rpa_platform/worker/websocket_worker.py`:

```python
import json
import os
import socket
from datetime import datetime

from rpa_platform.worker.diagnostics import build_diagnostic_summary
from rpa_platform.worker.machine_identity import load_or_create_machine_id
```

Then add the CLI option and branch:

First extend the `WorkerConfig` dataclass:

```python
@dataclass(frozen=True)
class WorkerConfig:
    ws_url: str
    machine_token: str
    robot_id: str
    db_path: str
    machine_config: str
    log_path: str
    artifact_dir: str
    capabilities: List[str]
```

Then return the new fields from `load_worker_config`:

```python
        log_path=values.get("RPA_LOG_PATH", "C:/rpa_group/logs/worker.log"),
        artifact_dir=values.get("RPA_ARTIFACT_DIR", "C:/rpa_group/artifacts"),
```

Add the CLI option:

```python
    parser.add_argument("--diagnose", action="store_true", help="Print a local redacted diagnostic summary and exit.")
```

Add the diagnostic branch after loading `config`:

```python
    if args.diagnose:
        machine_id = load_or_create_machine_id(Path(config.machine_config))
        summary = build_diagnostic_summary(
            machine_id=machine_id,
            robot_id=config.robot_id,
            task_id=None,
            mode="manual_debug",
            hostname=socket.gethostname(),
            session_name=os.environ.get("SESSIONNAME", "unknown"),
            interactive_desktop=bool(os.environ.get("SESSIONNAME")),
            screen_resolution="unknown",
            display_scaling="unknown",
            pid=os.getpid(),
            service_version="0.1.0",
            started_at=datetime.now().isoformat(),
            current_task_id=None,
            wss_connected=False,
            last_heartbeat_at=None,
            log_path=config.log_path,
            artifact_dir=config.artifact_dir,
            sqlite_path=config.db_path,
            recent_errors=[],
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
```

- [x] **Step 7: Run WebSocket and diagnostics tests**

```bash
python -m unittest tests.test_platform_websocket_worker tests.test_platform_windows_diagnostics -v
```

Expected: PASS.

- [x] **Step 8: Commit**

```bash
git add rpa_platform/worker/diagnostics.py rpa_platform/worker/websocket_client.py rpa_platform/worker/websocket_worker.py tests/test_platform_windows_diagnostics.py tests/test_platform_websocket_worker.py docs/rpa_platform_windows_websocket_protocol.md docs/rpa_platform_windows_websocket_runbook.md docs/superpowers/plans/2026-06-17-windows-websocket-worker.md
git commit -m "补充 Windows Worker 调试诊断能力"
```

## Task 6: Integration Verification and Documentation Sync

**Files:**
- Modify: `docs/rpa_platform_windows_websocket_protocol.md`
- Modify: `docs/rpa_platform_windows_websocket_runbook.md`
- Modify: any WebSocket implementation files changed in Tasks 1-4.

- [ ] **Step 1: Run focused tests**

```bash
python -m unittest \
  tests.test_platform_websocket_protocol \
  tests.test_platform_machine_identity \
  tests.test_platform_websocket_worker \
  tests.test_platform_windows_diagnostics \
  tests.test_platform_worker_scheduler \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run existing dry-run smoke**

```bash
python scripts/dev/run_platform_dryrun.py --prepare-only
python scripts/dev/run_platform_worker_once.py
```

Expected:

- Output contains `scheduler_result`.
- Output contains `runner_result`.
- Output does not contain Cookie, Token, EncodingAESKey, kitsecret, or raw secret values.

- [ ] **Step 3: Check protected files before staging**

```bash
git status -sb
```

Expected:

- Existing local test changes in `scripts/dev/run_wecom_bind_real_write.py` and `tests/test_platform_wecom_bind_real_write.py` are still visible unless the owner explicitly resolved them.
- Existing untracked handoff drafts under `docs/superpowers/handoff/` are not deleted.
- No `.env`, `config.py`, logs, DB files, screenshots, zip files, or `.local/` files are staged.

- [ ] **Step 4: Commit documentation sync**

```bash
git add docs/rpa_platform_windows_websocket_protocol.md docs/rpa_platform_windows_websocket_runbook.md docs/superpowers/plans/2026-06-17-windows-websocket-worker.md
git commit -m "补充 Windows WebSocket Worker 协议与部署计划"
```

## Follow-Up Task Group: WeCom Client Create Group RPA

This is a separate capability family after the base WebSocket worker is working. Do not implement it inside `WecomBindServiceRunner`.

### Task 7: WeCom Client Command Model

**Files:**
- Create: `rpa_platform/worker/client_commands.py`
- Create: `tests/test_platform_client_commands.py`
- Modify: `docs/rpa_platform_windows_websocket_protocol.md`

- [ ] **Step 1: Write command model tests**

```python
import unittest

from rpa_platform.worker.client_commands import normalize_client_command


class ClientCommandTest(unittest.TestCase):
    def test_normalizes_uia_click_command_with_image_fallback(self):
        command = normalize_client_command(
            {
                "step_key": "open_create_group",
                "step_name": "打开发起群聊入口",
                "action": "click_element",
                "target": {
                    "type": "uia",
                    "window_title": "企业微信",
                    "control_type": "Button",
                    "name": "发起群聊",
                },
                "fallback": {
                    "type": "image",
                    "image_key": "wecom_create_group_button",
                },
            }
        )

        self.assertEqual(command["action"], "click_element")
        self.assertEqual(command["target"]["type"], "uia")
        self.assertEqual(command["fallback"]["type"], "image")

    def test_rejects_position_click_without_high_risk_marker(self):
        with self.assertRaises(ValueError):
            normalize_client_command(
                {
                    "step_key": "unsafe_click",
                    "step_name": "坐标点击",
                    "action": "fallback_position_click",
                    "target": {"type": "position", "x": 100, "y": 200},
                }
            )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_platform_client_commands -v
```

Expected: FAIL because `client_commands.py` does not exist.

- [ ] **Step 3: Implement command normalization**

```python
from typing import Any, Dict


SUPPORTED_ACTIONS = {
    "activate_app",
    "find_element",
    "click_element",
    "set_text",
    "clipboard_paste",
    "send_hotkey",
    "wait_until",
    "assert_element",
    "capture_artifact",
    "fallback_image_click",
    "fallback_position_click",
}


def normalize_client_command(raw: Dict[str, Any]) -> Dict[str, Any]:
    command = dict(raw)
    action = command.get("action", "")
    if action not in SUPPORTED_ACTIONS:
        raise ValueError("Unsupported client command action: %s" % action)
    if action == "fallback_position_click" and command.get("risk_level") != "high":
        raise ValueError("Position click fallback must be marked risk_level=high")
    if not command.get("step_key"):
        raise ValueError("Client command step_key is required")
    if not command.get("step_name"):
        raise ValueError("Client command step_name is required")
    if action in ("click_element", "find_element", "set_text", "assert_element"):
        target = command.get("target") or {}
        if target.get("type") != "uia":
            raise ValueError("%s requires a UIA target" % action)
    return command
```

- [ ] **Step 4: Run command model tests**

```bash
python -m unittest tests.test_platform_client_commands -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rpa_platform/worker/client_commands.py tests/test_platform_client_commands.py docs/rpa_platform_windows_websocket_protocol.md
git commit -m "定义企微客户端 RPA 元素化命令模型"
```

### Task 8: UIA Driver and Element Picker Skeleton

**Files:**
- Create: `rpa_platform/worker/uia_driver.py`
- Create: `rpa_platform/worker/element_picker.py`
- Create: `tests/test_platform_element_picker.py`
- Modify: `docs/rpa_platform_windows_websocket_runbook.md`

- [ ] **Step 1: Write fake UIA picker tests**

```python
import unittest

from rpa_platform.worker.element_picker import build_selector_from_element


class ElementPickerTest(unittest.TestCase):
    def test_builds_selector_from_uia_element_metadata(self):
        selector = build_selector_from_element(
            {
                "name": "发起群聊",
                "automation_id": "",
                "class_name": "Button",
                "control_type": "Button",
                "window_title": "企业微信",
                "bounding_rect": [100, 200, 180, 240],
            }
        )

        self.assertEqual(selector["type"], "uia")
        self.assertEqual(selector["name"], "发起群聊")
        self.assertEqual(selector["control_type"], "Button")
        self.assertEqual(selector["window_title"], "企业微信")
        self.assertNotIn("screenshot", selector)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_platform_element_picker -v
```

Expected: FAIL because `element_picker.py` does not exist.

- [ ] **Step 3: Implement selector builder**

```python
from typing import Any, Dict


def build_selector_from_element(element: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "uia",
        "window_title": str(element.get("window_title", "")),
        "control_type": str(element.get("control_type", "")),
        "name": str(element.get("name", "")),
        "class_name": str(element.get("class_name", "")),
        "automation_id": str(element.get("automation_id", "")),
        "bounding_rect_hint": element.get("bounding_rect"),
    }
```

- [ ] **Step 4: Add UIA driver interface skeleton**

```python
from typing import Any, Dict, Optional, Protocol


class UiaDriver(Protocol):
    def find_element(self, selector: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def click_element(self, selector: Dict[str, Any]) -> None:
        raise NotImplementedError

    def set_text(self, selector: Dict[str, Any], value: str) -> None:
        raise NotImplementedError
```

- [ ] **Step 5: Run picker tests**

```bash
python -m unittest tests.test_platform_element_picker -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add rpa_platform/worker/uia_driver.py rpa_platform/worker/element_picker.py tests/test_platform_element_picker.py docs/rpa_platform_windows_websocket_runbook.md
git commit -m "新增企微客户端元素拾取器骨架"
```

### Task 9: WeCom Create Group Runner Skeleton

**Files:**
- Create: `rpa_platform/worker/wecom_client_runner.py`
- Create: `tests/test_platform_wecom_client_runner.py`
- Modify: `docs/rpa_platform_windows_websocket_protocol.md`

- [ ] **Step 1: Write runner test with fake UIA driver**

```python
import unittest

from rpa_platform.worker.wecom_client_runner import WecomCreateGroupRunner


class FakeUiaDriver:
    def __init__(self):
        self.calls = []

    def find_element(self, selector):
        self.calls.append(("find", selector))
        return {"name": selector.get("name", ""), "control_type": selector.get("control_type", "")}

    def click_element(self, selector):
        self.calls.append(("click", selector))

    def set_text(self, selector, value):
        self.calls.append(("set_text", selector, value))


class WecomCreateGroupRunnerTest(unittest.TestCase):
    def test_executes_create_group_template_commands(self):
        driver = FakeUiaDriver()
        runner = WecomCreateGroupRunner(uia_driver=driver)

        result = runner.run_template(
            task_id="task-001",
            payload={
                "customer_name": "zh_test_上海测试客户",
                "group_name": "zh_test_上海测试客户_服务群",
                "member_names": ["李四"],
                "test_mode": True,
            },
            commands=[
                {
                    "step_key": "open_create_group",
                    "step_name": "打开发起群聊入口",
                    "action": "click_element",
                    "target": {"type": "uia", "window_title": "企业微信", "control_type": "Button", "name": "发起群聊"},
                },
                {
                    "step_key": "set_group_name",
                    "step_name": "设置群名称",
                    "action": "set_text",
                    "target": {"type": "uia", "window_title": "企业微信", "control_type": "Edit", "name": "群名称"},
                    "value_from": "group_name",
                },
            ],
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(driver.calls[0][0], "click")
        self.assertEqual(driver.calls[1][0], "set_text")
        self.assertEqual(driver.calls[1][2], "zh_test_上海测试客户_服务群")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest tests.test_platform_wecom_client_runner -v
```

Expected: FAIL because `wecom_client_runner.py` does not exist.

- [ ] **Step 3: Implement runner skeleton**

```python
from typing import Any, Dict, List


class WecomCreateGroupRunner:
    def __init__(self, uia_driver: Any):
        self.uia_driver = uia_driver

    def run_template(
        self,
        task_id: str,
        payload: Dict[str, Any],
        commands: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        for command in commands:
            action = command["action"]
            target = command.get("target", {})
            if action == "click_element":
                self.uia_driver.click_element(target)
            elif action == "set_text":
                value = payload[command["value_from"]]
                self.uia_driver.set_text(target, value)
            else:
                raise ValueError("Unsupported create-group command: %s" % action)
        return {
            "task_id": task_id,
            "status": "success",
            "group_name": payload.get("group_name", ""),
        }
```

- [ ] **Step 4: Run runner tests**

```bash
python -m unittest tests.test_platform_wecom_client_runner -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rpa_platform/worker/wecom_client_runner.py tests/test_platform_wecom_client_runner.py docs/rpa_platform_windows_websocket_protocol.md
git commit -m "新增企微客户端自动建群 Runner 骨架"
```

## Self-Review

- Spec coverage:
  - jdycsm control plane and Windows execution plane are separated in protocol and runbook.
  - `machine_id` is stable and local-file backed.
  - `idempotency_key` is mandatory in dispatch.
  - heartbeat, register, dispatch, progress, result, and error are included.
  - `waiting_login` uses jdycsm-owned manual action notification; QR images are not uploaded by default.
  - Windows diagnostic mode covers session, display, local paths, recent errors, and redaction.
  - WeCom client create-group is separated as `wecom_client_rpa_create_group`.
  - Business-facing configuration and admin-only selector maintenance are separated.
  - Element picker uses hover plus hotkey capture before any exe packaging.
  - reconnect/reconcile behavior is documented.
  - Sensitive data stays local by default.
- Placeholder scan:
  - No placeholder or open-ended steps remain.
- Type consistency:
  - Message fields use `machine_id`, `robot_id`, `message_id`, `task_id`, and `idempotency_key` consistently.
  - CLI command in runbook matches planned module path.
