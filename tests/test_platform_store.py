import json
import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.storage.sqlite_store import SQLiteStore


class SQLiteStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "platform.db"
        self.store = SQLiteStore(str(self.db_path))
        self.store.init_schema()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_published_flow_snapshot_is_bound_when_task_is_created(self):
        team_id = self.store.create_team("交付团队", webhook_url="https://example.invalid/robot")
        flow_id = self.store.create_flow_template(
            team_id=team_id,
            name="企微代开发应用上线",
            description="简道云 Webhook 触发企微上线",
        )
        draft_id = self.store.create_flow_version(
            flow_template_id=flow_id,
            steps=[
                {"key": "open_jdy", "name": "打开简道云后台", "action": "open_url"},
                {"key": "derive_urls", "name": "生成企微配置 URL", "action": "derive_urls"},
            ],
            created_by="codex",
        )
        published_id = self.store.publish_flow_version(flow_id, draft_id)

        created = self.store.create_task_from_published_flow(
            team_id=team_id,
            flow_template_id=flow_id,
            enterprise_name="上海测试客户",
            corp_id="wwabc123",
            source_user_id="u001",
            idempotency_key="wecom_app_launch:wwabc123:u001",
            payload={"user_id": "u001", "企业客户名称": "上海测试客户", "企业微信明文 CorpID": "wwabc123"},
        )

        task = self.store.get_task(created.task_id)
        self.assertTrue(created.created)
        self.assertEqual(task["status"], TaskStatus.PENDING.value)
        self.assertEqual(task["flow_version_id"], published_id)
        snapshot = json.loads(task["flow_version_snapshot_json"])
        self.assertEqual(snapshot["version_no"], 1)
        self.assertEqual(snapshot["steps"][1]["key"], "derive_urls")

    def test_idempotent_task_creation_returns_existing_task(self):
        team_id = self.store.create_team("交付团队")
        flow_id = self.store.create_flow_template(team_id, "企微代开发应用上线", "")
        version_id = self.store.create_flow_version(
            flow_id,
            steps=[{"key": "start", "name": "开始", "action": "receive_webhook"}],
            created_by="codex",
        )
        self.store.publish_flow_version(flow_id, version_id)

        first = self.store.create_task_from_published_flow(
            team_id=team_id,
            flow_template_id=flow_id,
            enterprise_name="客户 A",
            corp_id="ww001",
            source_user_id="u001",
            idempotency_key="wecom_app_launch:ww001:u001",
            payload={"user_id": "u001"},
        )
        second = self.store.create_task_from_published_flow(
            team_id=team_id,
            flow_template_id=flow_id,
            enterprise_name="客户 A",
            corp_id="ww001",
            source_user_id="u001",
            idempotency_key="wecom_app_launch:ww001:u001",
            payload={"user_id": "u001"},
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.task_id, second.task_id)


if __name__ == "__main__":
    unittest.main()
