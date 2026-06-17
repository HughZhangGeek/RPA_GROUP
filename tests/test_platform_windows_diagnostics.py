import unittest

from rpa_platform.worker.diagnostics import build_diagnostic_summary


class WindowsDiagnosticsTest(unittest.TestCase):
    def test_builds_diagnostic_summary_without_sensitive_values(self):
        summary = build_diagnostic_summary(
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            task_id="task-001",
            mode="manual_debug",
            hostname="WIN-RPA-01",
            session_name="console",
            interactive_desktop=True,
            screen_resolution="1920x1080",
            display_scaling="100%",
            pid=1234,
            service_version="0.1.0",
            started_at="2026-06-17T09:55:00+08:00",
            current_task_id="task-001",
            wss_connected=True,
            last_heartbeat_at="2026-06-17T10:03:45+08:00",
            log_path="C:/rpa_group/logs/worker.log",
            artifact_dir="C:/rpa_group/artifacts/task-001",
            sqlite_path="C:/rpa_group/data/platform-worker.db",
            recent_errors=[
                {
                    "at": "2026-06-17T10:03:00+08:00",
                    "error_type": "LOGIN_REQUIRED",
                    "step_key": "wecom_submit_online",
                    "message": "企微后台登录态失效，需要人工扫码",
                    "cookie": "must-not-leak",
                }
            ],
        )

        self.assertEqual(summary["task_id"], "task-001")
        self.assertTrue(summary["windows"]["interactive_desktop"])
        self.assertEqual(summary["windows"]["screen_resolution"], "1920x1080")
        self.assertEqual(summary["local_refs"]["log_path_hint"], "C:/rpa_group/logs/worker.log")
        rendered = str(summary).lower()
        self.assertNotIn("must-not-leak", rendered)
        self.assertNotIn("cookie", rendered)
        self.assertNotIn("encoding_aes_key", rendered)
        self.assertNotIn("kitsecret", rendered)

    def test_redacts_secret_patterns_without_rejecting_monitor_paths(self):
        summary = build_diagnostic_summary(
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            task_id="task-001",
            mode="manual_debug",
            hostname="WIN-RPA-01",
            session_name="console",
            interactive_desktop=True,
            screen_resolution="1920x1080",
            display_scaling="100%",
            pid=1234,
            service_version="0.1.0",
            started_at="2026-06-17T09:55:00+08:00",
            current_task_id="task-001",
            wss_connected=True,
            last_heartbeat_at="2026-06-17T10:03:45+08:00",
            log_path="C:/rpa_group/monitor/logs/worker.log",
            artifact_dir="C:/rpa_group/artifacts/task-001",
            sqlite_path="C:/rpa_group/data/platform-worker.db",
            recent_errors=[
                {
                    "at": "2026-06-17T10:03:00+08:00",
                    "error_type": "LOGIN_REQUIRED",
                    "step_key": "wecom_submit_online",
                    "message": "Authorization: Bearer secret-value",
                }
            ],
        )

        self.assertEqual(summary["local_refs"]["log_path_hint"], "C:/rpa_group/monitor/logs/worker.log")
        rendered = str(summary)
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("Bearer secret-value", rendered)

    def test_redacts_common_secret_message_formats(self):
        secret_messages = [
            "token: secret-value",
            "password=secret-value",
            "api_key: secret-value",
            "api-key: secret-value",
            '{"token":"secret-value"}',
        ]

        for message in secret_messages:
            with self.subTest(message=message):
                summary = build_diagnostic_summary(
                    machine_id="mch-001",
                    robot_id="windows-rpa-01",
                    task_id="task-001",
                    mode="manual_debug",
                    hostname="WIN-RPA-01",
                    session_name="console",
                    interactive_desktop=True,
                    screen_resolution="1920x1080",
                    display_scaling="100%",
                    pid=1234,
                    service_version="0.1.0",
                    started_at="2026-06-17T09:55:00+08:00",
                    current_task_id="task-001",
                    wss_connected=True,
                    last_heartbeat_at="2026-06-17T10:03:45+08:00",
                    log_path="C:/rpa_group/logs/worker.log",
                    artifact_dir="C:/rpa_group/artifacts/task-001",
                    sqlite_path="C:/rpa_group/data/platform-worker.db",
                    recent_errors=[
                        {
                            "at": "2026-06-17T10:03:00+08:00",
                            "error_type": "LOGIN_REQUIRED",
                            "step_key": "wecom_submit_online",
                            "message": message,
                        }
                    ],
                )

                self.assertNotIn("secret-value", str(summary))
