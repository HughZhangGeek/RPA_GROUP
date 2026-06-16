import tempfile
import unittest
from pathlib import Path

from rpa_platform.server.webhook_service import JdyWebhookService, PayloadValidationError
from rpa_platform.storage.sqlite_store import SQLiteStore


class JdyWebhookServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(self.team_id, "企微代开发应用上线", "")
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[{"key": "receive_webhook", "name": "接收 Webhook", "action": "receive_webhook"}],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, version_id)
        self.service = JdyWebhookService(self.store, self.team_id, self.flow_id)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_creates_task_from_required_jdy_payload(self):
        result = self.service.receive(
            {
                "user_id": "u001",
                "企业客户名称": "上海测试客户",
                "企业微信明文 CorpID": "wwabc123",
            }
        )

        task = self.store.get_task(result.task_id)
        self.assertTrue(result.created)
        self.assertEqual(task["enterprise_name"], "上海测试客户")
        self.assertEqual(task["corp_id"], "wwabc123")
        self.assertEqual(task["source_user_id"], "u001")
        self.assertEqual(task["idempotency_key"], "wecom_app_launch:wwabc123:u001")

    def test_duplicate_payload_returns_existing_task(self):
        payload = {
            "user_id": "u001",
            "企业客户名称": "上海测试客户",
            "企业微信明文 CorpID": "wwabc123",
        }

        first = self.service.receive(payload)
        second = self.service.receive(payload)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.task_id, second.task_id)

    def test_rejects_payload_without_corp_id(self):
        with self.assertRaises(PayloadValidationError):
            self.service.receive({"user_id": "u001", "企业客户名称": "上海测试客户"})


if __name__ == "__main__":
    unittest.main()
