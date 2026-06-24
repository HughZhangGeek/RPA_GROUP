import unittest

from rpa_platform.worker.client_commands import normalize_client_command


class ClientCommandTest(unittest.TestCase):
    def test_normalizes_uia_click_command_with_image_fallback(self):
        command = normalize_client_command(
            {
                "step_key": "open_create_group",
                "step_name": "打开发起群聊入口",
                "action": "click_element",
                "target": {
                    "type": "uia",
                    "window_title": "企业微信",
                    "control_type": "Button",
                    "name": "发起群聊",
                },
                "fallback": {
                    "type": "image",
                    "image_key": "wecom_create_group_button",
                },
            }
        )

        self.assertEqual(command["action"], "click_element")
        self.assertEqual(command["target"]["type"], "uia")
        self.assertEqual(command["fallback"]["type"], "image")

    def test_rejects_position_click_without_high_risk_marker(self):
        with self.assertRaises(ValueError):
            normalize_client_command(
                {
                    "step_key": "unsafe_click",
                    "step_name": "坐标点击",
                    "action": "fallback_position_click",
                    "target": {"type": "position", "x": 100, "y": 200},
                }
            )

    def test_rejects_uia_action_with_non_dict_target_as_value_error(self):
        with self.assertRaises(ValueError):
            normalize_client_command(
                {
                    "step_key": "invalid_target",
                    "step_name": "非法 target",
                    "action": "click_element",
                    "target": "not-a-dict",
                }
            )

    def test_returns_command_without_sharing_nested_target(self):
        raw = {
            "step_key": "open_create_group",
            "step_name": "打开发起群聊入口",
            "action": "click_element",
            "target": {
                "type": "uia",
                "window_title": "企业微信",
                "control_type": "Button",
                "name": "发起群聊",
            },
        }

        command = normalize_client_command(raw)
        command["target"]["name"] = "被 runner 修改"

        self.assertEqual(raw["target"]["name"], "发起群聊")

    def test_accepts_element_driven_actions_for_wecom_permission_page(self):
        for action in (
            "wait_element",
            "input_text",
            "assert_checked",
            "scroll_to_element",
        ):
            command = normalize_client_command(
                {
                    "step_key": action,
                    "step_name": "企微权限页元素动作",
                    "action": action,
                    "target": {
                        "type": "uia",
                        "window_title": "企业微信",
                        "control_type": "CheckBox",
                        "name": "姓名",
                    },
                }
            )

            self.assertEqual(command["action"], action)
            self.assertEqual(command["target"]["name"], "姓名")
