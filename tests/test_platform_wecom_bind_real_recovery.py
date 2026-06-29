import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
        self.assertTrue(bind_input.wecom_suite_explicit)

    def test_build_bind_input_from_csm_semantic_payload(self):
        from rpa_platform.worker.wecom_bind_real_recovery import build_bind_input_from_context

        bind_input = build_bind_input_from_context(
            {
                "enterprise_name": "zh_test_上海测试客户",
                "enterprise_short_name": "上海测试",
                "corp_id": "ww_semantic_corp",
                "userid": "zh_test_userid",
                "source_entry_id": "6258e5f6e09e970007b0150c",
                "current_home_url": "//dashboard",
                "current_webhook_url": "//corp/service",
            }
        )

        self.assertEqual(bind_input.enterprise_name, "zh_test_上海测试客户")
        self.assertEqual(bind_input.enterprise_short_name, "上海测试")
        self.assertEqual(bind_input.plain_corp_id, "ww_semantic_corp")
        self.assertEqual(bind_input.requested_user_id, "zh_test_userid")
        self.assertEqual(bind_input.wecom_suiteid, 1009479)
        self.assertEqual(bind_input.suite_name, "简道云")
        self.assertFalse(bind_input.wecom_suite_explicit)

    def test_missing_required_context_returns_business_unexecutable_without_write(self):
        from rpa_platform.worker.wecom_bind_real_recovery import RealWecomBindRecovery

        orchestrator = FakeOrchestrator()
        recovery = RealWecomBindRecovery(orchestrator_factory=lambda _context: orchestrator)

        result = recovery.run(
            task_id="task-missing",
            context={"userid": "zh_test_userid"},
        )

        self.assertEqual(result["status"], "business_unexecutable")
        self.assertEqual(result["reason"], "missing_enterprise_identity")
        self.assertIn("enterprise_identity", result["missing_fields"])
        self.assertEqual(orchestrator.calls, [])

    def test_business_preflight_blocked_result_becomes_business_unexecutable(self):
        from rpa_platform.worker.wecom_bind_real_recovery import RealWecomBindRecovery

        class BusinessBlockedOrchestrator:
            def run(self, task_id, context):
                return {
                    "status": "blocked",
                    "reason": "wecom_app_not_unique_or_missing",
                    "detail": "no custom app matched authcorp name and app name",
                }

        recovery = RealWecomBindRecovery(orchestrator_factory=lambda _context: BusinessBlockedOrchestrator())

        result = recovery.run(
            task_id="task-business-blocked",
            context={
                "enterprise_name": "zh_test_上海测试客户",
                "corp_id": "ww_test_corp",
                "userid": "zh_test_user",
            },
        )

        self.assertEqual(result["status"], "business_unexecutable")
        self.assertEqual(result["reason"], "wecom_app_not_unique_or_missing")

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

    def test_env_built_jdy_login_recovery_refreshes_cookie_and_continues_unattended_write(self):
        from rpa_platform.worker.wecom_bind_real_recovery import (
            RealWecomBindUnattendedWriteRecovery,
            _build_jdy_orchestrator,
            _jdy_login_recovery_config_from_env,
        )

        events = []

        class FakeQrProvider:
            def __init__(self, **_kwargs):
                self.qr_path = qr_path

            def capture(self):
                events.append("qr_captured")
                return self.qr_path

            def close(self):
                events.append("qr_closed")

        class FakeCookieExporter:
            def __init__(self, *, wecom_url, **_kwargs):
                events.append("cookie_exporter:%s" % wecom_url)

            def __call__(self):
                events.append("cookie_exported")
                return "jdy-cookie-after-scan"

        class FakeBotClient:
            def __init__(self, webhook_url):
                self.webhook_url = webhook_url

            def send(self, payload):
                events.append("qr_notified:%s" % payload["msgtype"])
                self.last_payload = payload
                return {"errcode": 0}

        class FakeJdyProbe:
            def __init__(self, *, cookie_file, **_kwargs):
                self.cookie_file = Path(cookie_file)

            def __call__(self):
                events.append("health_cookie:%s" % self.cookie_file.read_text(encoding="utf-8"))
                return {"corp_deploy_list": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            qr_path = root / "jdy-qr.png"
            qr_path.write_bytes(b"qr")
            jdy_cookie_file = root / "jdy-admin.cookie"
            wecom_cookie_file = root / "wecom-admin.cookie"
            wecom_cookie_file.write_text("wecom-cookie", encoding="utf-8")
            env = {
                "JDY_LOGIN_RECOVERY_ENABLED": "true",
                "JDY_QR_NOTIFY_ENABLED": "true",
                "JDY_QR_NOTIFY_WEBHOOK_URL": "https://example.invalid/webhook",
                "JDY_QR_NOTIFY_MODE": "markdown",
                "JDY_QR_TTL_SECONDS": "3",
                "JDY_QR_POLL_INTERVAL_SECONDS": "1",
                "JDY_QR_MAX_NOTIFY_TIMES": "1",
                "JDY_ADMIN_COOKIE_FILE": str(jdy_cookie_file),
                "JDY_BROWSER_PROFILE_DIR": str(root / "jdy-profile"),
                "JDY_LOGIN_RECOVERY_NODE_WORK_DIR": str(root / "jdy-node"),
                "JDY_QR_ARTIFACT_DIR": str(root / "jdy-qr"),
                "JDY_LOGIN_URL": "https://dc.jdydevelop.com/sa?redirect_uri=%2F",
                "WECOM_ADMIN_COOKIE_FILE": str(wecom_cookie_file),
            }
            preflight_results = [
                {"status": "blocked", "reason": "jdy_session_expired", "detail": "用户尚未登录"},
                {"status": "ok", "reason": "ready_for_confirm_write"},
            ]

            def fake_build_real_clients(*, jdy_cookie_file, wecom_cookie_file):
                events.append("clients_for_preflight:%s|%s" % (Path(jdy_cookie_file).name, Path(wecom_cookie_file).name))
                return {"jdy_client": object(), "wecom_client": object()}

            def fake_run_readonly_preflight(_bind_input, **_clients):
                result = preflight_results.pop(0)
                events.append("preflight:%s" % result["reason"])
                return result

            def clients_builder(**kwargs):
                events.append("clients_built:%s|%s" % (Path(kwargs["jdy_cookie_file"]).name, Path(kwargs["wecom_cookie_file"]).name))
                return {"jdy_client": object(), "wecom_client": object()}

            def write_runner(**kwargs):
                events.append("real_write_started")
                preflight = kwargs["preflight_runner"]()
                return {
                    "mode": "unattended_write",
                    "status": "success",
                    "preflight": preflight["preflight"],
                    "login_recovery": kwargs["login_recovery"],
                }

            with patch("rpa_platform.worker.wecom_bind_real_recovery.PlaywrightQrArtifactProvider", FakeQrProvider):
                with patch("rpa_platform.worker.wecom_bind_real_recovery.PlaywrightWecomCookieExporter", FakeCookieExporter):
                    with patch("rpa_platform.worker.wecom_bind_real_recovery.WecomBotClient", FakeBotClient):
                        with patch("rpa_platform.worker.wecom_bind_real_recovery.JdyCookieFileReadonlyProbe", FakeJdyProbe):
                            with patch(
                                "rpa_platform.worker.wecom_bind_real_recovery.build_real_clients",
                                side_effect=fake_build_real_clients,
                            ):
                                with patch(
                                    "rpa_platform.worker.wecom_bind_real_recovery.run_readonly_preflight",
                                    side_effect=fake_run_readonly_preflight,
                                ):
                                    config = _jdy_login_recovery_config_from_env(env)
                                    recovery = RealWecomBindUnattendedWriteRecovery(
                                        env=env,
                                        login_recovery_factory=lambda context: _build_jdy_orchestrator(config, env, context),
                                        clients_builder=clients_builder,
                                        write_runner=write_runner,
                                        wait_seconds=0,
                                    )
                                    result = recovery.run(
                                        task_id="task-jdy-env-built",
                                        context={
                                            "enterprise_name": "zh_test_上海测试客户",
                                            "enterprise_short_name": "zh_test_上海",
                                            "plain_corp_id": "ww_test_corp",
                                            "requested_user_id": "zh_test_user",
                                        },
                                    )
                                    refreshed_cookie = jdy_cookie_file.read_text(encoding="utf-8")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["preflight"]["status"], "ok")
        self.assertEqual(refreshed_cookie, "jdy-cookie-after-scan")
        self.assertEqual(
            events,
            [
                "cookie_exporter:https://dc.jdydevelop.com/sa?redirect_uri=%2F",
                "clients_for_preflight:jdy-admin.cookie|wecom-admin.cookie",
                "preflight:jdy_session_expired",
                "qr_captured",
                "qr_notified:markdown",
                "cookie_exported",
                "health_cookie:jdy-cookie-after-scan",
                "clients_for_preflight:jdy-admin.cookie|wecom-admin.cookie",
                "preflight:ready_for_confirm_write",
                "qr_closed",
                "clients_built:jdy-admin.cookie|wecom-admin.cookie",
                "real_write_started",
            ],
        )


if __name__ == "__main__":
    unittest.main()
