from typing import Any, Dict, List

from rpa_platform.worker.client_commands import normalize_client_command


class WecomCreateGroupRunner:
    def __init__(self, uia_driver: Any):
        self.uia_driver = uia_driver

    def run_template(
        self,
        task_id: str,
        payload: Dict[str, Any],
        commands: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if payload.get("test_mode") is not True and payload.get("confirm_write") is not True:
            raise ValueError("Create-group runner requires test_mode=true or confirm_write=true")
        for raw_command in commands:
            command = normalize_client_command(raw_command)
            action = command["action"]
            target = command.get("target", {})
            if action == "click_element":
                self.uia_driver.click_element(target)
            elif action == "wait_element":
                self.uia_driver.wait_element(
                    target,
                    timeout_seconds=command.get("timeout_seconds", 10.0),
                )
            elif action == "set_text":
                value = payload[command["value_from"]]
                self.uia_driver.set_text(target, value)
            elif action == "input_text":
                value = payload[command["value_from"]]
                self.uia_driver.input_text(target, value)
            elif action == "assert_checked":
                self.uia_driver.assert_checked(target, expected=command.get("expected", True))
            elif action == "scroll_to_element":
                self.uia_driver.scroll_to_element(target)
            elif action == "fallback_position_click":
                self.uia_driver.click_position(target["x"], target["y"])
            else:
                raise ValueError("Unsupported create-group command: %s" % action)
        return {
            "task_id": task_id,
            "status": "success",
            "group_name": payload.get("group_name", ""),
        }
