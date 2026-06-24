import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from rpa_platform.worker.dingtalk_group_handoff import (
    DingtalkGroupHandoffSmokeRunner,
    HandoffElementPaths,
)


class DingtalkGroupHandoffSmokeTest(unittest.TestCase):
    def test_runs_search_group_settings_and_add_member_chain(self):
        with TemporaryDirectory() as tmpdir:
            paths = _write_handoff_files(Path(tmpdir))
            calls = []
            runner = DingtalkGroupHandoffSmokeRunner(
                uia_driver=_FakeDriver(calls),
                gui_backend=_FakeGui(calls),
                clipboard_backend=_FakeClipboard(calls),
                sleep=lambda _seconds: None,
            )

            runner.run(
                group_name="帆软测试&简道云沟通群",
                paths=paths,
                step_delay_seconds=0,
            )

            self.assertEqual(
                calls,
                [
                    ("uia_click", "search_input"),
                    ("clipboard_copy", "帆软测试&简道云沟通群"),
                    ("hotkey", ("ctrl", "a")),
                    ("hotkey", ("ctrl", "v")),
                    ("position_click", 610, 80),
                    (
                        "locate",
                        str(paths.normal_group_image),
                        0.75,
                        (386, 90, 880, 348),
                    ),
                    ("position_click", 638, 124),
                    ("uia_click", "settings_button"),
                    ("uia_click", "add_member_button"),
                ],
            )

    def test_auto_click_uses_position_for_generic_large_panel_capture(self):
        calls = []
        runner = DingtalkGroupHandoffSmokeRunner(
            uia_driver=_FakeDriver(calls),
            gui_backend=_FakeGui(calls),
            clipboard_backend=_FakeClipboard(calls),
            sleep=lambda _seconds: None,
        )

        runner.click_collected_config(
            {
                "target": {
                    "type": "uia",
                    "name": "",
                    "class_name": "Chrome_RenderWidgetHostHWND",
                    "control_type": "PaneControl",
                    "bounding_rect_hint": [0, 0, 1600, 900],
                },
                "fallback_position": {"x": 1200, "y": 80},
            },
            click_mode="auto",
        )

        self.assertEqual(calls, [("position_click", 1200, 80)])

    def test_can_force_search_input_to_position_click_when_uia_click_is_noop(self):
        with TemporaryDirectory() as tmpdir:
            paths = _write_handoff_files(Path(tmpdir))
            calls = []
            runner = DingtalkGroupHandoffSmokeRunner(
                uia_driver=_FakeDriver(calls),
                gui_backend=_FakeGui(calls),
                clipboard_backend=_FakeClipboard(calls),
                sleep=lambda _seconds: None,
            )

            runner.run(
                group_name="帆软测试&简道云沟通群",
                paths=paths,
                search_click_mode="position",
                step_delay_seconds=0,
                stop_before_add_member=True,
            )

            self.assertEqual(calls[0], ("position_click", 650, 20))


class _FakeDriver:
    def __init__(self, calls):
        self.calls = calls

    def click_element(self, target):
        self.calls.append(("uia_click", target["automation_id"]))

    def click_position(self, x, y):
        self.calls.append(("position_click", x, y))


class _FakeGui:
    def __init__(self, calls):
        self.calls = calls

    def hotkey(self, *keys):
        self.calls.append(("hotkey", tuple(keys)))

    def locateOnScreen(self, image, confidence, region):
        self.calls.append(("locate", image, confidence, region))
        return SimpleNamespace(left=617, top=112, width=42, height=24)


class _FakeClipboard:
    def __init__(self, calls):
        self.calls = calls

    def copy(self, value):
        self.calls.append(("clipboard_copy", value))


def _write_handoff_files(root: Path) -> HandoffElementPaths:
    elements_dir = root / "dingtalk_group_handoff"
    elements_dir.mkdir()
    normal_group_image = elements_dir / "normal_group.png"
    normal_group_image.write_bytes(b"fake-image")

    files = {
        "group_search_input.json": {
            "target": _target("search_input", "EditControl"),
            "fallback_position": {"x": 650, "y": 20},
        },
        "select_search_type_group.json": {
            "target": _target("select_group", "TextControl"),
            "fallback_position": {"x": 610, "y": 80},
        },
        "group_settings_button.json": {
            "target": _target("settings_button", "ButtonControl"),
            "fallback_position": {"x": 1200, "y": 80},
        },
        "add_member_button.json": {
            "target": _target("add_member_button", "ButtonControl"),
            "fallback_position": {"x": 1100, "y": 220},
        },
    }
    for filename, payload in files.items():
        (elements_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    return HandoffElementPaths.from_dir(elements_dir)


def _target(automation_id: str, control_type: str) -> dict:
    return {
        "type": "uia",
        "window_title": "钉钉",
        "control_type": control_type,
        "name": automation_id,
        "automation_id": automation_id,
        "class_name": "",
        "bounding_rect_hint": [1, 2, 3, 4],
    }


if __name__ == "__main__":
    unittest.main()
