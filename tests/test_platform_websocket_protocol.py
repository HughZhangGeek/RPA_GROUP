import unittest

from rpa_platform.worker.websocket_protocol import (
    WorkerRegisterPayload,
    build_envelope,
    parse_envelope,
)


class WebSocketProtocolTest(unittest.TestCase):
    def test_builds_register_envelope_without_sensitive_values(self):
        payload = WorkerRegisterPayload(
            hostname="WIN-RPA-01",
            service_version="0.1.0",
            capabilities={"wecom_bind_service": True},
            login_health={"jdy_admin": "ok", "wecom_admin": "ok"},
            current_task=None,
        )

        envelope = build_envelope(
            message_type="worker.register",
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            payload=payload.to_dict(),
            message_id="msg-001",
            sent_at="2026-06-17T10:00:00+08:00",
        )

        self.assertEqual(envelope["type"], "worker.register")
        self.assertEqual(envelope["machine_id"], "mch-001")
        self.assertEqual(envelope["payload"]["hostname"], "WIN-RPA-01")
        self.assertNotIn("cookie", str(envelope).lower())
        self.assertNotIn("encoding_aes_key", str(envelope).lower())

    def test_waiting_login_error_uses_link_only_manual_action(self):
        envelope = build_envelope(
            message_type="task.error",
            machine_id="mch-001",
            robot_id="windows-rpa-01",
            payload={
                "task_id": "task-001",
                "status": "waiting_login",
                "error_type": "LOGIN_REQUIRED",
                "error_message": "企微后台登录态失效，需要人工扫码",
                "step_key": "wecom_submit_online",
                "retryable": True,
                "manual_action": {
                    "action_type": "login_required",
                    "target": "wecom_admin",
                    "notify_audience": "rpa_admins",
                    "notification_channel": "wecom_bot",
                    "notification_mode": "link_only",
                    "handle_url": "https://jdycsm.example.com/rpa/manual-actions/action-001",
                    "qr_delivery": "not_uploaded",
                },
                "artifact_refs": [],
            },
            message_id="msg-002",
            sent_at="2026-06-17T10:03:00+08:00",
        )

        manual_action = envelope["payload"]["manual_action"]
        self.assertEqual(manual_action["notify_audience"], "rpa_admins")
        self.assertEqual(manual_action["notification_mode"], "link_only")
        self.assertEqual(manual_action["qr_delivery"], "not_uploaded")
        self.assertNotIn("qr_image", str(envelope))

    def test_parse_rejects_missing_message_id(self):
        with self.assertRaises(ValueError):
            parse_envelope(
                {
                    "type": "worker.heartbeat",
                    "sent_at": "2026-06-17T10:00:00+08:00",
                    "machine_id": "mch-001",
                    "robot_id": "windows-rpa-01",
                    "payload": {},
                }
            )

    def test_build_envelope_rejects_sensitive_headers(self):
        with self.assertRaises(ValueError):
            build_envelope(
                message_type="task.progress",
                machine_id="mch-001",
                robot_id="windows-rpa-01",
                payload={"headers": {"Authorization": "Bearer secret-value"}},
                message_id="msg-sensitive",
                sent_at="2026-06-17T10:04:00+08:00",
            )
