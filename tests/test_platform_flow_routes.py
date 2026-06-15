import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from rpa_platform.server.app import create_app
from rpa_platform.storage.sqlite_store import SQLiteStore


class FlowRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.default_flow_id = self.store.create_flow_template(self.team_id, "默认流程", "")
        version_id = self.store.create_flow_version(
            self.default_flow_id,
            steps=[{"key": "receive_webhook", "name": "接收 Webhook", "action": "receive_webhook"}],
            created_by="codex",
        )
        self.store.publish_flow_version(self.default_flow_id, version_id)
        self.app = create_app(self.store, self.team_id, self.default_flow_id)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_creates_and_lists_flow_templates(self):
        create_route = self._route("/platform/teams/{team_id}/flows", "POST")
        list_route = self._route("/platform/teams/{team_id}/flows", "GET")

        created = create_route.endpoint(
            self.team_id,
            {"name": "企微代开发应用上线", "description": "简道云 Webhook 触发"},
        )
        flows = list_route.endpoint(self.team_id)

        self.assertEqual(create_route.status_code, 201)
        self.assertEqual(created["name"], "企微代开发应用上线")
        self.assertTrue(any(flow["id"] == created["id"] for flow in flows["items"]))

    def test_creates_draft_version_and_publishes_it(self):
        create_flow = self._route("/platform/teams/{team_id}/flows", "POST").endpoint
        flow = create_flow(self.team_id, {"name": "企微代开发应用上线", "description": ""})
        draft_route = self._route("/platform/flows/{flow_id}/versions/draft", "POST")
        publish_route = self._route("/platform/flows/{flow_id}/versions/{version_id}/publish", "POST")

        draft = draft_route.endpoint(
            flow["id"],
            {
                "steps": [
                    {"key": "open_jdy", "name": "打开简道云后台", "action": "open_url"},
                    {"key": "derive_urls", "name": "生成 URL", "action": "derive_urls"},
                ],
                "created_by": "admin",
            },
        )
        published = publish_route.endpoint(flow["id"], draft["id"])

        self.assertEqual(draft_route.status_code, 201)
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(published["published_version_id"], draft["id"])

    def test_rejects_invalid_step_json_from_route(self):
        create_flow = self._route("/platform/teams/{team_id}/flows", "POST").endpoint
        flow = create_flow(self.team_id, {"name": "企微代开发应用上线", "description": ""})
        draft_route = self._route("/platform/flows/{flow_id}/versions/draft", "POST")

        with self.assertRaises(HTTPException) as ctx:
            draft_route.endpoint(flow["id"], {"steps": [{"key": "bad", "name": "缺动作"}]})

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("action", ctx.exception.detail)

    def test_copies_and_rolls_back_versions(self):
        flow_id = self.default_flow_id
        draft_route = self._route("/platform/flows/{flow_id}/versions/draft", "POST")
        publish_route = self._route("/platform/flows/{flow_id}/versions/{version_id}/publish", "POST")
        copy_route = self._route("/platform/flows/{flow_id}/versions/{version_id}/copy", "POST")
        rollback_route = self._route("/platform/flows/{flow_id}/versions/{version_id}/rollback", "POST")

        first_published_id = self.store.get_flow_template(flow_id)["published_version_id"]
        draft_v2 = draft_route.endpoint(
            flow_id,
            {"steps": [{"key": "v2", "name": "第二版", "action": "click"}], "created_by": "admin"},
        )
        publish_route.endpoint(flow_id, draft_v2["id"])
        copied = copy_route.endpoint(flow_id, first_published_id, {"created_by": "admin"})
        rolled_back = rollback_route.endpoint(flow_id, first_published_id)

        self.assertEqual(copied["status"], "draft")
        self.assertEqual(copied["version_no"], 3)
        self.assertEqual(rolled_back["published_version_id"], first_published_id)

    def _route(self, path, method):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route
        raise AssertionError("Route not found: %s %s" % (method, path))


if __name__ == "__main__":
    unittest.main()
