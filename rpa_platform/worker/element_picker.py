import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from typing import Any, Dict


def build_selector_from_element(element: Dict[str, Any]) -> Dict[str, Any]:
    bounding_rect = element.get("bounding_rect")
    bounding_rect_hint = (
        list(bounding_rect) if isinstance(bounding_rect, (list, tuple)) else bounding_rect
    )
    return {
        "type": "uia",
        "window_title": str(element.get("window_title", "")),
        "control_type": str(element.get("control_type", "")),
        "name": str(element.get("name", "")),
        "class_name": str(element.get("class_name", "")),
        "automation_id": str(element.get("automation_id", "")),
        "xpath": str(element.get("xpath", "")),
        "hierarchy_path": list(element.get("hierarchy_path", [])),
        "bounding_rect_hint": bounding_rect_hint,
    }


def _center_from_rect(rect: Any) -> Dict[str, int]:
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return {}
    left, top, right, bottom = rect
    return {
        "x": int((left + right) / 2),
        "y": int((top + bottom) / 2),
    }


def build_element_action_config(
    business_action: str,
    element: Dict[str, Any],
    collected_at: str = "",
    note: str = "",
) -> Dict[str, Any]:
    selector = build_selector_from_element(element)
    timestamp = collected_at or datetime.now(timezone.utc).isoformat()
    return {
        "business_action": business_action,
        "target": selector,
        "fallback_position": _center_from_rect(selector.get("bounding_rect_hint")),
        "collected_at": timestamp,
        "note": note,
    }


def collect_element_from_cursor(automation_backend: Any = None) -> Dict[str, Any]:
    automation = automation_backend or _load_uiautomation()
    if not hasattr(automation, "ControlFromCursor"):
        raise RuntimeError("uiautomation backend does not support ControlFromCursor")
    control = automation.ControlFromCursor()
    return _snapshot_control(control)


def main(argv: List[str] = None, automation_backend: Any = None) -> int:
    parser = argparse.ArgumentParser(description="Collect a Windows UIA element under cursor")
    parser.add_argument("--business-action", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--collected-at", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    element = collect_element_from_cursor(automation_backend=automation_backend)
    config = build_element_action_config(
        business_action=args.business_action,
        element=element,
        collected_at=args.collected_at,
        note=args.note,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _snapshot_control(control: Any) -> Dict[str, Any]:
    window_title = _top_window_title(control)
    hierarchy_path = _hierarchy_path(control)
    return {
        "name": str(getattr(control, "Name", "")),
        "automation_id": str(getattr(control, "AutomationId", "")),
        "class_name": str(getattr(control, "ClassName", "")),
        "control_type": str(getattr(control, "ControlTypeName", "")),
        "window_title": window_title,
        "hierarchy_path": hierarchy_path,
        "bounding_rect": list(getattr(control, "BoundingRectangle", []) or []),
    }


def _top_window_title(control: Any) -> str:
    if hasattr(control, "GetTopLevelControl"):
        top = control.GetTopLevelControl()
        if top is not None:
            return str(getattr(top, "Name", ""))
    path = _hierarchy_path(control)
    return path[0] if path else ""


def _hierarchy_path(control: Any) -> List[str]:
    names = []
    current = control
    for _ in range(12):
        if current is None:
            break
        name = str(getattr(current, "Name", ""))
        if name:
            names.append(name)
        if not hasattr(current, "GetParentControl"):
            break
        current = current.GetParentControl()
    names.reverse()
    return names


def _load_uiautomation() -> Any:
    try:
        import uiautomation as automation  # type: ignore
    except ImportError as exc:
        raise RuntimeError("uiautomation is required on Windows for element collection") from exc
    return automation


if __name__ == "__main__":
    raise SystemExit(main())
