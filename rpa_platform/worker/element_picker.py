from typing import Any, Dict


def build_selector_from_element(element: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "uia",
        "window_title": str(element.get("window_title", "")),
        "control_type": str(element.get("control_type", "")),
        "name": str(element.get("name", "")),
        "class_name": str(element.get("class_name", "")),
        "automation_id": str(element.get("automation_id", "")),
        "bounding_rect_hint": element.get("bounding_rect"),
    }
