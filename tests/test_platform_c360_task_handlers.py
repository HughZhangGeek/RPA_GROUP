import unittest

from rpa_platform.worker.c360_worker_client import load_c360_worker_config_from_env
from rpa_platform.worker.c360_worker_runtime import WorkerTaskResult
from rpa_platform.worker.simulated_handlers import SimulatedTaskHandlers


class FakeWecomHandler:
    def __init__(self):
        self.calls = []

    async def handle(self, dispatch):
        self.calls.append(dispatch)
        return WorkerTaskResult(status="ready_for_real_bind", result={"status": "ready_for_real_bind"})


class C360TaskHandlersTest(unittest.IsolatedAsyncioTestCase):
    def _config(self, simulate):
        return load_c360_worker_config_from_env(
            {
                "C360_BASE_URL": "http://127.0.0.1:3601",
                "RPA_WORKER_TOKEN": "secret-token",
                "RPA_WORKER_ID": "win-server-001",
                "RPA_WORKER_SIMULATE": "true" if simulate else "false",
            }
        )

    async def test_simulate_true_keeps_existing_simulated_wecom_handler(self):
        from rpa_platform.worker.c360_task_handlers import build_c360_task_handlers

        handlers = build_c360_task_handlers(self._config(simulate=True), diagnostics={})

        self.assertIsInstance(handlers, SimulatedTaskHandlers)
        result = await handlers.handle(
            {
                "task_type": "wecom_bind_service",
                "payload": {"task_type": "wecom_bind_service", "enterprise_name": "zh_test_上海测试客户"},
            }
        )
        self.assertEqual(result, {"simulated": True, "handler": "wecom_bind_service"})

    async def test_simulate_false_routes_wecom_bind_service_to_real_handler(self):
        from rpa_platform.worker.c360_task_handlers import C360TaskHandlers

        fake_wecom = FakeWecomHandler()
        handlers = C360TaskHandlers(diagnostics={}, wecom_bind_handler=fake_wecom)

        result = await handlers.handle(
            {
                "task_type": "wecom_bind_service",
                "payload": {"task_type": "wecom_bind_service", "enterprise_name": "zh_test_上海测试客户"},
            }
        )

        self.assertEqual(result.status, "ready_for_real_bind")
        self.assertEqual(fake_wecom.calls[0]["payload"]["enterprise_name"], "zh_test_上海测试客户")

    async def test_simulate_false_keeps_diagnostics_safe(self):
        from rpa_platform.worker.c360_task_handlers import C360TaskHandlers

        handlers = C360TaskHandlers(
            diagnostics={"machine_id": "win-server-001", "recent_error": "token: secret-value"},
            wecom_bind_handler=FakeWecomHandler(),
        )

        result = await handlers.handle({"task_type": "diagnostics", "payload": {}})

        self.assertEqual(result["machine_id"], "win-server-001")
        self.assertNotIn("secret-value", str(result))


if __name__ == "__main__":
    unittest.main()
