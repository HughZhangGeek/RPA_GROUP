import copy
from typing import Any, Dict


SUPPORTED_ACTIONS = {
    "activate_app",
    "find_element",
    "click_element",
    "set_text",
    "clipboard_paste",
    "send_hotkey",
    "wait_until",
    "assert_element",
    "capture_artifact",
    "fallback_image_click",
    "fallback_position_click",
}


def normalize_client_command(raw: Dict[str, Any]) -> Dict[str, Any]:
    command = copy.deepcopy(raw)
    action = command.get("action", "")
    if action not in SUPPORTED_ACTIONS:
        raise ValueError("Unsupported client command action: %s" % action)
    if action == "fallback_position_click" and command.get("risk_level") != "high":
        raise ValueError("Position click fallback must be marked risk_level=high")
    if not command.get("step_key"):
        raise ValueError("Client command step_key is required")
    if not command.get("step_name"):
        raise ValueError("Client command step_name is required")
    if action in ("click_element", "find_element", "set_text", "assert_element"):
        target = command.get("target") or {}
        if not isinstance(target, dict) or target.get("type") != "uia":
            raise ValueError("%s requires a UIA target" % action)
    return command
