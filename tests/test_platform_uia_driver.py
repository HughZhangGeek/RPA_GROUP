import unittest

from rpa_platform.worker.uia_driver import UiaAutomationDriver


class FakeControl:
    def __init__(self, exists=True, checked=True):
        self.exists = exists
        self.checked = checked
        self.calls = []
        self.Name = "姓名"
        self.AutomationId = "nameCheckbox"
        self.ClassName = "CheckBox"
        self.ControlTypeName = "CheckBox"
        self.BoundingRectangle = [10, 20, 110, 60]

    def Exists(self, *_args, **_kwargs):
        self.calls.append(("exists",))
        return self.exists

    def Click(self):
        self.calls.append(("click",))

    def SetValue(self, value):
        self.calls.append(("set_value", value))

    def GetTogglePattern(self):
        self.calls.append(("toggle_pattern",))
        return self

    @property
    def ToggleState(self):
        return 1 if self.checked else 0

    def GetScrollItemPattern(self):
        self.calls.append(("scroll_item_pattern",))
        return self

    def ScrollIntoView(self):
        self.calls.append(("scroll_into_view",))


class FakeAutomationBackend:
    def __init__(self, control):
        self.control = control
        self.calls = []

    def SetGlobalSearchTimeout(self, seconds):
        self.calls.append(("timeout", seconds))

    def WindowControl(self, **kwargs):
        self.calls.append(("window", kwargs))
        return "window-control"

    def Control(self, **kwargs):
        self.calls.append(("control", kwargs))
        return self.control


class SequenceAutomationBackend:
    def __init__(self, controls):
        self.controls = list(controls)
        self.calls = []

    def WindowControl(self, **kwargs):
        self.calls.append(("window", kwargs))
        return "window-control"

    def Control(self, **kwargs):
        self.calls.append(("control", kwargs))
        return self.controls.pop(0)


class UiaAutomationDriverTest(unittest.TestCase):
    def test_finds_uia_element_with_window_scoped_selector(self):
        control = FakeControl()
        backend = FakeAutomationBackend(control)
        driver = UiaAutomationDriver(automation_backend=backend)

        element = driver.find_element(
            {
                "window_title": "企业微信",
                "control_type": "CheckBox",
                "name": "姓名",
                "automation_id": "nameCheckbox",
                "class_name": "CheckBox",
            }
        )

        self.assertEqual(element["name"], "姓名")
        self.assertEqual(element["automation_id"], "nameCheckbox")
        self.assertEqual(
            backend.calls,
            [
                ("window", {"Name": "企业微信", "searchDepth": 1}),
                (
                    "control",
                    {
                        "searchFromControl": "window-control",
                        "searchDepth": 8,
                        "Name": "姓名",
                        "AutomationId": "nameCheckbox",
                        "ClassName": "CheckBox",
                        "ControlType": "CheckBox",
                    },
                ),
            ],
        )

    def test_finds_uia_element_with_rect_object(self):
        class FakeRect:
            left = 10
            top = 20
            right = 110
            bottom = 60

        control = FakeControl()
        control.BoundingRectangle = FakeRect()
        driver = UiaAutomationDriver(automation_backend=FakeAutomationBackend(control))

        element = driver.find_element({"window_title": "企业微信", "name": "姓名"})

        self.assertEqual(element["bounding_rect"], [10, 20, 110, 60])

    def test_falls_back_to_automation_id_when_strict_qt_selector_misses(self):
        missing = FakeControl(exists=False)
        found = FakeControl()
        found.Name = ""
        found.AutomationId = "titlebar_widget.search_bar.search_edit"
        found.ClassName = "QLineEdit"
        found.ControlTypeName = "EditControl"
        backend = SequenceAutomationBackend([missing, found])
        driver = UiaAutomationDriver(automation_backend=backend)

        element = driver.find_element(
            {
                "automation_id": "titlebar_widget.search_bar.search_edit",
                "bounding_rect_hint": [570, 5, 740, 33],
                "class_name": "QLineEdit",
                "control_type": "EditControl",
                "name": "",
                "type": "uia",
                "window_title": "钉钉",
            }
        )

        self.assertEqual(element["automation_id"], "titlebar_widget.search_bar.search_edit")
        self.assertEqual(
            backend.calls,
            [
                ("window", {"Name": "钉钉", "searchDepth": 1}),
                (
                    "control",
                    {
                        "searchFromControl": "window-control",
                        "searchDepth": 8,
                        "AutomationId": "titlebar_widget.search_bar.search_edit",
                        "ClassName": "QLineEdit",
                        "ControlType": "EditControl",
                    },
                ),
                (
                    "control",
                    {
                        "searchDepth": 8,
                        "AutomationId": "titlebar_widget.search_bar.search_edit",
                    },
                ),
            ],
        )

    def test_click_uses_automation_id_fallback_when_strict_qt_selector_misses(self):
        missing = FakeControl(exists=False)
        found = FakeControl()
        found.AutomationId = "titlebar_widget.search_bar.search_edit"
        backend = SequenceAutomationBackend([missing, found])
        driver = UiaAutomationDriver(automation_backend=backend)

        driver.click_element(
            {
                "automation_id": "titlebar_widget.search_bar.search_edit",
                "class_name": "QLineEdit",
                "control_type": "EditControl",
                "window_title": "钉钉",
            }
        )

        self.assertEqual(found.calls, [("exists",), ("click",)])

    def test_click_input_assert_and_scroll_use_uia_patterns(self):
        control = FakeControl(checked=True)
        driver = UiaAutomationDriver(automation_backend=FakeAutomationBackend(control))
        selector = {"window_title": "企业微信", "control_type": "CheckBox", "name": "姓名"}

        driver.click_element(selector)
        driver.input_text(selector, "张三")
        driver.assert_checked(selector, expected=True)
        driver.scroll_to_element(selector)

        self.assertEqual(
            control.calls,
            [
                ("exists",),
                ("click",),
                ("exists",),
                ("set_value", "张三"),
                ("exists",),
                ("toggle_pattern",),
                ("exists",),
                ("scroll_item_pattern",),
                ("scroll_into_view",),
            ],
        )

    def test_assert_checked_raises_when_state_differs(self):
        driver = UiaAutomationDriver(
            automation_backend=FakeAutomationBackend(FakeControl(checked=False))
        )

        with self.assertRaisesRegex(AssertionError, "checked state mismatch"):
            driver.assert_checked({"window_title": "企业微信", "name": "姓名"}, expected=True)


if __name__ == "__main__":
    unittest.main()
