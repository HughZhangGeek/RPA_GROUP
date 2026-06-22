import unittest


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    def run(self, task_id, context):
        self.calls.append({"task_id": task_id, "context": context})
        return {"status": "ready_for_real_bind", "reason": "ready_for_confirm_write"}


class WecomBindRealRecoveryTest(unittest.TestCase):
    def test_build_bind_input_from_flat_payload(self):
        from rpa_platform.worker.wecom_bind_real_recovery import build_bind_input_from_context

        bind_input = build_bind_input_from_context(
            {
                "enterprise_name": "zh_test_上海测试客户",
                "enterprise_short_name": "上海测试",
                "plain_corp_id": "ww_test_corp",
                "requested_user_id": "zh_test_user",
                "suite_id": "1",
                "suite_scenario": "main",
                "wecom_suiteid": "1009479",
                "suite_name": "简道云",
            }
        )

        self.assertEqual(bind_input.enterprise_name, "zh_test_上海测试客户")
        self.assertEqual(bind_input.enterprise_short_name, "上海测试")
        self.assertEqual(bind_input.plain_corp_id, "ww_test_corp")
        self.assertEqual(bind_input.requested_user_id, "zh_test_user")
        self.assertEqual(bind_input.wecom_suiteid, 1009479)

    def test_missing_required_context_returns_blocked_without_write(self):
        from rpa_platform.worker.wecom_bind_real_recovery import RealWecomBindRecovery

        recovery = RealWecomBindRecovery(orchestrator_factory=lambda _context: FakeOrchestrator())

        result = recovery.run(task_id="task-missing", context={"enterprise_name": "zh_test_上海测试客户"})

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "missing_required_bind_context")
        self.assertIn("plain_corp_id", result["missing_fields"])

    def test_run_delegates_to_login_recovery_orchestrator(self):
        from rpa_platform.worker.wecom_bind_real_recovery import RealWecomBindRecovery

        orchestrator = FakeOrchestrator()
        recovery = RealWecomBindRecovery(orchestrator_factory=lambda _context: orchestrator)

        result = recovery.run(
            task_id="task-real-readonly",
            context={
                "enterprise_name": "zh_test_上海测试客户",
                "plain_corp_id": "ww_test_corp",
                "requested_user_id": "zh_test_user",
            },
        )

        self.assertEqual(result["status"], "ready_for_real_bind")
        self.assertEqual(orchestrator.calls[0]["task_id"], "task-real-readonly")
        self.assertEqual(orchestrator.calls[0]["context"]["enterprise_name"], "zh_test_上海测试客户")

    def test_unattended_write_recovery_runs_login_recovery_before_real_write(self):
        from rpa_platform.worker.wecom_bind_real_recovery import RealWecomBindUnattendedWriteRecovery

        events = []

        class FakeLoginRecovery:
            def run(self, task_id, context):
                events.append("login_recovery")
                return {
                    "status": "ready_for_real_bind",
                    "reason": "ready_for_confirm_write",
                    "preflight": {"status": "ok", "reason": "ready_for_confirm_write"},
                    "login_recovery": {"notify_attempts": 1, "restored": True},
                }

        def clients_builder(**_kwargs):
            events.append("clients")
            return {"jdy_client": object(), "wecom_client": object()}

        def write_runner(**kwargs):
            events.append("write")
            preflight = kwargs["preflight_runner"](None, jdy_client=kwargs["jdy_client"], wecom_client=kwargs["wecom_client"])
            return {
                "mode": "unattended_write",
                "status": "success",
                "preflight": preflight["preflight"],
                "login_recovery": kwargs["login_recovery"],
            }

        recovery = RealWecomBindUnattendedWriteRecovery(
            env={},
            login_recovery_factory=lambda _context: FakeLoginRecovery(),
            clients_builder=clients_builder,
            write_runner=write_runner,
            wait_seconds=0,
        )

        result = recovery.run(
            task_id="task-unattended-recovered",
            context={
                "enterprise_name": "zh_test_上海测试客户",
                "plain_corp_id": "ww_test_corp",
                "requested_user_id": "zh_test_user",
            },
        )

        self.assertEqual(events, ["login_recovery", "clients", "write"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["preflight"]["status"], "ok")
        self.assertEqual(result["login_recovery"]["notify_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
