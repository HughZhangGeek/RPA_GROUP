import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rpa_platform.worker.element_picker import (
    build_element_action_config,
    build_selector_from_element,
    collect_element_from_cursor,
    main,
)


class ElementPickerTest(unittest.TestCase):
    def test_builds_selector_from_uia_element_metadata(self):
        selector = build_selector_from_element(
            {
                "name": "发起群聊",
                "automation_id": "",
                "class_name": "Button",
                "control_type": "Button",
                "window_title": "企业微信",
                "bounding_rect": [100, 200, 180, 240],
            }
        )

        self.assertEqual(selector["type"], "uia")
        self.assertEqual(selector["name"], "发起群聊")
        self.assertEqual(selector["control_type"], "Button")
        self.assertEqual(selector["window_title"], "企业微信")
        self.assertNotIn("screenshot", selector)

    def test_copies_bounding_rect_hint_from_element(self):
        element = {
            "name": "发起群聊",
            "automation_id": "",
            "class_name": "Button",
            "control_type": "Button",
            "window_title": "企业微信",
            "bounding_rect": [1, 2, 3, 4],
        }

        selector = build_selector_from_element(element)
        selector["bounding_rect_hint"][0] = 99

        self.assertEqual(element["bounding_rect"][0], 1)

    def test_builds_reusable_action_config_from_collected_element(self):
        config = build_element_action_config(
            business_action="wecom_bind.permission.save",
            element={
                "name": "保存",
                "automation_id": "saveButton",
                "class_name": "Button",
                "control_type": "Button",
                "window_title": "企业微信",
                "xpath": "/Window/Button[3]",
                "hierarchy_path": ["企业微信", "权限设置", "保存"],
                "bounding_rect": [900, 720, 980, 760],
            },
            collected_at="2026-06-24T10:00:00+08:00",
            note="企微权限页面保存按钮",
        )

        self.assertEqual(config["business_action"], "wecom_bind.permission.save")
        self.assertEqual(config["target"]["type"], "uia")
        self.assertEqual(config["target"]["automation_id"], "saveButton")
        self.assertEqual(config["target"]["xpath"], "/Window/Button[3]")
        self.assertEqual(config["target"]["hierarchy_path"], ["企业微信", "权限设置", "保存"])
        self.assertEqual(config["fallback_position"], {"x": 940, "y": 740})
        self.assertEqual(config["collected_at"], "2026-06-24T10:00:00+08:00")
        self.assertEqual(config["note"], "企微权限页面保存按钮")

    def test_collects_element_from_cursor_with_hierarchy(self):
        class FakeParent:
            Name = "企业微信"

            def GetParentControl(self):
                return None

        class FakeControl:
            Name = "姓名"
            AutomationId = "nameCheckbox"
            ClassName = "CheckBox"
            ControlTypeName = "CheckBox"
            BoundingRectangle = [10, 20, 110, 60]

            def GetParentControl(self):
                return FakeParent()

            def GetTopLevelControl(self):
                return FakeParent()

        class FakeAutomation:
            def ControlFromCursor(self):
                return FakeControl()

        element = collect_element_from_cursor(automation_backend=FakeAutomation())

        self.assertEqual(element["name"], "姓名")
        self.assertEqual(element["window_title"], "企业微信")
        self.assertEqual(element["hierarchy_path"], ["企业微信", "姓名"])

    def test_cli_writes_collected_action_config(self):
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "element.json"

            status = main(
                [
                    "--business-action",
                    "wecom_bind.permission.name",
                    "--collected-at",
                    "2026-06-24T10:00:00+08:00",
                    "--output",
                    str(output),
                ],
                automation_backend=_FakeAutomationForCli(),
            )

            self.assertEqual(status, 0)
            content = output.read_text(encoding="utf-8")
            self.assertIn('"business_action": "wecom_bind.permission.name"', content)
            self.assertIn('"name": "姓名"', content)

    def test_cli_hotkey_mode_collects_when_shortcut_is_pressed(self):
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "element.json"
            keyboard = _FakeKeyboardForCli()

            status = main(
                [
                    "--business-action",
                    "wecom_bind.permission.name",
                    "--output",
                    str(output),
                    "--hotkey",
                    "ctrl+alt+c",
                ],
                automation_backend=_FakeAutomationForCli(),
                keyboard_backend=keyboard,
            )

            self.assertEqual(status, 0)
            self.assertEqual(keyboard.waited_hotkey, "ctrl+alt+c")
            content = output.read_text(encoding="utf-8")
            self.assertIn('"business_action": "wecom_bind.permission.name"', content)
            self.assertIn('"name": "姓名"', content)


class _FakeAutomationForCli:
    def ControlFromCursor(self):
        class FakeControl:
            Name = "姓名"
            AutomationId = "nameCheckbox"
            ClassName = "CheckBox"
            ControlTypeName = "CheckBox"
            BoundingRectangle = [10, 20, 110, 60]

            def GetParentControl(self):
                return None

            def GetTopLevelControl(self):
                return None

        return FakeControl()


class _FakeKeyboardForCli:
    def __init__(self):
        self.waited_hotkey = ""

    def wait(self, hotkey):
        self.waited_hotkey = hotkey
