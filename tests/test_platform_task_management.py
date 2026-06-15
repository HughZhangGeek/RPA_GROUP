import json
import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.storage.sqlite_store import SQLiteStore


class TaskManagementStoreTest(unittest.TestCase):
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
        self.task_id = self._create_task()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_task_detail_includes_snapshot_steps_logs_artifacts_and_manual_actions(self):
        step_id = self.store.append_task_step(
            self.task_id,
            "login_check",
            "检查后台登录态",
            "failed",
            output_data={"missing_targets": ["wecom"]},
        )
        artifact_id = self.store.create_task_artifact(
            task_id=self.task_id,
            step_id=step_id,
            artifact_type="screenshot",
            path="screenshots/login.png",
            metadata={"source": "login_check"},
        )
        action_id = self.store.create_manual_action(
            task_id=self.task_id,
            action_type="waiting_login",
            reason="企微后台需要扫码登录",
            candidates=[],
        )

        detail = self.store.get_task_detail(self.task_id)

        self.assertEqual(detail["id"], self.task_id)
        self.assertEqual(detail["enterprise_name"], "上海测试客户")
        self.assertEqual(detail["corp_id_masked"], "ww0***001")
        self.assertEqual(detail["flow_version_snapshot"]["steps"][0]["key"], "receive_webhook")
        self.assertEqual(detail["steps"][0]["step_key"], "login_check")
        self.assertEqual(detail["artifacts"][0]["id"], artifact_id)
        self.assertEqual(detail["manual_actions"][0]["id"], action_id)

    def test_resume_waiting_login_moves_task_to_checking_login_and_closes_action(self):
        self.store.set_task_status(self.task_id, TaskStatus.WAITING_LOGIN)
        action_id = self.store.create_manual_action(
            task_id=self.task_id,
            action_type="waiting_login",
            reason="企微后台需要扫码登录",
            candidates=[],
        )

        result = self.store.resume_task(
            self.task_id,
            handled_by="admin",
            note="扫码完成",
        )

        task = self.store.get_task(self.task_id)
        action = self.store.get_manual_action(action_id)
        self.assertEqual(result["status"], TaskStatus.CHECKING_LOGIN.value)
        self.assertEqual(task["status"], TaskStatus.CHECKING_LOGIN.value)
        self.assertEqual(action["status"], "resolved")
        self.assertEqual(action["handled_by"], "admin")

    def test_resume_manual_selection_saves_candidate_and_moves_to_running(self):
        self.store.set_task_status(self.task_id, TaskStatus.WAITING_MANUAL_SELECTION)
        action_id = self.store.create_manual_action(
            task_id=self.task_id,
            action_type="waiting_manual_selection",
            reason="企微客户名称命中多条",
            candidates=[{"id": "row-1", "name": "上海测试客户"}],
        )

        result = self.store.resume_task(
            self.task_id,
            handled_by="admin",
            selected_candidate={"id": "row-1", "name": "上海测试客户"},
        )

        action = self.store.get_manual_action(action_id)
        self.assertEqual(result["status"], TaskStatus.RUNNING.value)
        self.assertEqual(json.loads(action["selected_candidate_json"])["id"], "row-1")

    def test_resume_rejects_non_waiting_task(self):
        with self.assertRaises(ValueError):
            self.store.resume_task(self.task_id, handled_by="admin")

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


if __name__ == "__main__":
    unittest.main()
