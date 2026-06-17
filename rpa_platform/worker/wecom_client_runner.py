from typing import Any, Dict, List


class WecomCreateGroupRunner:
    def __init__(self, uia_driver: Any):
        self.uia_driver = uia_driver

    def run_template(
        self,
        task_id: str,
        payload: Dict[str, Any],
        commands: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        for command in commands:
            action = command["action"]
            target = command.get("target", {})
            if action == "click_element":
                self.uia_driver.click_element(target)
            elif action == "set_text":
                value = payload[command["value_from"]]
                self.uia_driver.set_text(target, value)
            else:
                raise ValueError("Unsupported create-group command: %s" % action)
        return {
            "task_id": task_id,
            "status": "success",
            "group_name": payload.get("group_name", ""),
        }
