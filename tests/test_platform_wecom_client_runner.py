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

    def wait_element(self, selector, timeout_seconds=10.0):
        self.calls.append(("wait", selector, timeout_seconds))
        return {"name": selector.get("name", ""), "control_type": selector.get("control_type", "")}

    def input_text(self, selector, value):
        self.calls.append(("input_text", selector, value))

    def assert_checked(self, selector, expected=True):
        self.calls.append(("assert_checked", selector, expected))

    def scroll_to_element(self, selector):
        self.calls.append(("scroll_to", selector))


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

    def test_executes_element_driven_permission_commands(self):
        driver = FakeUiaDriver()
        runner = WecomCreateGroupRunner(uia_driver=driver)
        name_checkbox = {
            "type": "uia",
            "window_title": "企业微信",
            "control_type": "CheckBox",
            "name": "姓名",
        }
        dept_checkbox = {
            "type": "uia",
            "window_title": "企业微信",
            "control_type": "CheckBox",
            "name": "部门名",
        }
        save_button = {
            "type": "uia",
            "window_title": "企业微信",
            "control_type": "Button",
            "name": "保存",
        }

        result = runner.run_template(
            task_id="task-001",
            payload={"test_mode": True, "group_name": "zh_test_服务群"},
            commands=[
                {
                    "step_key": "wait_org_info",
                    "step_name": "等待组织架构信息",
                    "action": "wait_element",
                    "target": name_checkbox,
                    "timeout_seconds": 3,
                },
                {
                    "step_key": "scroll_dept",
                    "step_name": "滚动到部门名",
                    "action": "scroll_to_element",
                    "target": dept_checkbox,
                },
                {
                    "step_key": "assert_name",
                    "step_name": "确认姓名已勾选",
                    "action": "assert_checked",
                    "target": name_checkbox,
                    "expected": True,
                },
                {
                    "step_key": "save_permission",
                    "step_name": "保存权限",
                    "action": "click_element",
                    "target": save_button,
                },
            ],
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            driver.calls,
            [
                ("wait", name_checkbox, 3),
                ("scroll_to", dept_checkbox),
                ("assert_checked", name_checkbox, True),
                ("click", save_button),
            ],
        )
