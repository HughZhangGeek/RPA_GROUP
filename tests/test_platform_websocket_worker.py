import os
import tempfile
import unittest
from pathlib import Path

from rpa_platform.worker.websocket_client import WorkerWebSocketClient
from rpa_platform.worker.websocket_worker import load_worker_config


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

    def test_dispatch_handler_missing_result_sends_reject_ack(self):
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

        try:
            client.receive_once(lambda task: handled.append(task))
        except Exception as exc:
            self.fail("receive_once should send reject ack when handler returns None: %r" % exc)

        self.assertEqual(handled[0]["task_id"], "task-001")
        self.assertEqual(transport.sent[0]["type"], "task.ack")
        self.assertFalse(transport.sent[0]["payload"]["accepted"])
        self.assertIsNone(transport.sent[0]["payload"]["local_execution_id"])
        self.assertEqual(transport.sent[0]["payload"]["reject_reason"], "handler_result_missing")


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
