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
