import unittest

from rpa_platform.worker.wecom_rpa import (
    BrowserUseTaskRequest,
    BrowserUseWecomRpa,
    FakeBrowserUseRunner,
    FakeWecomRpa,
    WecomReviewStatus,
)


class WecomRpaTest(unittest.TestCase):
    def test_fake_rpa_returns_token_and_aeskey_for_configuration(self):
        rpa = FakeWecomRpa(
            configure_result={
                "token": "token-secret",
                "encoding_aes_key": "aes-secret",
                "review_status": "审核中",
            }
        )

        result = rpa.configure_custom_app({"id": "task-1", "enterprise_name": "安徽云速付"}, {"wecom": {}})

        self.assertEqual(result["token"], "token-secret")
        self.assertEqual(result["encoding_aes_key"], "aes-secret")
        self.assertEqual(result["review_status"], "审核中")

    def test_fake_rpa_reports_ready_to_online_and_submit_success(self):
        rpa = FakeWecomRpa(review_statuses=[WecomReviewStatus.READY_TO_ONLINE])

        status = rpa.check_review_status({"id": "task-1", "enterprise_name": "安徽云速付"}, {})
        submit = rpa.submit_online({"id": "task-1", "enterprise_name": "安徽云速付"}, {})

        self.assertEqual(status, WecomReviewStatus.READY_TO_ONLINE)
        self.assertTrue(submit["online_submitted"])

    def test_browser_use_adapter_builds_scoped_configuration_task(self):
        runner = FakeBrowserUseRunner(
            results=[
                {
                    "token": "token-secret",
                    "encoding_aes_key": "aes-secret",
                    "review_status": "审核中",
                    "page_state": "配置已填写，等待提交审核",
                }
            ]
        )
        rpa = BrowserUseWecomRpa(runner=runner, browser_profile="wecom_admin")

        result = rpa.configure_custom_app(
            {"id": "task-1", "enterprise_name": "安徽云速付"},
            {
                "jdy": {"suite_name": "简道云", "wecom_template_id": "1009479"},
                "wecom": {
                    "homeurl": "https://wxwork.jiandaoyun.com/wxwork/corp-secret/dashboard",
                    "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/corp-secret/service",
                    "redirect_domain": "wxwork.jiandaoyun.com",
                },
            },
        )

        request = runner.requests[0]
        self.assertEqual(request.task_template, "wecom_configure_app_v1")
        self.assertEqual(request.browser_profile, "wecom_admin")
        self.assertEqual(request.allowed_domains, ["open.work.weixin.qq.com"])
        self.assertFalse(request.use_cloud)
        self.assertIn("安徽云速付", request.prompt)
        self.assertIn("1009479", request.prompt)
        self.assertIn("ONLY 在 open.work.weixin.qq.com 域名内操作", request.prompt)
        self.assertEqual(result["token"], "token-secret")
        self.assertEqual(result["encoding_aes_key"], "aes-secret")

    def test_browser_use_task_request_rejects_cloud_mode_for_wecom(self):
        with self.assertRaises(ValueError):
            BrowserUseTaskRequest(
                task_template="wecom_configure_app_v1",
                prompt="配置企微应用",
                allowed_domains=["open.work.weixin.qq.com"],
                browser_profile="wecom_admin",
                use_cloud=True,
            )


if __name__ == "__main__":
    unittest.main()
