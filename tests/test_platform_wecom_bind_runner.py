from datetime import datetime
import json
import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient
from rpa_platform.integrations.wecom_admin_client import RetryableWecomOrderError, WecomAdminClient
from rpa_platform.services.wecom_bind_service import FixedWecomSecretGenerator, JdyWecomBindService
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.scheduler import TaskScheduler
from rpa_platform.worker.wecom_bind_runner import WecomBindServiceRunner
from tests.test_platform_wecom_bind_service import FakeJdyTransport, FakeWecomTransport


class RetryableOrderWecomTransport(FakeWecomTransport):
    def post_json(self, path, payload, headers):
        if path == "/wwopen/developer/order/set":
            raise RetryableWecomOrderError("当前状态暂不允许上线")
        return super().post_json(path, payload, headers)


class FailingStartBindService:
    def start_bind(self, request, now=None):
        raise RuntimeError("start bind exploded")

    def submit_online_order(self, context):
        raise AssertionError("submit_online_order should not run")


class WecomBindServiceRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(self.team_id, "企微绑定服务流", "")
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[
                {
                    "key": "jdy_wecom_bind_service",
                    "name": "企微绑定接口服务",
                    "action": "jdy_wecom_bind_service",
                }
            ],
            created_by="worker-test",
        )
        self.store.publish_flow_version(self.flow_id, version_id)
        self.task_id = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="上海测试客户",
            corp_id="ww001",
            source_user_id="user-1",
            idempotency_key="wecom-bind:ww001:user-1",
            payload={"user_id": "user-1", "企业客户名称": "上海测试客户", "企业微信明文 CorpID": "ww001"},
        ).task_id
        self.robot_id = self.store.register_robot(
            name="windows-rpa-01",
            host="WIN-RPA-01",
            browser_profile_path="C:/rpa/chrome-profile",
        )
        self.call_log = []

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_start_bind_moves_task_to_online_delay_and_releases_robot(self):
        runner = self._make_runner()

        result = runner.run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 0, 0),
        )

        task = self.store.get_task(self.task_id)
        context = self.store.get_task_context(self.task_id)
        steps = self.store.list_task_steps(self.task_id)
        self.assertEqual(result, {"task_id": self.task_id, "status": TaskStatus.WAITING_WECOM_ONLINE_DELAY.value})
        self.assertEqual(task["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(task["next_check_at"], "2026-06-16 10:05:00")
        self.assertIsNone(task["assigned_robot_id"])
        self.assertEqual(task["current_step_key"], "jdy_wecom_bind_service")
        self.assertEqual(context["wecom"]["auditorderid"], "order-1")
        self.assertEqual(steps[-1]["step_key"], "jdy_wecom_bind_service")
        self.assertEqual(steps[-1]["status"], "success")
        output = json.loads(steps[-1]["output_json"])
        self.assertEqual(output["wecom"]["auditorderid"], "order-1")
        self.assertEqual(output["wecom"]["token"], "***")
        self.assertEqual(output["wecom"]["encoding_aes_key"], "***")
        self.assertNotIn("token-secret", steps[-1]["output_json"])
        self.assertNotIn("aes-secret", steps[-1]["output_json"])
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")

    def test_online_delay_resume_submits_order_and_marks_success(self):
        runner = self._make_runner()
        runner.run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 0, 0),
        )
        self.store.set_task_status(
            self.task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            assigned_robot_id=None,
        )

        result = runner.run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 5, 0),
        )

        task = self.store.get_task(self.task_id)
        context = self.store.get_task_context(self.task_id)
        steps = self.store.list_task_steps(self.task_id)
        self.assertEqual(result, {"task_id": self.task_id, "status": TaskStatus.SUCCESS.value})
        self.assertEqual(task["status"], TaskStatus.SUCCESS.value)
        self.assertIsNone(task["assigned_robot_id"])
        self.assertEqual(context["wecom"]["auditorder_status"], 5)
        self.assertEqual(steps[-1]["step_key"], "wecom_submit_online_order")
        self.assertEqual(steps[-1]["status"], "success")
        self.assertNotIn("token-secret", steps[-1]["output_json"])
        self.assertNotIn("aes-secret", steps[-1]["output_json"])
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")

    def test_scheduler_claimed_online_delay_submits_order_without_restarting_bind(self):
        runner = self._make_runner()
        runner.run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 0, 0),
        )
        initial_resolve_calls = self._count_calls("/api/fx_sa/wxwork/get_corp_deploy_list")
        self.store.set_task_status(
            self.task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at="2026-06-16 10:05:00",
            assigned_robot_id=None,
        )

        claimed = TaskScheduler(self.store).claim_next_task(
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 5, 1),
        )
        self.assertEqual(claimed["id"], self.task_id)
        self.assertEqual(self.store.get_task(self.task_id)["status"], TaskStatus.CHECKING_LOGIN.value)
        result = runner.run_claimed_task(
            claimed["id"],
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 5, 1),
        )

        self.assertEqual(result, {"task_id": self.task_id, "status": TaskStatus.SUCCESS.value})
        self.assertEqual(self.store.get_task(self.task_id)["status"], TaskStatus.SUCCESS.value)
        self.assertEqual(self._count_calls("/wwopen/developer/order/set"), 1)
        self.assertEqual(self._count_calls("/api/fx_sa/wxwork/get_corp_deploy_list"), initial_resolve_calls)

    def test_retryable_online_submit_keeps_online_delay_for_two_minutes(self):
        runner = self._make_runner(wecom_transport=RetryableOrderWecomTransport(self.call_log))
        runner.run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 0, 0),
        )
        self.store.set_task_status(
            self.task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            assigned_robot_id=None,
        )

        result = runner.run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 5, 1),
        )

        task = self.store.get_task(self.task_id)
        steps = self.store.list_task_steps(self.task_id)
        output = json.loads(steps[-1]["output_json"])
        self.assertEqual(result, {"task_id": self.task_id, "status": TaskStatus.WAITING_WECOM_ONLINE_DELAY.value})
        self.assertEqual(task["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(task["next_check_at"], "2026-06-16 10:07:01")
        self.assertIsNone(task["assigned_robot_id"])
        self.assertEqual(steps[-1]["step_key"], "wecom_submit_online_order")
        self.assertEqual(steps[-1]["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(output["error_type"], "retryable_wecom_order")
        self.assertEqual(output["error_detail"], "当前状态暂不允许上线")
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")

    def test_non_retryable_start_bind_error_marks_task_failed_and_releases_robot(self):
        runner = WecomBindServiceRunner(self.store, FailingStartBindService())

        with self.assertRaises(RuntimeError):
            runner.run_claimed_task(
                self.task_id,
                self.robot_id,
                now=datetime(2026, 6, 16, 10, 0, 0),
            )

        task = self.store.get_task(self.task_id)
        steps = self.store.list_task_steps(self.task_id)
        output = json.loads(steps[-1]["output_json"])
        self.assertEqual(task["status"], TaskStatus.FAILED.value)
        self.assertIsNone(task["assigned_robot_id"])
        self.assertEqual(task["current_step_key"], "jdy_wecom_bind_service")
        self.assertEqual(steps[-1]["step_key"], "jdy_wecom_bind_service")
        self.assertEqual(steps[-1]["status"], "failed")
        self.assertEqual(output["error_type"], "RuntimeError")
        self.assertEqual(output["error_detail"], "start bind exploded")
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")

    def _make_runner(self, wecom_transport=None):
        service = JdyWecomBindService(
            jdy_client=JdyAdminClient(FakeJdyTransport(self.call_log)),
            wecom_client=WecomAdminClient(wecom_transport or FakeWecomTransport(self.call_log)),
            secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
        )
        return WecomBindServiceRunner(self.store, service)

    def _count_calls(self, path):
        return len([call for call in self.call_log if call["path"] == path])


if __name__ == "__main__":
    unittest.main()
