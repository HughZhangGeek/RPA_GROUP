import json
import tempfile
import unittest
from pathlib import Path

from rpa_platform.storage.sqlite_store import SQLiteStore


class FlowVersionStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(
            self.team_id,
            "企微代开发应用上线",
            "简道云 Webhook 触发",
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_lists_flow_templates_for_team(self):
        flows = self.store.list_flow_templates(self.team_id)

        self.assertEqual(len(flows), 1)
        self.assertEqual(flows[0]["id"], self.flow_id)
        self.assertEqual(flows[0]["name"], "企微代开发应用上线")

    def test_copy_version_creates_new_draft_with_snapshot_steps(self):
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[{"key": "open_jdy", "name": "打开简道云后台", "action": "open_url"}],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, version_id)

        copied_id = self.store.copy_flow_version(
            flow_template_id=self.flow_id,
            source_version_id=version_id,
            created_by="admin",
        )

        copied = self.store.get_flow_version(copied_id)
        self.assertNotEqual(copied_id, version_id)
        self.assertEqual(copied["status"], "draft")
        self.assertEqual(copied["version_no"], 2)
        self.assertEqual(json.loads(copied["steps_json"])[0]["key"], "open_jdy")
        flow = self.store.get_flow_template(self.flow_id)
        self.assertEqual(flow["draft_version_id"], copied_id)
        self.assertEqual(flow["published_version_id"], version_id)

    def test_rollback_publishes_historical_version_and_archives_current(self):
        v1 = self.store.create_flow_version(
            self.flow_id,
            steps=[{"key": "v1", "name": "第一版", "action": "open_url"}],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, v1)
        v2 = self.store.create_flow_version(
            self.flow_id,
            steps=[{"key": "v2", "name": "第二版", "action": "click"}],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, v2)

        rolled_back_id = self.store.rollback_flow_version(self.flow_id, v1)

        flow = self.store.get_flow_template(self.flow_id)
        self.assertEqual(rolled_back_id, v1)
        self.assertEqual(flow["published_version_id"], v1)
        self.assertEqual(self.store.get_flow_version(v1)["status"], "published")
        self.assertEqual(self.store.get_flow_version(v2)["status"], "archived")


if __name__ == "__main__":
    unittest.main()
