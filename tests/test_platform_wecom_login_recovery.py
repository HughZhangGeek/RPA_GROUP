import os
import tempfile
import unittest
import json
import subprocess
import sys
from subprocess import CompletedProcess
from pathlib import Path

from rpa_platform.worker.wecom_login_recovery import (
    LoginRecoveryConfig,
    LoginSessionHealthChecker,
    LoginSessionStatus,
    LocalQrArtifactProvider,
    PlaywrightQrArtifactProvider,
    PlaywrightWecomCookieExporter,
    WecomQrLoginNotifier,
    WecomCookieFileReadonlyProbe,
    WecomCookieSessionRefresher,
    WecomLoginRecoveryOrchestrator,
)


class FakeReadonlyProbe:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self):
        self.calls.append("called")
        if self.responses:
            return self.responses.pop(0)
        return {"data": {"corpapp": []}}


class FakeQrProvider:
    def __init__(self, path):
        self.path = path
        self.calls = 0

    def capture(self):
        self.calls += 1
        return self.path


class ClosableFakeQrProvider(FakeQrProvider):
    def __init__(self, path):
        super().__init__(path)
        self.closed = False

    def close(self):
        self.closed = True


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify_qr(self, *, task_id, qr_path, expires_at, context):
        self.calls.append(
            {
                "task_id": task_id,
                "qr_path": qr_path,
                "expires_at": expires_at,
                "context": context,
            }
        )


class FakeSessionRefresher:
    def __init__(self):
        self.calls = 0

    def refresh(self):
        self.calls += 1
        return True


class LoginSessionHealthCheckerTest(unittest.TestCase):
    def test_classifies_outsession_login_page_forbidden_and_valid_json(self):
        cases = [
            ({"result": {"errCode": -3, "message": "outsession"}}, LoginSessionStatus.EXPIRED),
            ("<html><title>企业微信登录</title></html>", LoginSessionStatus.EXPIRED),
            ({"status_code": 403, "body": "forbidden"}, LoginSessionStatus.EXPIRED),
            ({"data": {"corpapp": []}}, LoginSessionStatus.RESTORED),
            ({"unexpected": "shape"}, LoginSessionStatus.ERROR),
        ]

        for response, expected in cases:
            with self.subTest(response=response):
                checker = LoginSessionHealthChecker(FakeReadonlyProbe([response]))
                result = checker.check()

                self.assertEqual(result.status, expected)


