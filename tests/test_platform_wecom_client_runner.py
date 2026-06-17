import unittest

from rpa_platform.worker.wecom_client_runner import WecomCreateGroupRunner


class FakeUiaDriver:
    def __init__(self):
        self.calls = []

    def find_element(self, selector):
        self.calls.append(("find", selector))
        return {"name": selector.get("name", ""), "control_type": selector.get("control_type", "")}

    def click_element(self, selector):
        self.calls.append(("click", selector))

    def set_text(self, selector, value):
        self.calls.append(("set_text", selector, value))


class WecomCreateGroupRunnerTest(unittest.TestCase):
    def test_requires_test_mode_or_confirm_write_before_driver_calls(self):
        driver = FakeUiaDriver()
        runner = WecomCreateGroupRunner(uia_driver=driver)

        with self.assertRaisesRegex(ValueError, "requires test_mode=true or confirm_write=true"):
            runner.run_template(
                task_id="task-001",
                payload={
                    "customer_name": "zh_test_上海测试客户",
                    "group_name": "zh_test_上海测试客户_服务群",
                    "member_names": ["李四"],
                },
                commands=[
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
                    }
                ],
            )

        self.assertEqual(driver.calls, [])

    def test_executes_create_group_template_commands(self):
        driver = FakeUiaDriver()
        runner = WecomCreateGroupRunner(uia_driver=driver)
        open_target = {
            "type": "uia",
            "window_title": "企业微信",
            "control_type": "Button",
            "name": "发起群聊",
        }
        set_name_target = {
            "type": "uia",
            "window_title": "企业微信",
            "control_type": "Edit",
            "name": "群名称",
        }

        result = runner.run_template(
            task_id="task-001",
            payload={
                "customer_name": "zh_test_上海测试客户",
                "group_name": "zh_test_上海测试客户_服务群",
                "member_names": ["李四"],
                "test_mode": True,
            },
            commands=[
                {
                    "step_key": "open_create_group",
                    "step_name": "打开发起群聊入口",
                    "action": "click_element",
                    "target": open_target,
                },
                {
                    "step_key": "set_group_name",
                    "step_name": "设置群名称",
                    "action": "set_text",
                    "target": set_name_target,
                    "value_from": "group_name",
                },
            ],
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            driver.calls,
            [
                ("click", open_target),
                ("set_text", set_name_target, "zh_test_上海测试客户_服务群"),
            ],
        )

    def test_confirm_write_allows_create_group_template_commands(self):
        driver = FakeUiaDriver()
        runner = WecomCreateGroupRunner(uia_driver=driver)
        open_target = {
            "type": "uia",
            "window_title": "企业微信",
            "control_type": "Button",
            "name": "发起群聊",
        }

        result = runner.run_template(
            task_id="task-001",
            payload={
                "customer_name": "zh_test_上海测试客户",
                "group_name": "zh_test_上海测试客户_服务群",
                "member_names": ["李四"],
                "confirm_write": True,
            },
            commands=[
                {
                    "step_key": "open_create_group",
                    "step_name": "打开发起群聊入口",
                    "action": "click_element",
                    "target": open_target,
                },
            ],
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(driver.calls, [("click", open_target)])
