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
    def test_real_recovery_uses_default_userid_from_downstream_resolution(self):
        from rpa_platform.worker.wecom_bind_real_recovery import RealWecomBindRecovery

        class RecordingRecovery:
            def __init__(self):
                self.calls = []

            def run(self, task_id, context):
                self.calls.append({"task_id": task_id, "context": dict(context)})
                context["requested_user_id"] = "deploy-default-userid"
                context["userid"] = "deploy-default-userid"
                return {
                    "status": "ready_for_real_bind",
                    "reason": "ready_for_confirm_write",
                    "jdy": {
                        "requested_user_id": "deploy-default-userid",
                        "bound_user_id": "deploy-default-userid",
                    },
                }

        recovery = RecordingRecovery()
        real_recovery = RealWecomBindRecovery(orchestrator_factory=lambda context: recovery)

        result = real_recovery.run(
            task_id="task-default-userid",
            context={
                "enterprise_name": "上海测试客户",
                "corp_id": "ww001",
                "userid": "",
            },
        )

        self.assertEqual(result["status"], "ready_for_real_bind")
        self.assertEqual(result["userid_source"], "default")
        self.assertEqual(recovery.calls[0]["context"]["userid_source"], "default")
        self.assertEqual(result["jdy"]["requested_user_id"], "deploy-default-userid")
        self.assertEqual(result["jdy"]["bound_user_id"], "deploy-default-userid")

    def test_real_recovery_allows_missing_userid_to_continue_to_jdy_default(self):
        from rpa_platform.worker.wecom_bind_real_recovery import RealWecomBindRecovery

        class RecordingRecovery:
            def __init__(self):
                self.calls = []

            def run(self, task_id, context):
                self.calls.append({"task_id": task_id, "context": dict(context)})
                return {"status": "ready_for_real_bind", "reason": "ready_for_confirm_write"}

        recovery = RecordingRecovery()
        real_recovery = RealWecomBindRecovery(orchestrator_factory=lambda context: recovery)
        result = real_recovery.run(
            task_id="task-missing-userid",
            context={"enterprise_name": "上海测试客户", "corp_id": "ww001"},
        )

        self.assertEqual(result["status"], "ready_for_real_bind")
        self.assertEqual(result["userid_source"], "default")
        self.assertEqual(recovery.calls[0]["context"]["userid_source"], "default")

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
        self.assertEqual(
            result.result["queue_control"],
            {
                "action": "pause",
                "scope": "wecom_bind_service",
                "resume_when": "wecom_login_restored",
            },
        )
        self.assertEqual(result.progress[0]["status"], "readonly_preflight_started")
        self.assertEqual(result.progress[-1]["status"], "waiting_login")
        self.assertEqual(result.progress[-1]["queue_control"]["action"], "pause")
        self.assertEqual(recovery.calls[0]["task_id"], "task-001")
        self.assertEqual(recovery.calls[0]["context"]["enterprise_name"], "上海测试客户")
        self.assertNotIn("corp-id-placeholder", str(result))

    async def test_notify_exhausted_result_requires_manual_escalation_and_keeps_queue_paused(self):
        recovery = FakeRecovery(
            {
                "status": "login_recovery_notify_exhausted",
                "reason": "wecom_login_not_restored",
                "manual_action": "manual_escalation_required",
                "notify_attempts": 3,
                "remaining_notify_attempts": 0,
            }
        )
        handler = WecomBindRecoveryTaskHandler(recovery)

        result = await handler.handle(
            {
                "task_id": "task-exhausted",
                "task_type": "wecom_bind_service",
                "payload": {"task_type": "wecom_bind_service", "enterprise_name": "上海测试客户"},
            }
        )

        self.assertEqual(result.status, "manual_action_required")
        self.assertEqual(result.result["status"], "login_recovery_notify_exhausted")
        self.assertEqual(result.result["manual_action"], "manual_escalation_required")
        self.assertEqual(result.result["queue_control"]["action"], "pause")
        self.assertEqual(result.progress[0]["status"], "readonly_preflight_started")
        self.assertEqual(result.progress[-1]["status"], "login_recovery_notify_exhausted")
        self.assertEqual(result.progress[-1]["queue_control"]["scope"], "wecom_bind_service")

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
        self.assertEqual(
            result.result["queue_control"],
            {
                "action": "resume",
                "scope": "wecom_bind_service",
                "resume_reason": "wecom_login_restored",
            },
        )
        self.assertEqual(result.progress[0]["status"], "readonly_preflight_started")
        self.assertEqual(result.progress[-1]["status"], "readonly_preflight_completed")
        self.assertEqual(result.progress[-1]["queue_control"]["action"], "resume")
        self.assertNotIn("corp-id-placeholder", str(result))

    async def test_ready_for_real_bind_reports_preflight_step_progress(self):
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
                "task_id": "task-progress",
                "task_type": "wecom_bind_service",
                "payload": {"enterprise_name": "上海测试客户", "plain_corp_id": "corp-id-placeholder"},
            }
        )

        self.assertEqual(
            [item["status"] for item in result.progress],
            [
                "readonly_preflight_started",
                "readonly_preflight_completed",
            ],
        )
        self.assertEqual(result.progress[-1]["queue_control"]["action"], "resume")

    async def test_waiting_login_reports_preflight_and_queue_pause_steps(self):
        recovery = FakeRecovery(
            {
                "status": "waiting_login",
                "reason": "wecom_login_not_restored",
                "expires_at": 1000.0,
                "notify_attempts": 1,
                "remaining_notify_attempts": 2,
                "next_action": "retry_wecom_login_qr",
            }
        )
        handler = WecomBindRecoveryTaskHandler(recovery)

        result = await handler.handle(
            {
                "task_id": "task-waiting",
                "task_type": "wecom_bind_service",
                "payload": {"enterprise_name": "上海测试客户", "plain_corp_id": "corp-id-placeholder"},
            }
        )

        self.assertEqual(
            [item["status"] for item in result.progress],
            [
                "readonly_preflight_started",
                "waiting_login",
            ],
        )
        self.assertEqual(result.progress[-1]["queue_control"]["action"], "pause")
        self.assertEqual(result.progress[-1]["next_action"], "retry_wecom_login_qr")

    async def test_unsupported_task_type_raises_value_error(self):
        handler = WecomBindRecoveryTaskHandler(FakeRecovery({}))

        with self.assertRaises(ValueError):
            await handler.handle({"task_id": "task-003", "task_type": "diagnostics", "payload": {}})

    async def test_unattended_write_success_reports_write_progress_and_succeeded_result(self):
        recovery = FakeRecovery(
            {
                "mode": "unattended_write",
                "status": "success",
                "preflight": {"status": "ok", "reason": "ready_for_confirm_write"},
                "wecom": {"auditorderid": "au202606200001", "auditorder_status": 5},
                "submit_result": {
                    "status": "success",
                    "context": {
                        "wecom": {
                            "auditorder_status": 5,
                            "token": "token-secret",
                            "encoding_aes_key": "aes-secret",
                        }
                    },
                },
            }
        )
        handler = WecomBindRecoveryTaskHandler(recovery)

        result = await handler.handle(
            {
                "task_id": "task-unattended-success",
                "task_type": "wecom_bind_service",
                "payload": {"enterprise_name": "上海测试客户", "plain_corp_id": "corp-id-placeholder"},
            }
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            [item["status"] for item in result.progress],
            [
                "readonly_preflight_started",
                "readonly_preflight_completed",
                "real_write_started",
                "real_write_completed",
            ],
        )
        self.assertEqual(result.result["status"], "success")
        self.assertEqual(result.result["wecom"]["auditorderid"], "au202606200001")
        self.assertEqual(result.result["wecom"]["auditorder_status"], 5)
        self.assertNotIn("token-secret", str(result))
        self.assertNotIn("aes-secret", str(result))
        self.assertNotIn("corp-id-placeholder", str(result))

    async def test_unattended_write_failure_reports_write_failed_and_failed_status(self):
        recovery = FakeRecovery(
            {
                "mode": "unattended_write",
                "status": "failed",
                "reason": "real_write_failed",
                "detail": "WeCom admin API error",
            }
        )
        handler = WecomBindRecoveryTaskHandler(recovery)

        result = await handler.handle(
            {
                "task_id": "task-unattended-failed",
                "task_type": "wecom_bind_service",
                "payload": {"enterprise_name": "上海测试客户", "plain_corp_id": "corp-id-placeholder"},
            }
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(
            [item["status"] for item in result.progress],
            [
                "readonly_preflight_started",
                "readonly_preflight_completed",
                "real_write_started",
                "real_write_failed",
            ],
        )
        self.assertEqual(result.result["status"], "failed")
        self.assertEqual(result.result["reason"], "real_write_failed")
        self.assertNotIn("corp-id-placeholder", str(result))

    async def test_unattended_write_waiting_login_requires_manual_action_without_write_progress(self):
        recovery = FakeRecovery(
            {
                "mode": "unattended_write",
                "status": "waiting_login",
                "reason": "wecom_login_not_restored",
                "expires_at": 1000.0,
                "notify_attempts": 1,
                "remaining_notify_attempts": 2,
            }
        )
        handler = WecomBindRecoveryTaskHandler(recovery)

        result = await handler.handle(
            {
                "task_id": "task-unattended-waiting-login",
                "task_type": "wecom_bind_service",
                "payload": {"enterprise_name": "上海测试客户", "plain_corp_id": "corp-id-placeholder"},
            }
        )

        self.assertEqual(result.status, "manual_action_required")
        self.assertEqual(
            [item["status"] for item in result.progress],
            [
                "readonly_preflight_started",
                "waiting_login",
            ],
        )
        self.assertEqual(result.result["queue_control"]["action"], "pause")
        self.assertNotIn("real_write_started", str(result.progress))

    async def test_unattended_write_business_unexecutable_does_not_report_real_write_failure(self):
        recovery = FakeRecovery(
            {
                "mode": "unattended_write",
                "status": "business_unexecutable",
                "reason": "jdy_corp_not_unique_or_missing",
            }
        )
        handler = WecomBindRecoveryTaskHandler(recovery)

        result = await handler.handle(
            {
                "task_id": "task-unattended-business-unexecutable",
                "task_type": "wecom_bind_service",
                "payload": {"enterprise_name": "上海测试客户"},
            }
        )

        self.assertEqual(result.status, "business_unexecutable")
        self.assertEqual(
            [item["status"] for item in result.progress],
            [
                "readonly_preflight_started",
                "readonly_preflight_completed",
            ],
        )
        self.assertEqual(result.result["status"], "business_unexecutable")
        self.assertEqual(result.result["reason"], "jdy_corp_not_unique_or_missing")
        self.assertNotIn("real_write_started", str(result.progress))
        self.assertNotIn("real_write_failed", str(result.progress))


if __name__ == "__main__":
    unittest.main()
