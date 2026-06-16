from datetime import datetime, timedelta
import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.domain.default_flows import WECOM_APP_LAUNCH_FLOW_STEPS
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyAdminTransport
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.hybrid_runner import HybridFlowRunner
from rpa_platform.worker.robot_registry import RobotRegistry
from rpa_platform.worker.runner import FakeRunner
from rpa_platform.worker.scheduler import TaskScheduler
from rpa_platform.worker.wecom_rpa import FakeWecomRpa


class FakeTransport(JdyAdminTransport):
    def __init__(self, responses):
        self.responses = list(responses)

    def post_json(self, path, payload):
        return self.responses.pop(0)


class WorkerSchedulerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(self.team_id, "企微代开发应用上线", "")
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[
                {"key": "receive_webhook", "name": "接收 Webhook", "action": "receive_webhook"},
                {"key": "open_jdy", "name": "打开简道云后台", "action": "open_url"},
            ],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, version_id)
        self.registry = RobotRegistry(self.store)
        self.robot_id = self.registry.register_robot(
            name="windows-rpa-01",
            host="WIN-RPA-01",
            browser_profile_path="C:/rpa/chrome-profile",
        )
        self.scheduler = TaskScheduler(self.store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_register_robot_persists_idle_robot_with_profile(self):
        robot = self.store.get_robot(self.robot_id)

        self.assertEqual(robot["status"], "idle")
        self.assertEqual(robot["browser_profile_path"], "C:/rpa/chrome-profile")
        self.assertTrue(robot["last_heartbeat_at"])

    def test_claims_pending_task_and_marks_robot_busy(self):
        task_id = self._create_task("ww001", "u001")

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:00:00"))

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], task_id)
        task = self.store.get_task(task_id)
        robot = self.store.get_robot(self.robot_id)
        self.assertEqual(task["status"], TaskStatus.CHECKING_LOGIN.value)
        self.assertEqual(task["assigned_robot_id"], self.robot_id)
        self.assertEqual(robot["status"], "busy")

    def test_does_not_claim_another_task_while_robot_busy(self):
        self._create_task("ww001", "u001")
        self._create_task("ww002", "u002")
        self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:00:00"))

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:01:00"))

        self.assertIsNone(claimed)

    def test_claims_due_wecom_review_task_and_increments_attempts(self):
        task_id = self._create_task("ww001", "u001")
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_REVIEW,
            next_check_at="2026-06-08 09:58:00",
            check_attempts=2,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:00:00"))

        self.assertEqual(claimed["id"], task_id)
        task = self.store.get_task(task_id)
        self.assertEqual(task["status"], TaskStatus.CHECKING_LOGIN.value)
        self.assertEqual(task["check_attempts"], 3)

    def test_skips_wecom_review_task_before_next_check_time(self):
        task_id = self._create_task("ww001", "u001")
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_REVIEW,
            next_check_at="2026-06-08 10:05:00",
            check_attempts=2,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:00:00"))

        self.assertIsNone(claimed)
        self.assertEqual(self.store.get_task(task_id)["status"], TaskStatus.WAITING_WECOM_REVIEW.value)

    def test_skips_wecom_review_task_when_next_check_time_is_empty(self):
        task_id = self._create_task("ww001", "u001")
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_REVIEW,
            next_check_at="",
            check_attempts=2,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:00:00"))

        self.assertIsNone(claimed)
        self.assertEqual(self.store.get_task(task_id)["status"], TaskStatus.WAITING_WECOM_REVIEW.value)

    def test_claims_due_wecom_online_delay_task_and_increments_attempts(self):
        task_id = self._create_task("ww001", "u001")
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at="2026-06-08 10:05:00",
            check_attempts=1,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:06:00"))

        self.assertEqual(claimed["id"], task_id)
        task = self.store.get_task(task_id)
        self.assertEqual(task["status"], TaskStatus.CHECKING_LOGIN.value)
        self.assertEqual(task["check_attempts"], 2)

    def test_skips_wecom_online_delay_task_before_next_check_time(self):
        task_id = self._create_task("ww001", "u001")
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at="2026-06-08 10:05:00",
            check_attempts=1,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:04:00"))

        self.assertIsNone(claimed)
        self.assertEqual(self.store.get_task(task_id)["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)

    def test_skips_wecom_online_delay_task_when_next_check_time_is_empty(self):
        task_id = self._create_task("ww001", "u001")
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at="",
            check_attempts=1,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:00:00"))

        self.assertIsNone(claimed)
        self.assertEqual(self.store.get_task(task_id)["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)

    def test_claims_jdy_callback_failed_before_due_wecom_online_delay(self):
        online_delay_task_id = self._create_task("ww001", "u001")
        jdy_callback_failed_task_id = self._create_task("ww002", "u002")
        self.store.set_task_status(
            online_delay_task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at="2026-06-08 09:58:00",
            check_attempts=1,
            assigned_robot_id=None,
        )
        self.store.set_task_status(
            jdy_callback_failed_task_id,
            TaskStatus.JDY_CALLBACK_FAILED,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:00:00"))

        self.assertEqual(claimed["id"], jdy_callback_failed_task_id)

    def test_fake_runner_marks_claimed_task_running_and_releases_robot(self):
        task_id = self._create_task("ww001", "u001")
        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-08 10:00:00"))

        result = FakeRunner(self.store).run_claimed_task(claimed["id"], self.robot_id)

        task = self.store.get_task(task_id)
        robot = self.store.get_robot(self.robot_id)
        steps = self.store.list_task_steps(task_id)
        self.assertEqual(result["status"], "runner_stubbed")
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(robot["status"], "idle")
        self.assertEqual(steps[0]["step_key"], "worker_stub")

    def test_run_once_claims_task_and_executes_hybrid_runner(self):
        flow_id = self.store.create_flow_template(self.team_id, "企微代开发应用上线 hybrid", "")
        version_id = self.store.create_flow_version(
            flow_id,
            steps=WECOM_APP_LAUNCH_FLOW_STEPS,
            created_by="codex",
        )
        self.store.publish_flow_version(flow_id, version_id)
        task_id = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=flow_id,
            enterprise_name="上海测试客户",
            corp_id="ww001",
            source_user_id="u001",
            idempotency_key="wecom_app_launch:hybrid:ww001:u001",
            payload={"user_id": "u001", "企业客户名称": "上海测试客户", "企业微信明文 CorpID": "ww001"},
        ).task_id
        runner = HybridFlowRunner(
            store=self.store,
            jdy_client=JdyAdminClient(
                FakeTransport(
                    [
                        {
                            "has_more": False,
                            "corp_deploy_list": [
                                {
                                    "corp_id": "corp-secret",
                                    "name": "上海测试客户",
                                    "tenant_id": "",
                                    "suite_name": "简道云",
                                    "integrate_suite_name": "简道云",
                                    "suite_id": 1,
                                    "suite_scenario": "main",
                                }
                            ],
                        },
                        {"can_bind_corp_secret": True},
                        {"tenant_id": "u001", "owner_id": "u001"},
                    ]
                )
            ),
            wecom_rpa=FakeWecomRpa(),
        )

        result = self.scheduler.run_once(self.robot_id, runner, now=self._dt("2026-06-08 10:00:00"))

        task = self.store.get_task(task_id)
        step_keys = [step["step_key"] for step in self.store.list_task_steps(task_id)]
        self.assertTrue(result["claimed"])
        self.assertEqual(result["task_id"], task_id)
        self.assertEqual(result["runner_result"]["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(task["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(task["current_step_key"], "wecom_submit_review")
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")
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

    def _create_task(self, corp_id, user_id):
        result = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="上海测试客户",
            corp_id=corp_id,
            source_user_id=user_id,
            idempotency_key="wecom_app_launch:%s:%s" % (corp_id, user_id),
            payload={"user_id": user_id, "企业客户名称": "上海测试客户", "企业微信明文 CorpID": corp_id},
        )
        return result.task_id

    @staticmethod
    def _dt(value):
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    unittest.main()
