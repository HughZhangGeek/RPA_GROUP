import unittest

from rpa_platform.worker.c360_worker_runtime import WorkerTaskResult
from rpa_platform.worker.wecom_bind_recovery_handler import WecomBindRecoveryTaskHandler


class FakeRecovery:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, task_id, context):
        self.calls.append({"task_id": task_id, "context": context})
        return dict(self.result)


class WecomBindRecoveryTaskHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_login_result_becomes_manual_action_required_progress(self):
        recovery = FakeRecovery(
            {
                "status": "waiting_login",
                "reason": "wecom_login_not_restored",
                "expires_at": 1000.0,
            }
        )
        handler = WecomBindRecoveryTaskHandler(recovery)

        result = await handler.handle(
            {
                "task_id": "task-001",
                "task_type": "wecom_bind_service",
                "payload": {
                    "task_type": "wecom_bind_service",
                    "enterprise_name": "上海测试客户",
                    "plain_corp_id": "corp-id-placeholder",
                },
            }
        )

        self.assertIsInstance(result, WorkerTaskResult)
        self.assertEqual(result.status, "manual_action_required")
        self.assertEqual(result.result["manual_action"], "scan_wecom_admin_qr")
        self.assertEqual(result.result["reason"], "wecom_login_not_restored")
        self.assertEqual(result.progress[0]["status"], "waiting_login")
        self.assertEqual(recovery.calls[0]["task_id"], "task-001")
        self.assertEqual(recovery.calls[0]["context"]["enterprise_name"], "上海测试客户")
        self.assertNotIn("corp-id-placeholder", str(result))

    async def test_ready_for_real_bind_remains_pending_manual_confirmation(self):
        recovery = FakeRecovery(
            {
                "status": "ready_for_real_bind",
                "reason": "ready_for_confirm_write",
                "preflight": {"status": "ok", "reason": "ready_for_confirm_write"},
            }
        )
        handler = WecomBindRecoveryTaskHandler(recovery)

        result = await handler.handle(
            {
                "task_id": "task-002",
                "route_key": "wecom_bind_service",
                "payload": {"enterprise_name": "上海测试客户", "plain_corp_id": "corp-id-placeholder"},
            }
        )

        self.assertEqual(result.status, "ready_for_real_bind")
        self.assertEqual(result.result["reason"], "ready_for_confirm_write")
        self.assertEqual(result.progress[0]["status"], "ready_for_real_bind")
        self.assertNotIn("corp-id-placeholder", str(result))

    async def test_unsupported_task_type_raises_value_error(self):
        handler = WecomBindRecoveryTaskHandler(FakeRecovery({}))

        with self.assertRaises(ValueError):
            await handler.handle({"task_id": "task-003", "task_type": "diagnostics", "payload": {}})


if __name__ == "__main__":
    unittest.main()
