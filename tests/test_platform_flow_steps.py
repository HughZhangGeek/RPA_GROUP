import unittest

from rpa_platform.domain.flow_steps import FlowStepValidationError, validate_steps


class FlowStepValidationTest(unittest.TestCase):
    def test_accepts_table_editor_step_json_shape(self):
        steps = validate_steps(
            [
                {
                    "key": "open_jdy",
                    "name": "打开简道云后台",
                    "action": "open_url",
                    "target": "jdy",
                    "config": {"url": "https://www.jiandaoyun.com"},
                    "enabled": True,
                },
                {
                    "key": "derive_urls",
                    "name": "生成企微配置 URL",
                    "action": "derive_urls",
                    "target": "system",
                    "config": {"source": "corp_secret_id"},
                },
            ]
        )

        self.assertEqual(steps[0]["key"], "open_jdy")
        self.assertTrue(steps[1]["enabled"])

    def test_rejects_duplicate_step_keys(self):
        with self.assertRaises(FlowStepValidationError) as ctx:
            validate_steps(
                [
                    {"key": "open_jdy", "name": "打开简道云后台", "action": "open_url"},
                    {"key": "open_jdy", "name": "重复步骤", "action": "click"},
                ]
            )

        self.assertIn("duplicate step key", str(ctx.exception))

    def test_rejects_missing_action(self):
        with self.assertRaises(FlowStepValidationError) as ctx:
            validate_steps([{"key": "open_jdy", "name": "打开简道云后台"}])

        self.assertIn("action", str(ctx.exception))

    def test_accepts_hybrid_jdy_wecom_browser_use_actions(self):
        steps = validate_steps(
            [
                {"key": "jdy_resolve_corp", "name": "简道云查找绑定企业", "action": "jdy_resolve_corp"},
                {"key": "derive_wecom_urls", "name": "生成企微配置 URL", "action": "derive_wecom_urls"},
                {
                    "key": "wecom_configure_app",
                    "name": "企微页面配置代开发应用",
                    "action": "wecom_configure_app",
                    "config": {"engine": "browser_use", "task_template": "wecom_configure_app_v1"},
                },
                {"key": "jdy_install_bind", "name": "简道云提交企业微信绑定", "action": "jdy_install_bind"},
                {"key": "browser_check", "name": "浏览器状态检查", "action": "browser_use_task"},
                {"key": "wecom_submit_online", "name": "企微待上线后提交上线", "action": "wecom_submit_online"},
            ],
            enforce_action_allowlist=True,
        )

        self.assertEqual(
            [step["action"] for step in steps],
            [
                "jdy_resolve_corp",
                "derive_wecom_urls",
                "wecom_configure_app",
                "jdy_install_bind",
                "browser_use_task",
                "wecom_submit_online",
            ],
        )

    def test_rejects_unknown_action_when_allowlist_is_enabled(self):
        with self.assertRaises(FlowStepValidationError) as ctx:
            validate_steps(
                [{"key": "bad", "name": "未知动作", "action": "unknown_action"}],
                enforce_action_allowlist=True,
            )

        self.assertIn("unknown action", str(ctx.exception))

    def test_default_wecom_launch_flow_steps_validate_with_allowlist(self):
        from rpa_platform.domain.default_flows import WECOM_APP_LAUNCH_FLOW_STEPS

        steps = validate_steps(WECOM_APP_LAUNCH_FLOW_STEPS, enforce_action_allowlist=True)

        self.assertEqual(steps[0]["key"], "jdy_resolve_corp")
        self.assertEqual(steps[-1]["key"], "wecom_submit_online")
        self.assertEqual([step["action"] for step in steps], [step["action"] for step in WECOM_APP_LAUNCH_FLOW_STEPS])

    def test_default_wecom_bind_service_flow_steps_validate_with_allowlist(self):
        from rpa_platform.domain.default_flows import WECOM_BIND_SERVICE_FLOW_STEPS

        steps = validate_steps(WECOM_BIND_SERVICE_FLOW_STEPS, enforce_action_allowlist=True)

        self.assertEqual(
            [step["key"] for step in steps],
            [
                "jdy_wecom_bind_service",
                "wecom_wait_online_delay",
                "wecom_submit_online_order",
            ],
        )
        self.assertEqual(
            [step["action"] for step in steps],
            [
                "jdy_wecom_bind_service",
                "wecom_wait_online_delay",
                "wecom_submit_online_order",
            ],
        )


if __name__ == "__main__":
    unittest.main()
