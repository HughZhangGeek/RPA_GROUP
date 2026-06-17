import unittest

from rpa_platform.worker.element_picker import build_selector_from_element


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
