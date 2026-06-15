from datetime import datetime
import json
import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyAdminTransport
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.hybrid_runner import HybridFlowRunner
from rpa_platform.worker.wecom_rpa import FakeWecomRpa, WecomReviewStatus


class FakeTransport(JdyAdminTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, path, payload):
        self.calls.append({"path": path, "payload": payload})
        return self.responses.pop(0)


class HybridFlowRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(self.team_id, "企微代开发应用上线", "")
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[
                {"key": "jdy_resolve_corp", "name": "简道云查找绑定企业", "action": "jdy_resolve_corp"},
                {"key": "derive_wecom_urls", "name": "生成企微配置 URL", "action": "derive_wecom_urls"},
                {"key": "wecom_configure_app", "name": "企微页面配置代开发应用", "action": "wecom_configure_app"},
                {"key": "jdy_check_owner", "name": "简道云校验绑定 User_ID", "action": "jdy_check_owner"},
                {"key": "jdy_install_bind", "name": "简道云提交企业微信绑定", "action": "jdy_install_bind"},
                {"key": "wecom_submit_review", "name": "企微提交上线进入审核", "action": "wecom_submit_review"},
                {"key": "wecom_wait_review", "name": "等待企微审核通过", "action": "wecom_wait_review"},
                {"key": "wecom_submit_online", "name": "企微待上线后提交上线", "action": "wecom_submit_online"},
            ],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, version_id)
        self.task_id = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="安徽云速付",
            corp_id="ww-demo",
            source_user_id="user-1",
            idempotency_key="wecom_app_launch:ww-demo:user-1",
            payload={"user_id": "user-1", "企业客户名称": "安徽云速付", "企业微信明文 CorpID": "ww-demo"},
        ).task_id
        self.robot_id = self.store.register_robot(
            name="windows-rpa-01",
            host="WIN-RPA-01",
            browser_profile_path="C:/rpa/chrome-profile",
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_runner_reaches_waiting_review_after_jdy_bind_and_wecom_review_submit(self):
        transport = FakeTransport(
            [
                {
                    "has_more": False,
                    "corp_deploy_list": [
                        {
                            "corp_id": "corp-secret",
                            "name": "安徽云速付",
                            "tenant_id": "",
                            "suite_name": "简道云",
                            "integrate_suite_name": "简道云",
                            "suite_id": 1,
                            "suite_scenario": "main",
                        }
                    ],
                },
                {"can_bind_corp_secret": True},
                {"tenant_id": "user-1", "owner_id": "user-1"},
            ]
        )
        runner = HybridFlowRunner(
            store=self.store,
            jdy_client=JdyAdminClient(transport),
            wecom_rpa=FakeWecomRpa(),
        )

        result = runner.run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 8, 10, 0, 0),
        )

        task = self.store.get_task(self.task_id)
        context = self.store.get_task_context(self.task_id)
        step_keys = [step["step_key"] for step in self.store.list_task_steps(self.task_id)]
        install_payload = transport.calls[-1]["payload"]

        self.assertEqual(result["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(task["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(task["assigned_robot_id"], None)
        self.assertEqual(task["next_check_at"], "2026-06-08 10:10:00")
        self.assertEqual(task["current_step_key"], "wecom_submit_review")
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")
        self.assertEqual(context["jdy"]["corp_secret_id"], "corp-secret")
        self.assertEqual(context["jdy"]["install_owner_id"], "user-1")
        self.assertEqual(context["wecom"]["homeurl"], "https://wxwork.jiandaoyun.com/wxwork/corp-secret/dashboard")
        self.assertEqual(context["wecom"]["callbackurl"], "https://wxwork.jiandaoyun.com/wxwork/corp/corp-secret/service")
        self.assertEqual(context["wecom"]["token"], "fake-token")
        self.assertEqual(context["wecom"]["encoding_aes_key"], "fake-aes-key")
        self.assertEqual(install_payload["tenant_id"], "user-1")
        self.assertEqual(install_payload["token"], "fake-token")
        self.assertEqual(
            step_keys,
            [
                "jdy_resolve_corp",
                "derive_wecom_urls",
                "wecom_configure_app",
                "jdy_check_owner",
                "jdy_install_bind",
                "wecom_submit_review",
            ],
        )
        self.assertEqual(json.loads(self.store.list_task_steps(self.task_id)[2]["output_json"])["review_status"], "审核中")

    def test_reviewing_status_keeps_waiting_review_with_next_check(self):
        self.store.set_task_status(self.task_id, TaskStatus.WAITING_WECOM_REVIEW)
        self.store.merge_task_context(self.task_id, {"wecom": {"review_status": "审核中"}})
        runner = HybridFlowRunner(
            store=self.store,
            jdy_client=JdyAdminClient(FakeTransport([])),
            wecom_rpa=FakeWecomRpa(review_statuses=[WecomReviewStatus.REVIEWING]),
        )

        result = runner.run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 8, 10, 0, 0),
        )

        task = self.store.get_task(self.task_id)
        steps = self.store.list_task_steps(self.task_id)
        self.assertEqual(result["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(task["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(task["next_check_at"], "2026-06-08 10:10:00")
        self.assertEqual(task["assigned_robot_id"], None)
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")
        self.assertEqual(steps[-1]["step_key"], "wecom_wait_review")
        self.assertEqual(json.loads(steps[-1]["output_json"])["review_status"], "审核中")

    def test_ready_to_online_status_then_submit_online_marks_success(self):
        self.store.set_task_status(self.task_id, TaskStatus.READY_TO_ONLINE)
        runner = HybridFlowRunner(
            store=self.store,
            jdy_client=JdyAdminClient(FakeTransport([])),
            wecom_rpa=FakeWecomRpa(review_statuses=[WecomReviewStatus.READY_TO_ONLINE]),
        )

        result = runner.run_claimed_task(self.task_id, self.robot_id)

        task = self.store.get_task(self.task_id)
        steps = self.store.list_task_steps(self.task_id)
        self.assertEqual(result["status"], TaskStatus.SUCCESS.value)
        self.assertEqual(task["status"], TaskStatus.SUCCESS.value)
        self.assertEqual(task["assigned_robot_id"], None)
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")
        self.assertEqual(steps[-1]["step_key"], "wecom_submit_online")
        self.assertEqual(json.loads(steps[-1]["output_json"])["review_status"], "已上线")

    def test_needs_login_from_wecom_browser_task_moves_to_waiting_login(self):
        transport = FakeTransport(
            [
                {
                    "has_more": False,
                    "corp_deploy_list": [
                        {
                            "corp_id": "corp-secret",
                            "name": "安徽云速付",
                            "tenant_id": "",
                            "suite_name": "简道云",
                            "integrate_suite_name": "简道云",
                            "suite_id": 1,
                            "suite_scenario": "main",
                        }
                    ],
                },
            ]
        )
        runner = HybridFlowRunner(
            store=self.store,
            jdy_client=JdyAdminClient(transport),
            wecom_rpa=NeedsLoginWecomRpa(),
        )

        result = runner.run_claimed_task(self.task_id, self.robot_id)

        task = self.store.get_task(self.task_id)
        actions = self.store.list_manual_actions(self.task_id)
        self.assertEqual(result["status"], TaskStatus.WAITING_LOGIN.value)
        self.assertEqual(task["status"], TaskStatus.WAITING_LOGIN.value)
        self.assertEqual(task["assigned_robot_id"], None)
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")
        self.assertEqual(actions[0]["action_type"], "waiting_login")
        self.assertIn("企微后台需要扫码登录", actions[0]["reason"])


class NeedsLoginWecomRpa:
    def configure_custom_app(self, task, context):
        return {"status": "needs_login", "target": "wecom", "reason": "企微后台需要扫码登录"}

    def submit_review(self, task, context):
        raise AssertionError("submit_review should not run when login is missing")

    def check_review_status(self, task, context):
        raise AssertionError("check_review_status should not run when login is missing")

    def submit_online(self, task, context):
        raise AssertionError("submit_online should not run when login is missing")


if __name__ == "__main__":
    unittest.main()