class WecomLoginRecoveryOrchestratorTest(unittest.TestCase):
    def test_expired_preflight_sends_qr_polls_until_restored_and_reruns_preflight(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            qr_path = Path(tmpdir) / "qr.png"
            qr_path.write_bytes(b"qr")
            preflight_results = [
                {"status": "blocked", "reason": "wecom_session_expired", "detail": "outsession"},
                {"status": "ok", "reason": "ready_for_confirm_write"},
            ]
            notifier = FakeNotifier()
            orchestrator = WecomLoginRecoveryOrchestrator(
                config=LoginRecoveryConfig(enabled=True, qr_notify_enabled=True, ttl_seconds=120, max_notify_times=1),
                preflight=lambda: preflight_results.pop(0),
                health_checker=LoginSessionHealthChecker(
                    FakeReadonlyProbe(
                        [
                            {"result": {"errCode": -3, "message": "outsession"}},
                            {"data": {"corpapp": []}},
                        ]
                    )
                ),
                qr_provider=FakeQrProvider(qr_path),
                notifier=notifier,
                sleep=lambda seconds: None,
                now=lambda: 1000.0,
            )

            result = orchestrator.run(task_id="task-001", context={"enterprise_name": "上海测试客户"})

        self.assertEqual(result["status"], "ready_for_real_bind")
        self.assertEqual(result["reason"], "ready_for_confirm_write")
        self.assertEqual(result["preflight"]["status"], "ok")
        self.assertEqual(notifier.calls[0]["task_id"], "task-001")
        self.assertEqual(notifier.calls[0]["expires_at"], 1120.0)
        self.assertEqual(notifier.calls[0]["context"]["enterprise_name"], "上海测试客户")

    def test_timeout_returns_waiting_login_with_retry_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            qr_path = Path(tmpdir) / "qr.png"
            qr_path.write_bytes(b"qr")
            notifier = FakeNotifier()
            provider = FakeQrProvider(qr_path)
            orchestrator = WecomLoginRecoveryOrchestrator(
                config=LoginRecoveryConfig(
                    enabled=True,
                    qr_notify_enabled=True,
                    ttl_seconds=10,
                    poll_interval_seconds=5,
                    max_notify_times=3,
                ),
                preflight=lambda: {"status": "blocked", "reason": "wecom_session_expired", "detail": "outsession"},
                health_checker=LoginSessionHealthChecker(
                    FakeReadonlyProbe(
                        [
                            {"result": {"errCode": -3, "message": "outsession"}},
                            {"result": {"errCode": -3, "message": "outsession"}},
                        ]
                    )
                ),
                qr_provider=provider,
                notifier=notifier,
                sleep=lambda seconds: None,
                now=lambda: 1000.0,
            )

            result = orchestrator.run(
                task_id="task-timeout",
                context={"enterprise_name": "上海测试客户", "notify_attempts": 1},
            )

        self.assertEqual(result["status"], "waiting_login")
        self.assertEqual(result["reason"], "wecom_login_not_restored")
        self.assertEqual(result["expires_at"], 1010.0)
        self.assertEqual(result["notify_attempts"], 2)
        self.assertEqual(result["remaining_notify_attempts"], 1)
        self.assertEqual(result["next_action"], "retry_wecom_login_qr")
        self.assertEqual(result["retry_after"], 1010.0)
        self.assertEqual(len(notifier.calls), 1)
        self.assertEqual(provider.calls, 1)

    def test_allows_retrigger_until_notify_limit_then_requires_manual_escalation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            qr_path = Path(tmpdir) / "qr.png"
            qr_path.write_bytes(b"qr")
            notifier = FakeNotifier()
            provider = FakeQrProvider(qr_path)
            orchestrator = WecomLoginRecoveryOrchestrator(
                config=LoginRecoveryConfig(
                    enabled=True,
                    qr_notify_enabled=True,
                    ttl_seconds=5,
                    poll_interval_seconds=5,
                    max_notify_times=2,
                ),
                preflight=lambda: {"status": "blocked", "reason": "wecom_session_expired"},
                health_checker=LoginSessionHealthChecker(
                    FakeReadonlyProbe([{"result": {"errCode": -3, "message": "outsession"}}])
                ),
                qr_provider=provider,
                notifier=notifier,
                sleep=lambda seconds: None,
                now=lambda: 2000.0,
            )

            retried = orchestrator.run(
                task_id="task-retry",
                context={"enterprise_name": "上海测试客户", "login_recovery": {"notify_attempts": 1}},
            )

        self.assertEqual(retried["status"], "waiting_login")
        self.assertEqual(retried["notify_attempts"], 2)
        self.assertEqual(retried["remaining_notify_attempts"], 0)
        self.assertEqual(retried["next_action"], "manual_escalation_required")
        self.assertEqual(len(notifier.calls), 1)
        self.assertEqual(provider.calls, 1)

        exhausted_provider = FakeQrProvider(qr_path)
        exhausted_notifier = FakeNotifier()
        exhausted = WecomLoginRecoveryOrchestrator(
            config=LoginRecoveryConfig(enabled=True, qr_notify_enabled=True, max_notify_times=2),
            preflight=lambda: {"status": "blocked", "reason": "wecom_session_expired"},
            health_checker=LoginSessionHealthChecker(FakeReadonlyProbe([])),
            qr_provider=exhausted_provider,
            notifier=exhausted_notifier,
            sleep=lambda seconds: None,
            now=lambda: 3000.0,
        ).run(
            task_id="task-exhausted",
            context={"enterprise_name": "上海测试客户", "notify_attempts": 2},
        )

        self.assertEqual(exhausted["status"], "login_recovery_notify_exhausted")
        self.assertEqual(exhausted["manual_action"], "manual_escalation_required")
        self.assertEqual(exhausted["notify_attempts"], 2)
        self.assertEqual(exhausted["remaining_notify_attempts"], 0)
        self.assertEqual(exhausted_provider.calls, 0)
        self.assertEqual(exhausted_notifier.calls, [])

    def test_refreshes_cookie_session_before_each_login_health_poll(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            qr_path = Path(tmpdir) / "qr.png"
            qr_path.write_bytes(b"qr")
            preflight_results = [
                {"status": "blocked", "reason": "wecom_session_expired"},
                {"status": "ok", "reason": "ready_for_confirm_write"},
            ]
            refresher = FakeSessionRefresher()
            orchestrator = WecomLoginRecoveryOrchestrator(
                config=LoginRecoveryConfig(enabled=True, qr_notify_enabled=False, ttl_seconds=10, poll_interval_seconds=1),
                preflight=lambda: preflight_results.pop(0),
                health_checker=LoginSessionHealthChecker(
                    FakeReadonlyProbe(
                        [
                            {"result": {"errCode": -3, "message": "outsession"}},
                            {"data": {"corpapp": []}},
                        ]
                    )
                ),
                qr_provider=FakeQrProvider(qr_path),
                notifier=FakeNotifier(),
                session_refresher=refresher,
                sleep=lambda seconds: None,
                now=lambda: 1000.0,
            )

            result = orchestrator.run(task_id="task-004", context={})

        self.assertEqual(result["status"], "ready_for_real_bind")
        self.assertEqual(refresher.calls, 2)

    def test_closes_qr_provider_after_login_recovery_finishes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            qr_path = Path(tmpdir) / "qr.png"
            qr_path.write_bytes(b"qr")
            qr_provider = ClosableFakeQrProvider(qr_path)
            preflight_results = [
                {"status": "blocked", "reason": "wecom_session_expired"},
                {"status": "ok", "reason": "ready_for_confirm_write"},
            ]
            orchestrator = WecomLoginRecoveryOrchestrator(
                config=LoginRecoveryConfig(enabled=True, qr_notify_enabled=False, ttl_seconds=10, poll_interval_seconds=1),
                preflight=lambda: preflight_results.pop(0),
                health_checker=LoginSessionHealthChecker(FakeReadonlyProbe([{"data": {"corpapp": []}}])),
                qr_provider=qr_provider,
                notifier=FakeNotifier(),
                sleep=lambda seconds: None,
                now=lambda: 1000.0,
            )

            result = orchestrator.run(task_id="task-005", context={})

        self.assertEqual(result["status"], "ready_for_real_bind")
        self.assertTrue(qr_provider.closed)

    def test_review_preflight_after_restore_becomes_manual_confirm_required(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            qr_path = Path(tmpdir) / "qr.png"
            qr_path.write_bytes(b"qr")
            preflight_results = [
                {"status": "blocked", "reason": "wecom_session_expired"},
                {"status": "review", "reason": "jdy_corp_name_mismatch"},
            ]
            orchestrator = WecomLoginRecoveryOrchestrator(
                config=LoginRecoveryConfig(enabled=True, qr_notify_enabled=False, ttl_seconds=60, poll_interval_seconds=1),
                preflight=lambda: preflight_results.pop(0),
                health_checker=LoginSessionHealthChecker(FakeReadonlyProbe([{"data": {"corpapp": []}}])),
                qr_provider=FakeQrProvider(qr_path),
                notifier=FakeNotifier(),
                sleep=lambda seconds: None,
                now=lambda: 2000.0,
            )

            result = orchestrator.run(task_id="task-002", context={})

        self.assertEqual(result["status"], "manual_confirm_required")
        self.assertEqual(result["reason"], "jdy_corp_name_mismatch")

    def test_expired_preflight_returns_blocked_when_recovery_disabled(self):
        orchestrator = WecomLoginRecoveryOrchestrator(
            config=LoginRecoveryConfig(enabled=False),
            preflight=lambda: {"status": "blocked", "reason": "wecom_session_expired"},
            health_checker=LoginSessionHealthChecker(FakeReadonlyProbe([])),
            qr_provider=FakeQrProvider(Path("unused.png")),
            notifier=FakeNotifier(),
            sleep=lambda seconds: None,
            now=lambda: 1.0,
        )

        result = orchestrator.run(task_id="task-003", context={})

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "wecom_session_expired")


class LoginRecoveryConfigTest(unittest.TestCase):
    def test_loads_qr_notification_settings_from_env(self):
        config = LoginRecoveryConfig.from_env(
            {
                "WECOM_LOGIN_RECOVERY_ENABLED": "true",
                "WECOM_QR_NOTIFY_ENABLED": "true",
                "WECOM_QR_NOTIFY_WEBHOOK_URL": "https://example.invalid/wecom-bot",
                "WECOM_QR_NOTIFY_MODE": "image",
                "WECOM_QR_NOTIFY_MENTION_MOBILES": "13800000000, 13900000000",
                "WECOM_QR_TTL_SECONDS": "180",
                "WECOM_QR_MAX_NOTIFY_TIMES": "2",
                "WECOM_QR_ARTIFACT_DIR": ".local/custom-qr",
                "WECOM_ADMIN_COOKIE_FILE": ".local/custom.cookie",
                "WECOM_BROWSER_PROFILE_DIR": ".local/custom-profile",
                "WECOM_LOGIN_RECOVERY_NODE_WORK_DIR": ".local/custom-node",
                "WECOM_LOGIN_URL": "https://example.invalid/wecom-login",
                "WECOM_QR_SELECTOR": ".custom-qr",
                "WECOM_BROWSER_CHANNEL": "msedge",
            }
        )

        self.assertTrue(config.enabled)
        self.assertTrue(config.qr_notify_enabled)
        self.assertEqual(config.qr_notify_webhook_url, "https://example.invalid/wecom-bot")
        self.assertEqual(config.qr_notify_mode, "image")
        self.assertEqual(config.qr_notify_mention_mobiles, ["13800000000", "13900000000"])
        self.assertEqual(config.ttl_seconds, 180)
        self.assertEqual(config.max_notify_times, 2)
        self.assertEqual(config.artifact_dir, ".local/custom-qr")
        self.assertEqual(config.cookie_file, ".local/custom.cookie")
        self.assertEqual(config.browser_profile_dir, ".local/custom-profile")
        self.assertEqual(config.node_work_dir, ".local/custom-node")
        self.assertEqual(config.login_url, "https://example.invalid/wecom-login")
        self.assertEqual(config.qr_selector, ".custom-qr")
        self.assertEqual(config.browser_channel, "msedge")


class WecomQrLoginNotifierTest(unittest.TestCase):
    def test_sends_markdown_text_and_image_without_leaking_sensitive_context(self):
        sent = []

        class FakeBot:
            def send(self, payload):
                sent.append(payload)
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            qr_path = Path(tmpdir) / "qr.png"
            qr_path.write_bytes(bytes([4, 5, 6]))
            notifier = WecomQrLoginNotifier(FakeBot(), mentioned_mobile_list=["13800000000"])

            notifier.notify_qr(
                task_id="task-001",
                qr_path=qr_path,
                expires_at=1000.0,
                context={
                    "enterprise_name": "上海测试客户",
                    "plain_corp_id": "corp-id-placeholder",
                },
            )

        self.assertEqual([payload["msgtype"] for payload in sent], ["markdown", "text", "image"])
        markdown_content = sent[0]["markdown"]["content"]
        self.assertIn("**企业微信服务商后台登录**", markdown_content)
        self.assertIn("当前绑定任务客户：上海测试客户", markdown_content)
        self.assertIn("状态：企微服务商后台登录态失效，等待管理员扫码恢复", markdown_content)
        self.assertIn("过期时间：1970-01-01 08:16:40 北京时间", markdown_content)
        self.assertNotIn("过期时间戳", markdown_content)
        self.assertEqual(sent[1]["text"]["mentioned_mobile_list"], ["13800000000"])
        self.assertNotIn("corp-id-placeholder", str(sent))


class WecomLoginNotificationPreviewCliTest(unittest.TestCase):
    def test_utf8_preview_preserves_chinese_customer_name(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "rpa_platform.worker.wecom_login_notification_preview",
                "--task-id",
                "task-utf8",
                "--enterprise-name",
                "上海测试客户",
                "--expires-at",
                "1000",
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        content = payload["markdown"]["content"]
        self.assertIn("上海测试客户", content)
        self.assertNotIn("????", completed.stdout)


class LocalQrArtifactProviderTest(unittest.TestCase):
    def test_returns_newest_png_artifact_from_configured_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_path = Path(tmpdir) / "old.png"
            new_path = Path(tmpdir) / "new.png"
            old_path.write_bytes(b"old")
            new_path.write_bytes(b"new")
            old_path.touch()
            new_path.touch()

            provider = LocalQrArtifactProvider(tmpdir)

            self.assertEqual(provider.capture(), new_path)

    def test_raises_clear_error_when_no_qr_artifact_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalQrArtifactProvider(tmpdir)

            with self.assertRaises(FileNotFoundError) as ctx:
                provider.capture()

        self.assertIn("No WeCom login QR artifact found", str(ctx.exception))


class PlaywrightQrArtifactProviderTest(unittest.TestCase):
    def test_captures_qr_to_local_artifact_with_persistent_profile(self):
        commands = []

        def fake_run(command, cwd):
            commands.append({"command": command, "cwd": cwd})
            output_path = Path(command[command.index("--output-path") + 1])
            output_path.write_bytes(bytes([1, 2, 3]))
            return CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = PlaywrightQrArtifactProvider(
                profile_dir=root / "profile",
                artifact_dir=root / "qr",
                node_work_dir=root / "node",
                login_url="https://example.invalid/wecom-login",
                qr_selector=".login-qr",
                browser_channel="chrome",
                ensure_package=lambda node_work_dir: None,
                run_command=fake_run,
                keepalive_seconds=0,
                now=lambda: 1000.0,
            )

            qr_path = provider.capture()

            self.assertTrue(qr_path.name.startswith("wecom-login-qr-1000"))
            self.assertEqual(qr_path.read_bytes(), bytes([1, 2, 3]))
            command = commands[0]["command"]
            self.assertEqual(command[0], "node")
            self.assertIn("--profile-dir", command)
            self.assertIn("--output-path", command)
            self.assertIn("--qr-selector", command)
            self.assertNotIn("corp-id-placeholder", " ".join(command))

    def test_background_capture_returns_after_qr_exists_and_keeps_login_page_alive(self):
        commands = []

        class FakeProcess:
            def __init__(self):
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = 0

        fake_process = FakeProcess()

        def fake_start(command, cwd):
            commands.append({"command": command, "cwd": cwd})
            output_path = Path(command[command.index("--output-path") + 1])
            output_path.write_bytes(bytes([7, 8, 9]))
            return fake_process

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = PlaywrightQrArtifactProvider(
                profile_dir=root / "profile",
                artifact_dir=root / "qr",
                node_work_dir=root / "node",
                ensure_package=lambda node_work_dir: None,
                start_process=fake_start,
                keepalive_seconds=120,
                wait_timeout_seconds=1,
                sleep=lambda seconds: None,
                now=lambda: 1001.0,
            )

            qr_path = provider.capture()

            self.assertEqual(qr_path.read_bytes(), bytes([7, 8, 9]))
            self.assertIs(provider.process, fake_process)
            self.assertIn("--keepalive-seconds", commands[0]["command"])
            self.assertIn("120", commands[0]["command"])
            provider.close()
            self.assertTrue(fake_process.terminated)
            self.assertEqual(list((root / "node").glob("*.mjs")), [])

    def test_qr_capture_script_falls_back_to_visible_iframes(self):
        from rpa_platform.worker.wecom_login_recovery import _node_qr_capture_script

        script = _node_qr_capture_script()

        self.assertIn("findQrLocator", script)
        self.assertIn("page.frames()", script)
        self.assertIn("findInScope(frame", script)

    def test_qr_capture_script_rejects_tiny_loading_images(self):
        from rpa_platform.worker.wecom_login_recovery import _node_qr_capture_script

        script = _node_qr_capture_script()

        self.assertIn("minQrEdge", script)
        self.assertIn("boundingBox", script)
        self.assertIn("box.width >= minQrEdge", script)


class WecomCookieSessionTest(unittest.TestCase):
    def test_playwright_cookie_exporter_reads_cookie_from_persistent_profile(self):
        commands = []

        def fake_run(command, cwd):
            commands.append({"command": command, "cwd": cwd})
            output_path = Path(command[command.index("--output-path") + 1])
            output_path.write_text('{"wecom_cookie": "header-value-from-profile"}', encoding="utf-8")
            return CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            exporter = PlaywrightWecomCookieExporter(
                profile_dir=root / "profile",
                node_work_dir=root / "node",
                wecom_url="https://example.invalid/wecom",
                browser_channel="chrome",
                ensure_package=lambda node_work_dir: None,
                run_command=fake_run,
            )

            cookie_header = exporter()

        self.assertEqual(cookie_header, "header-value-from-profile")
        command = commands[0]["command"]
        self.assertIn("--profile-dir", command)
        self.assertIn("--wecom-url", command)
        self.assertIn("--output-path", command)
        self.assertNotIn("header-value-from-profile", " ".join(command))

    def test_session_refresher_writes_latest_cookie_with_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cookie_file = Path(tmpdir) / "wecom.cookie"
            refresher = WecomCookieSessionRefresher(
                cookie_file=cookie_file,
                export_cookie_header=lambda: "header-value-local",
            )

            result = refresher.refresh()

            self.assertTrue(result)
            self.assertEqual(cookie_file.read_text(encoding="utf-8"), "header-value-local")
            if os.name != "nt":
                self.assertEqual(cookie_file.stat().st_mode & 0o777, 0o600)

    def test_readonly_probe_reads_latest_cookie_file_for_each_call(self):
        calls = []

        def fake_get_json(path, params, headers):
            calls.append({"path": path, "params": params, "headers": headers})
            return {"data": {"corpapp": []}}

        with tempfile.TemporaryDirectory() as tmpdir:
            cookie_file = Path(tmpdir) / "wecom.cookie"
            cookie_file.write_text("header-value-first", encoding="utf-8")
            probe = WecomCookieFileReadonlyProbe(
                cookie_file=cookie_file,
                suiteid=1009479,
                enterprise_name="上海测试客户",
                request_json=fake_get_json,
            )

            first = probe()
            cookie_file.write_text("header-value-second", encoding="utf-8")
            second = probe()

        self.assertEqual(first, {"data": {"corpapp": []}})
        self.assertEqual(second, {"data": {"corpapp": []}})
        self.assertEqual(calls[0]["headers"]["cookie"], "header-value-first")
        self.assertEqual(calls[1]["headers"]["cookie"], "header-value-second")
        self.assertEqual(calls[0]["params"]["suiteid"], "1009479")
        self.assertEqual(calls[0]["params"]["corp_name_keyword"], "上海测试客户")

    def test_missing_cookie_file_is_treated_as_expired_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            probe = WecomCookieFileReadonlyProbe(
                cookie_file=Path(tmpdir) / "missing.cookie",
                suiteid=1009479,
                enterprise_name="上海测试客户",
                request_json=lambda path, params, headers: {"data": {"corpapp": []}},
            )
            checker = LoginSessionHealthChecker(probe)

            result = checker.check()

        self.assertEqual(result.status, LoginSessionStatus.EXPIRED)


if __name__ == "__main__":
    unittest.main()
