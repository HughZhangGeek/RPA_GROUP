import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from rpa_platform.server.app import create_app
from rpa_platform.storage.sqlite_store import SQLiteStore


class PlatformAppTest(unittest.TestCase):
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
        self.app = create_app(self.store, self.team_id, self.flow_id)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_health_check_is_namespaced_for_new_platform(self):
        route = self._route("/platform/healthz", "GET")

        self.assertEqual(route.status_code, 200)
        self.assertEqual(route.endpoint(), {"status": "ok", "service": "rpa_platform"})

    def test_jdy_webhook_endpoint_accepts_task_and_reports_idempotency(self):
        payload = {
            "user_id": "u001",
            "企业客户名称": "上海测试客户",
            "企业微信明文 CorpID": "wwabc123",
        }

        route = self._route("/platform/webhooks/jdy/wecom-app-launch", "POST")
        first = route.endpoint(payload)
        second = route.endpoint(payload)

        self.assertEqual(route.status_code, 202)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["task_id"], second["task_id"])

    def test_jdy_webhook_endpoint_rejects_missing_required_field(self):
        route = self._route("/platform/webhooks/jdy/wecom-app-launch", "POST")

        with self.assertRaises(HTTPException) as ctx:
            route.endpoint({"user_id": "u001", "企业客户名称": "上海测试客户"})
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("企业微信明文 CorpID", ctx.exception.detail)

    def _route(self, path, method):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route
        raise AssertionError(f"Route not found: {method} {path}")


if __name__ == "__main__":
    unittest.main()
