import unittest

from rpa_platform.worker.c360_worker_client import load_c360_worker_config_from_env
from rpa_platform.worker.c360_worker_runtime import AioHttpJsonTransport, C360WorkerRuntime
from rpa_platform.worker.simulated_handlers import SimulatedTaskHandlers


class FakeTransport:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_json(self):
        if not self.incoming:
            return None
        return self.incoming.pop(0)


class C360WorkerRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def _config(self):
        return load_c360_worker_config_from_env(
            {
                "C360_BASE_URL": "http://127.0.0.1:3601",
                "RPA_WORKER_TOKEN": "secret-token",
                "RPA_WORKER_ID": "win-sim-001",
                "RPA_WORKER_SIMULATE": "true",
            }
        )

    async def test_connect_sends_hello_then_completes_supported_dispatch(self):
        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-sim-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-001",
                    "task_type": "wecom_bind_service",
                    "route_key": "wecom_bind_service",
                    "idempotency_key": "idem-001",
                    "simulate": True,
                    "payload": {
                        "task_type": "wecom_bind_service",
                        "enterprise_name": "zh_test_模拟客户",
                        "plain_corp_id": "ww_test",
                    },
                },
            ]
        )
        runtime = C360WorkerRuntime(
            config=self._config(),
            transport=transport,
            handlers=SimulatedTaskHandlers(
                diagnostics={
                    "machine_id": "win-sim-001",
                    "interactive_desktop": True,
                    "session_name": "console",
                    "resolution": "1920x1080",
                    "dpi_scale": "100%",
                }
            ),
        )

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[0]["type"], "worker.hello")
        self.assertEqual([item["type"] for item in transport.sent[1:]], ["task.accepted", "task.progress", "task.completed"])
        self.assertEqual(transport.sent[1]["task_id"], "task-001")
        self.assertEqual(transport.sent[2]["status"], "running")
        self.assertEqual(transport.sent[3]["status"], "succeeded")
        self.assertEqual(transport.sent[3]["result"], {"simulated": True, "handler": "wecom_bind_service"})

    async def test_unknown_task_type_fails_without_crashing(self):
        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-sim-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-unknown",
                    "task_type": "unsupported",
                    "route_key": "unsupported",
                    "simulate": True,
                    "payload": {},
                },
            ]
        )
        runtime = C360WorkerRuntime(config=self._config(), transport=transport, handlers=SimulatedTaskHandlers({}))

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[-1]["type"], "task.completed")
        self.assertEqual(transport.sent[-1]["status"], "failed")
        self.assertIn("Unsupported task_type", transport.sent[-1]["error_message"])
        self.assertNotIn("secret-token", str(transport.sent))

    async def test_handler_exception_is_reported_as_failed_with_redacted_message(self):
        class ExplodingHandlers(SimulatedTaskHandlers):
            async def handle(self, dispatch):
                raise RuntimeError("Authorization: Bearer secret-value")

        transport = FakeTransport(
            [
                {"type": "worker.accepted", "worker_id": "win-sim-001"},
                {
                    "type": "task.dispatch",
                    "task_id": "task-failed",
                    "task_type": "runtime_health_check",
                    "route_key": "runtime_health_check",
                    "simulate": True,
                    "payload": {},
                },
            ]
        )
        runtime = C360WorkerRuntime(config=self._config(), transport=transport, handlers=ExplodingHandlers({}))

        await runtime.run_until_idle()

        self.assertEqual(transport.sent[-1]["status"], "failed")
        self.assertIn("Bearer [REDACTED]", transport.sent[-1]["error_message"])
        self.assertNotIn("secret-value", str(transport.sent))


class SimulatedTaskHandlersTest(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_health_check_returns_simulated_ok(self):
        result = await SimulatedTaskHandlers({}).handle({"task_type": "runtime_health_check", "payload": {}})

        self.assertEqual(result["ok"], True)
        self.assertEqual(result["simulated"], True)

    async def test_diagnostics_returns_redacted_summary(self):
        result = await SimulatedTaskHandlers(
            {
                "machine_id": "win-sim-001",
                "session_name": "console",
                "recent_error": "token: secret-value",
            }
        ).handle({"task_type": "diagnostics", "payload": {}})

        self.assertEqual(result["machine_id"], "win-sim-001")
        self.assertNotIn("secret-value", str(result))

    async def test_wecom_bind_service_returns_fixed_simulated_result(self):
        result = await SimulatedTaskHandlers({}).handle(
            {
                "task_type": "wecom_bind_service",
                "payload": {"enterprise_name": "zh_test_模拟客户", "plain_corp_id": "ww_test"},
            }
        )

        self.assertEqual(result, {"simulated": True, "handler": "wecom_bind_service"})


class AioHttpJsonTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_sends_and_receives_json_with_aiohttp_websocket(self):
        class Message:
            def __init__(self, data):
                self.data = data

        class FakeWebSocket:
            def __init__(self):
                self.sent = []

            async def send_str(self, data):
                self.sent.append(data)

            async def receive(self):
                return Message('{"type": "worker.accepted", "worker_id": "win-sim-001"}')

        websocket = FakeWebSocket()
        transport = AioHttpJsonTransport(websocket, session=None)

        await transport.send_json({"type": "worker.hello", "worker_id": "win-sim-001"})
        received = await transport.receive_json()

        self.assertIn('"worker.hello"', websocket.sent[0])
        self.assertEqual(received["type"], "worker.accepted")


if __name__ == "__main__":
    unittest.main()
