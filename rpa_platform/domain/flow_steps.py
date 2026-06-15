from typing import Any, Dict, List


class FlowStepValidationError(ValueError):
    """Raised when flow step JSON cannot be saved as a runnable version."""


ALLOWED_ACTIONS = {
    "receive_webhook",
    "open_url",
    "click",
    "derive_urls",
    "browser_use_task",
    "jdy_resolve_corp",
    "derive_wecom_urls",
    "wecom_configure_app",
    "jdy_check_owner",
    "jdy_install_bind",
    "wecom_submit_review",
    "wecom_wait_review",
    "wecom_submit_online",
}


def validate_steps(
    steps: List[Dict[str, Any]],
    enforce_action_allowlist: bool = False,
) -> List[Dict[str, Any]]:
    if not isinstance(steps, list) or not steps:
        raise FlowStepValidationError("steps must be a non-empty list")

    normalized = []
    seen_keys = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise FlowStepValidationError("each step must be an object")
        key = _required_text(step, "key", index)
        name = _required_text(step, "name", index)
        action = _required_text(step, "action", index)
        if enforce_action_allowlist and action not in ALLOWED_ACTIONS:
            raise FlowStepValidationError("unknown action: %s" % action)
        if key in seen_keys:
            raise FlowStepValidationError("duplicate step key: %s" % key)
        seen_keys.add(key)

        config = step.get("config", {})
        if not isinstance(config, dict):
            raise FlowStepValidationError("step %s config must be an object" % key)

        normalized_step = dict(step)
        normalized_step["key"] = key
        normalized_step["name"] = name
        normalized_step["action"] = action
        normalized_step["config"] = config
        normalized_step["enabled"] = bool(step.get("enabled", True))
        normalized.append(normalized_step)
    return normalized


def _required_text(step: Dict[str, Any], field: str, index: int) -> str:
    value = step.get(field)
    if value is None:
        raise FlowStepValidationError("step %d missing required field: %s" % (index, field))
    text = str(value).strip()
    if not text:
        raise FlowStepValidationError("step %d empty required field: %s" % (index, field))
    return text
