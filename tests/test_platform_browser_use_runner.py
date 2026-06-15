import unittest

from rpa_platform.worker.browser_use_runner import LocalBrowserUseRunner
from rpa_platform.worker.wecom_rpa import BrowserUseTaskRequest


class FakeAgent:
    def __init__(self, result):
        self.result = result
        self.run_count = 0

    def run(self):
        self.run_count += 1
        return self.result


class FakeHistory:
    def __init__(self, final_result):
        self._final_result = final_result

    def final_result(self):
        return self._final_result


class LocalBrowserUseRunnerTest(unittest.TestCase):
    def test_converts_request_to_agent_task_with_local_constraints(self):
        captured = []

        def agent_factory(agent_task):
            captured.append(agent_task)
            return FakeAgent({"status": "success", "page_state": "configured"})

        runner = LocalBrowserUseRunner(agent_factory=agent_factory)

        result = runner.run_task(
            BrowserUseTaskRequest(
                task_template="wecom_configure_app_v1",
                prompt="配置企业「安徽云速付」的代开发应用",
                allowed_domains=["open.work.weixin.qq.com"],
                browser_profile="wecom_admin",
            )
        )

        agent_task = captured[0]
        self.assertEqual(result["status"], "success")
        self.assertIn("安徽云速付", agent_task.task)
        self.assertIn("JSON object", agent_task.task)
        self.assertEqual(agent_task.allowed_domains, ["open.work.weixin.qq.com"])
        self.assertEqual(agent_task.browser_profile, "wecom_admin")
        self.assertFalse(agent_task.use_cloud)
        self.assertEqual(agent_task.metadata["task_template"], "wecom_configure_app_v1")

    def test_extracts_structured_json_from_agent_final_result(self):
        runner = LocalBrowserUseRunner(
            agent_factory=lambda agent_task: FakeAgent(
                FakeHistory('{"status": "manual_required", "reason": "需要扫码登录"}')
            )
        )

        result = runner.run_task(
            BrowserUseTaskRequest(
                task_template="wecom_submit_review_v1",
                prompt="提交审核",
                allowed_domains=["open.work.weixin.qq.com"],
                browser_profile="wecom_admin",
            )
        )

        self.assertEqual(result["status"], "manual_required")
        self.assertEqual(result["reason"], "需要扫码登录")

    def test_preserves_needs_login_result_for_upper_runner(self):
        runner = LocalBrowserUseRunner(
            agent_factory=lambda agent_task: FakeAgent({"status": "needs_login", "target": "wecom"})
        )

        result = runner.run_task(
            BrowserUseTaskRequest(
                task_template="wecom_check_review_status_v1",
                prompt="检查审核状态",
                allowed_domains=["open.work.weixin.qq.com"],
                browser_profile="wecom_admin",
            )
        )

        self.assertEqual(result, {"status": "needs_login", "target": "wecom"})

    def test_returns_structured_error_when_agent_output_is_not_json_object(self):
        runner = LocalBrowserUseRunner(agent_factory=lambda agent_task: FakeAgent("done"))

        result = runner.run_task(
            BrowserUseTaskRequest(
                task_template="wecom_submit_online_v1",
                prompt="提交上线",
                allowed_domains=["open.work.weixin.qq.com"],
                browser_profile="wecom_admin",
            )
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "BrowserUseRunnerError")
        self.assertIn("structured dict", result["error_detail"])

    def test_returns_structured_error_when_agent_raises(self):
        def agent_factory(agent_task):
            raise RuntimeError("browser session unavailable")

        runner = LocalBrowserUseRunner(agent_factory=agent_factory)

        result = runner.run_task(
            BrowserUseTaskRequest(
                task_template="wecom_configure_app_v1",
                prompt="配置应用",
                allowed_domains=["open.work.weixin.qq.com"],
                browser_profile="wecom_admin",
            )
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertEqual(result["error_detail"], "browser session unavailable")


if __name__ == "__main__":
    unittest.main()
