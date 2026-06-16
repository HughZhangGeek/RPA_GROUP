import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.server.app import create_app
from rpa_platform.storage.sqlite_store import SQLiteStore


class TaskRoutesTest(unittest.TestCase):
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
        self.task_id = self._create_task()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_get_task_detail_route_returns_admin_context(self):
        self.store.append_task_step(self.task_id, "login_check", "检查后台登录态", "failed")
        route = self._route("/platform/tasks/{task_id}", "GET")

        detail = route.endpoint(self.task_id)

        self.assertEqual(detail["id"], self.task_id)
        self.assertEqual(detail["corp_id_masked"], "ww0***001")
        self.assertEqual(detail["steps"][0]["step_key"], "login_check")

    def test_create_manual_action_route_sets_task_waiting_state(self):
        route = self._route("/platform/tasks/{task_id}/manual-actions", "POST")

        action = route.endpoint(
            self.task_id,
            {
                "action_type": "waiting_manual_selection",
                "reason": "企微客户名称命中多条",
                "candidates": [{"id": "row-1", "name": "上海测试客户"}],
                "artifact": {
                    "artifact_type": "screenshot",
                    "path": "screenshots/ambiguous.png",
                    "metadata": {"source": "wecom_search"},
                },
            },
        )

        task = self.store.get_task(self.task_id)
        detail = self.store.get_task_detail(self.task_id)
        self.assertEqual(route.status_code, 201)
        self.assertEqual(action["status"], "pending")
        self.assertEqual(task["status"], TaskStatus.WAITING_MANUAL_SELECTION.value)
        self.assertEqual(detail["artifacts"][0]["path"], "screenshots/ambiguous.png")

    def test_resume_route_returns_new_status(self):
        self.store.set_task_status(self.task_id, TaskStatus.WAITING_LOGIN)
        self.store.create_manual_action(
            task_id=self.task_id,
            action_type="waiting_login",
            reason="企微后台需要扫码登录",
            candidates=[],
        )
        route = self._route("/platform/tasks/{task_id}/resume", "POST")

        result = route.endpoint(self.task_id, {"handled_by": "admin", "note": "扫码完成"})

        self.assertEqual(result["status"], TaskStatus.CHECKING_LOGIN.value)
        self.assertEqual(result["task_id"], self.task_id)

    def test_resume_route_rejects_non_waiting_task(self):
        route = self._route("/platform/tasks/{task_id}/resume", "POST")

        with self.assertRaises(HTTPException) as ctx:
            route.endpoint(self.task_id, {"handled_by": "admin"})

        self.assertEqual(ctx.exception.status_code, 409)

    def _create_task(self):
        created = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="上海测试客户",
            corp_id="ww001",
            source_user_id="u001",
            idempotency_key="wecom_app_launch:ww001:u001",
            payload={"user_id": "u001", "企业客户名称": "上海测试客户", "企业微信明文 CorpID": "ww001"},
        )
        return created.task_id

    def _route(self, path, method):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route
        raise AssertionError("Route not found: %s %s" % (method, path))


if __name__ == "__main__":
    unittest.main()
