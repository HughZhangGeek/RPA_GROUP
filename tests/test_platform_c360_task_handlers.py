import unittest
import os
from unittest.mock import patch

from rpa_platform.worker.c360_worker_client import load_c360_worker_config_from_env
from rpa_platform.worker.c360_worker_runtime import WorkerTaskResult
from rpa_platform.worker.simulated_handlers import SimulatedTaskHandlers


class FakeWecomHandler:
    def __init__(self, status="ready_for_real_bind"):
        self.calls = []
        self.status = status

    async def handle(self, dispatch):
        self.calls.append(dispatch)
        return WorkerTaskResult(status=self.status, result={"status": self.status})


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

    def test_unattended_write_policy_requires_env_and_payload_gate(self):
        from rpa_platform.worker.c360_task_handlers import is_unattended_write_enabled

        self.assertFalse(is_unattended_write_enabled({}, {"unattended_write": True}))
        self.assertFalse(
            is_unattended_write_enabled(
                {"RPA_WORKER_ALLOW_UNATTENDED_WRITE": "true"},
                {"unattended_write": False, "confirm_write": False},
            )
        )
        self.assertTrue(
            is_unattended_write_enabled(
                {"RPA_WORKER_ALLOW_UNATTENDED_WRITE": "true"},
                {"unattended_write": True},
            )
        )
        self.assertTrue(
            is_unattended_write_enabled(
                {"RPA_WORKER_ALLOW_UNATTENDED_WRITE": "true"},
                {"confirm_write": True},
            )
        )

    async def test_unattended_write_routes_only_when_env_and_payload_are_enabled(self):
        from rpa_platform.worker.c360_task_handlers import C360TaskHandlers

        readonly = FakeWecomHandler(status="ready_for_real_bind")
        unattended = FakeWecomHandler(status="success")
        handlers = C360TaskHandlers(
            diagnostics={},
            wecom_bind_handler=readonly,
            wecom_bind_unattended_handler=unattended,
            env={"RPA_WORKER_ALLOW_UNATTENDED_WRITE": "true"},
        )

        readonly_result = await handlers.handle(
            {
                "task_type": "wecom_bind_service",
                "payload": {"task_type": "wecom_bind_service", "unattended_write": False},
            }
        )
        unattended_result = await handlers.handle(
            {
                "task_type": "wecom_bind_service",
                "payload": {"task_type": "wecom_bind_service", "unattended_write": True},
            }
        )

        self.assertEqual(readonly_result.status, "ready_for_real_bind")
        self.assertEqual(unattended_result.status, "success")
        self.assertEqual(len(readonly.calls), 1)
        self.assertEqual(len(unattended.calls), 1)

    async def test_build_handlers_wires_unattended_handler_from_env(self):
        from rpa_platform.worker.c360_task_handlers import build_c360_task_handlers

        readonly = FakeWecomHandler(status="ready_for_real_bind")
        unattended = FakeWecomHandler(status="success")

        with patch(
            "rpa_platform.worker.wecom_bind_real_recovery.build_wecom_bind_recovery_handler_from_env",
            return_value=readonly,
        ):
            with patch(
                "rpa_platform.worker.wecom_bind_real_recovery.build_wecom_bind_unattended_write_handler_from_env",
                return_value=unattended,
            ):
                handlers = build_c360_task_handlers(
                    self._config(simulate=False),
                    diagnostics={},
                    env={"RPA_WORKER_ALLOW_UNATTENDED_WRITE": "true"},
                )

        result = await handlers.handle(
            {
                "task_type": "wecom_bind_service",
                "payload": {"task_type": "wecom_bind_service", "confirm_write": True},
            }
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(unattended.calls), 1)

    async def test_build_handlers_reads_unattended_gate_from_process_env_when_env_not_injected(self):
        from rpa_platform.worker.c360_task_handlers import build_c360_task_handlers

        readonly = FakeWecomHandler(status="ready_for_real_bind")
        unattended = FakeWecomHandler(status="success")

        with patch.dict(os.environ, {"RPA_WORKER_ALLOW_UNATTENDED_WRITE": "true"}):
            with patch(
                "rpa_platform.worker.wecom_bind_real_recovery.build_wecom_bind_recovery_handler_from_env",
                return_value=readonly,
            ):
                with patch(
                    "rpa_platform.worker.wecom_bind_real_recovery.build_wecom_bind_unattended_write_handler_from_env",
                    return_value=unattended,
                ):
                    handlers = build_c360_task_handlers(self._config(simulate=False), diagnostics={})

        result = await handlers.handle(
            {
                "task_type": "wecom_bind_service",
                "payload": {"task_type": "wecom_bind_service", "unattended_write": True},
            }
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(unattended.calls), 1)


if __name__ == "__main__":
    unittest.main()
