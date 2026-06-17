import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from rpa_platform.worker.websocket_client import WorkerWebSocketClient
from rpa_platform.worker.websocket_worker import load_worker_config, main


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

    def test_sends_diagnostics_envelope(self):
        transport = FakeTransport(incoming=[])
        client = WorkerWebSocketClient(
            transport=transport,
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            hostname="WIN-RPA-01",
            service_version="0.1.0",
            capabilities={"wecom_bind_service": True},
        )

        client.send_diagnostics({"diagnostic_id": "diag-001", "mode": "manual_debug"})

        self.assertEqual(transport.sent[0]["type"], "worker.diagnostics")
        self.assertEqual(transport.sent[0]["payload"]["diagnostic_id"], "diag-001")

    def test_rejects_diagnostics_payload_with_sensitive_headers(self):
        transport = FakeTransport(incoming=[])
        client = WorkerWebSocketClient(
            transport=transport,
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            hostname="WIN-RPA-01",
            service_version="0.1.0",
            capabilities={"wecom_bind_service": True},
        )

        with self.assertRaises(ValueError):
            client.send_diagnostics({"headers": {"Authorization": "Bearer secret-value"}})

        self.assertEqual(transport.sent, [])

    def test_redacts_diagnostics_payload_secret_patterns_before_sending(self):
        transport = FakeTransport(incoming=[])
        client = WorkerWebSocketClient(
            transport=transport,
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            hostname="WIN-RPA-01",
            service_version="0.1.0",
            capabilities={"wecom_bind_service": True},
        )

        client.send_diagnostics(
            {
                "diagnostic_id": "diag-001",
                "recent_errors": [{"message": "Authorization: Bearer secret-value"}],
            }
        )

        rendered = str(transport.sent[0])
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("Bearer secret-value", rendered)

    def test_rejects_sensitive_headers_for_task_outbound_messages(self):
        for method_name in ("send_progress", "send_result", "send_error"):
            with self.subTest(method_name=method_name):
                transport = FakeTransport(incoming=[])
                client = WorkerWebSocketClient(
                    transport=transport,
                    machine_id="mch-001",
                    robot_id="windows-rpa-01",
                    hostname="WIN-RPA-01",
                    service_version="0.1.0",
                    capabilities={"wecom_bind_service": True},
                )

                with self.assertRaises(ValueError):
                    getattr(client, method_name)({"headers": {"Authorization": "Bearer secret-value"}})

                self.assertEqual(transport.sent, [])


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
            self.assertEqual(config.log_path, "C:/rpa_group/logs/worker.log")
            self.assertEqual(config.artifact_dir, "C:/rpa_group/artifacts")

    def test_diagnose_prints_redacted_local_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "worker.env"
            machine_config = Path(tmpdir) / "machine.json"
            env_path.write_text(
                "\n".join(
                    [
                        "RPA_WS_URL=wss://jdycsm.example.com/rpa/ws/worker",
                        "RPA_MACHINE_TOKEN=secret-token",
                        "RPA_ROBOT_ID=windows-rpa-01",
                        "RPA_DB_PATH=C:/rpa_group/data/platform-worker.db",
                        "RPA_MACHINE_CONFIG=%s" % machine_config,
                        "RPA_LOG_PATH=C:/rpa_group/logs/worker.log",
                        "RPA_ARTIFACT_DIR=C:/rpa_group/artifacts",
                    ]
                ),
                encoding="utf-8",
            )
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(["--env", str(env_path), "--diagnose"])

            self.assertEqual(exit_code, 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["robot_id"], "windows-rpa-01")
            self.assertEqual(summary["mode"], "manual_debug")
            self.assertFalse(summary["network"]["wss_connected"])
            self.assertEqual(summary["local_refs"]["log_path_hint"], "C:/rpa_group/logs/worker.log")
            self.assertNotIn("secret-token", output.getvalue())
            self.assertNotIn("cookie", output.getvalue().lower())
