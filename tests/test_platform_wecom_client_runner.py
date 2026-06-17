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
    def test_executes_create_group_template_commands(self):
        driver = FakeUiaDriver()
        runner = WecomCreateGroupRunner(uia_driver=driver)
        open_create_group_target = {
            "type": "uia",
            "window_title": "企业微信",
            "control_type": "Button",
            "name": "发起群聊",
        }
        set_group_name_target = {
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
                    "target": open_create_group_target,
                },
                {
                    "step_key": "set_group_name",
                    "step_name": "设置群名称",
                    "action": "set_text",
                    "target": set_group_name_target,
                    "value_from": "group_name",
                },
            ],
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(driver.calls[0][0], "click")
        self.assertEqual(driver.calls[0][1]["name"], open_create_group_target["name"])
        self.assertEqual(driver.calls[0][1]["control_type"], open_create_group_target["control_type"])
        self.assertEqual(driver.calls[0][1]["window_title"], open_create_group_target["window_title"])
        self.assertEqual(driver.calls[1][0], "set_text")
        self.assertEqual(driver.calls[1][1]["name"], set_group_name_target["name"])
        self.assertEqual(driver.calls[1][1]["control_type"], set_group_name_target["control_type"])
        self.assertEqual(driver.calls[1][1]["window_title"], set_group_name_target["window_title"])
        self.assertEqual(driver.calls[1][2], "zh_test_上海测试客户_服务群")
