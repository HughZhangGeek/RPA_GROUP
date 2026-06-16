import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.browser_profile import BrowserProfileConfig, BrowserProfileConfigError
from rpa_platform.worker.login_health import LoginCheckResult, LoginHealthChecker, StaticLoginProbe
from rpa_platform.worker.robot_registry import RobotRegistry
from rpa_platform.worker.runner import FakeRunner
from rpa_platform.worker.scheduler import TaskScheduler


class LoginHealthTest(unittest.TestCase):
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
        self.profile = BrowserProfileConfig(
            browser_type="edge",
            profile_path="C:/rpa/edge-profile",
            jdy_entry_url="https://www.jiandaoyun.com/dashboard",
            wecom_entry_url="https://work.weixin.qq.com/wework_admin",
        )
        self.robot_id = RobotRegistry(self.store).register_robot(
            name="windows-rpa-01",
            host="WIN-RPA-01",
            browser_profile=self.profile,
        )
        self.scheduler = TaskScheduler(self.store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_browser_profile_config_rejects_missing_entry_url(self):
        with self.assertRaises(BrowserProfileConfigError) as ctx:
            BrowserProfileConfig(
                browser_type="edge",
                profile_path="C:/rpa/edge-profile",
                jdy_entry_url="",
                wecom_entry_url="https://work.weixin.qq.com/wework_admin",
            )

        self.assertIn("jdy_entry_url", str(ctx.exception))

    def test_robot_registration_persists_browser_profile_capabilities(self):
        robot = self.store.get_robot(self.robot_id)

        capabilities = self.store.get_robot_capabilities(self.robot_id)
        self.assertEqual(robot["browser_profile_path"], "C:/rpa/edge-profile")
        self.assertEqual(capabilities["browser_type"], "edge")
        self.assertEqual(capabilities["entry_urls"]["jdy"], "https://www.jiandaoyun.com/dashboard")
        self.assertEqual(capabilities["entry_urls"]["wecom"], "https://work.weixin.qq.com/wework_admin")

    def test_login_health_checker_moves_task_to_running_when_all_targets_are_healthy(self):
        task_id = self._create_and_claim_task()
        checker = LoginHealthChecker(
            self.store,
            StaticLoginProbe(
                {
                    "jdy": LoginCheckResult(True, "already logged in"),
                    "wecom": LoginCheckResult(True, "already logged in"),
                }
            ),
        )

        result = checker.check_task_login(task_id, self.robot_id)

        task = self.store.get_task(task_id)
        steps = self.store.list_task_steps(task_id)
        self.assertEqual(result.status, TaskStatus.RUNNING)
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(steps[-1]["step_key"], "login_check")
        self.assertEqual(steps[-1]["status"], "success")

    def test_login_health_checker_waits_for_login_and_releases_robot_when_wecom_is_missing(self):
        task_id = self._create_and_claim_task()
        checker = LoginHealthChecker(
            self.store,
            StaticLoginProbe(
                {
                    "jdy": LoginCheckResult(True, "already logged in"),
                    "wecom": LoginCheckResult(False, "qr code required"),
                }
            ),
        )

        result = checker.check_task_login(task_id, self.robot_id)

        task = self.store.get_task(task_id)
        robot = self.store.get_robot(self.robot_id)
        steps = self.store.list_task_steps(task_id)
        self.assertEqual(result.status, TaskStatus.WAITING_LOGIN)
        self.assertEqual(result.missing_targets, ["wecom"])
        self.assertEqual(task["status"], TaskStatus.WAITING_LOGIN.value)
        self.assertIsNone(task["assigned_robot_id"])
        self.assertEqual(robot["status"], "idle")
        self.assertEqual(steps[-1]["status"], "failed")

    def test_fake_runner_uses_login_checker_before_stub_execution(self):
        task_id = self._create_and_claim_task()
        checker = LoginHealthChecker(
            self.store,
            StaticLoginProbe(
                {
                    "jdy": LoginCheckResult(True, "already logged in"),
                    "wecom": LoginCheckResult(False, "qr code required"),
                }
            ),
        )

        result = FakeRunner(self.store, login_checker=checker).run_claimed_task(task_id, self.robot_id)

        self.assertEqual(result["status"], "waiting_login")
        self.assertEqual(self.store.get_task(task_id)["status"], TaskStatus.WAITING_LOGIN.value)

    def _create_and_claim_task(self):
        created = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="上海测试客户",
            corp_id="ww001",
            source_user_id="u001",
            idempotency_key="wecom_app_launch:ww001:u001",
            payload={"user_id": "u001", "企业客户名称": "上海测试客户", "企业微信明文 CorpID": "ww001"},
        )
        self.scheduler.claim_next_task(created.task_id and self.robot_id)
        return created.task_id


if __name__ == "__main__":
    unittest.main()
