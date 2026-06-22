import unittest
from pathlib import Path


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

    def test_local_full_jdy_login_recovery_flow_continues_to_unattended_write(self):
        from rpa_platform.worker.wecom_bind_real_recovery import RealWecomBindUnattendedWriteRecovery
        from rpa_platform.worker.wecom_login_recovery import (
            LoginRecoveryConfig,
            LoginSessionHealthChecker,
            WecomLoginRecoveryOrchestrator,
        )

        events = []
        preflight_results = [
            {"status": "blocked", "reason": "jdy_session_expired", "detail": "用户尚未登录"},
            {"status": "ok", "reason": "ready_for_confirm_write"},
        ]

        class FakeQrProvider:
            def capture(self):
                events.append("qr_captured")
                return Path("jdy-qr.png")

            def close(self):
                events.append("qr_closed")

        class FakeNotifier:
            def notify_qr(self, *, task_id, qr_path, expires_at, context):
                events.append("qr_notified")

        class FakeSessionRefresher:
            def refresh(self):
                events.append("cookie_refreshed")
                return True

        def preflight():
            result = preflight_results.pop(0)
            events.append("preflight_%s" % result["reason"])
            return result

        def health_probe():
            events.append("health_restored")
            return {"corp_deploy_list": []}

        login_recovery = WecomLoginRecoveryOrchestrator(
            config=LoginRecoveryConfig(
                enabled=True,
                qr_notify_enabled=True,
                ttl_seconds=30,
                poll_interval_seconds=1,
                max_notify_times=1,
                trigger_reason="jdy_session_expired",
                login_not_restored_reason="jdy_login_not_restored",
                retry_action="retry_jdy_login_qr",
            ),
            preflight=preflight,
            health_checker=LoginSessionHealthChecker(health_probe),
            qr_provider=FakeQrProvider(),
            notifier=FakeNotifier(),
            session_refresher=FakeSessionRefresher(),
            sleep=lambda _seconds: None,
            now=lambda: 1000.0,
        )

        def clients_builder(**_kwargs):
            events.append("clients_built")
            return {"jdy_client": object(), "wecom_client": object()}

        def write_runner(**kwargs):
            events.append("real_write_started")
            preflight_result = kwargs["preflight_runner"]()
            return {
                "mode": "unattended_write",
                "status": "success",
                "preflight": preflight_result["preflight"],
                "login_recovery": kwargs["login_recovery"],
            }

        recovery = RealWecomBindUnattendedWriteRecovery(
            env={},
            login_recovery_factory=lambda _context: login_recovery,
            clients_builder=clients_builder,
            write_runner=write_runner,
            wait_seconds=0,
        )

        result = recovery.run(
            task_id="task-local-full-recovery",
            context={
                "enterprise_name": "zh_test_上海测试客户",
                "plain_corp_id": "ww_test_corp",
                "requested_user_id": "zh_test_user",
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["preflight"]["status"], "ok")
        self.assertEqual(
            events,
            [
                "preflight_jdy_session_expired",
                "qr_captured",
                "qr_notified",
                "cookie_refreshed",
                "health_restored",
                "preflight_ready_for_confirm_write",
                "qr_closed",
                "clients_built",
                "real_write_started",
            ],
        )

    def test_chained_login_recovery_runs_wecom_after_jdy_restore_exposes_wecom_expired(self):
        from rpa_platform.worker.wecom_bind_real_recovery import ChainedLoginRecoveryOrchestrator

        events = []

        class FakeJdyRecovery:
            def run(self, task_id, context):
                events.append("jdy")
                return {"status": "blocked", "reason": "wecom_session_expired"}

        class FakeWecomRecovery:
            def run(self, task_id, context):
                events.append("wecom")
                return {"status": "ready_for_real_bind", "preflight": {"status": "ok"}}

        result = ChainedLoginRecoveryOrchestrator(FakeJdyRecovery(), FakeWecomRecovery()).run(
            task_id="task-both-expired",
            context={"enterprise_name": "zh_test_上海测试客户"},
        )

        self.assertEqual(events, ["jdy", "wecom"])
        self.assertEqual(result["status"], "ready_for_real_bind")

    def test_jdy_login_recovery_selector_keeps_jdy_container_candidates_when_wecom_selector_is_configured(self):
        from rpa_platform.worker.wecom_bind_real_recovery import _jdy_login_recovery_config_from_env

        config = _jdy_login_recovery_config_from_env(
            {
                "WECOM_QR_SELECTOR": (
                    "canvas, img[src*='qr'], img[src*='qrcode'], img[src*='login'], "
                    "[class*='qr'] canvas, [class*='qr'] img"
                )
            }
        )

        self.assertIn("[id*='qrcode' i]", config.qr_selector)
        self.assertIn("[id*='qr' i]", config.qr_selector)
        self.assertIn("[class*='qrcode' i]", config.qr_selector)
        self.assertIn("[class*='qr' i]", config.qr_selector)

    def test_jdy_login_recovery_notifier_uses_jdyan_login_text(self):
        from rpa_platform.worker.wecom_bind_real_recovery import (
            _build_jdy_orchestrator,
            _jdy_login_recovery_config_from_env,
        )

        config = _jdy_login_recovery_config_from_env({})
        orchestrator = _build_jdy_orchestrator(
            config,
            {},
            {
                "enterprise_name": "zh_test_上海测试客户",
                "plain_corp_id": "ww_test_corp",
                "requested_user_id": "zh_test_user",
            },
        )

        self.assertEqual(orchestrator.notifier.title, "简道眼登录")
        self.assertIn("简道眼登录态失效", orchestrator.notifier.status_text)


if __name__ == "__main__":
    unittest.main()
