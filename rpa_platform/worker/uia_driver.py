import time
from typing import Any, Dict, Optional, Protocol


class UiaDriver(Protocol):
    def find_element(self, selector: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def wait_element(
        self, selector: Dict[str, Any], timeout_seconds: float = 10.0
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def click_element(self, selector: Dict[str, Any]) -> None:
        raise NotImplementedError

    def set_text(self, selector: Dict[str, Any], value: str) -> None:
        raise NotImplementedError

    def input_text(self, selector: Dict[str, Any], value: str) -> None:
        raise NotImplementedError

    def assert_checked(self, selector: Dict[str, Any], expected: bool = True) -> None:
        raise NotImplementedError

    def scroll_to_element(self, selector: Dict[str, Any]) -> None:
        raise NotImplementedError


class UiaAutomationDriver:
    def __init__(self, automation_backend: Any = None):
        self._automation = automation_backend or self._load_uiautomation()

    def find_element(self, selector: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        control = self._resolve_control(selector, must_exist=False)
        if control is None:
            return None
        return self._snapshot(control)

    def wait_element(
        self, selector: Dict[str, Any], timeout_seconds: float = 10.0
    ) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            element = self.find_element(selector)
            if element is not None:
                return element
            if time.monotonic() >= deadline:
                raise TimeoutError("UIA element not found: %s" % selector)
            time.sleep(0.2)

    def click_element(self, selector: Dict[str, Any]) -> None:
        self._resolve_control(selector).Click()

    def set_text(self, selector: Dict[str, Any], value: str) -> None:
        self.input_text(selector, value)

    def input_text(self, selector: Dict[str, Any], value: str) -> None:
        control = self._resolve_control(selector)
        if hasattr(control, "SetValue"):
            control.SetValue(value)
            return
        if hasattr(control, "SendKeys"):
            control.SendKeys("{Ctrl}a")
            control.SendKeys(value)
            return
        raise TypeError("UIA control does not support text input: %s" % selector)

    def assert_checked(self, selector: Dict[str, Any], expected: bool = True) -> None:
        control = self._resolve_control(selector)
        actual = self._is_checked(control)
        if actual is not expected:
            raise AssertionError(
                "checked state mismatch: expected=%s actual=%s selector=%s"
                % (expected, actual, selector)
            )

    def scroll_to_element(self, selector: Dict[str, Any]) -> None:
        control = self._resolve_control(selector)
        if hasattr(control, "GetScrollItemPattern"):
            pattern = control.GetScrollItemPattern()
            pattern.ScrollIntoView()
            return
        if hasattr(control, "ScrollIntoView"):
            control.ScrollIntoView()
            return
        raise TypeError("UIA control does not support scroll into view: %s" % selector)

    def _resolve_control(
        self, selector: Dict[str, Any], must_exist: bool = True
    ) -> Optional[Any]:
        search_root = None
        window_title = selector.get("window_title")
        if window_title:
            search_root = self._automation.WindowControl(Name=window_title, searchDepth=1)

        kwargs = self._control_search_kwargs(selector)
        if search_root is not None:
            kwargs["searchFromControl"] = search_root

        control = self._automation.Control(**kwargs)
        exists = control.Exists(0, 0) if hasattr(control, "Exists") else True
        if exists:
            return control
        fallback = self._resolve_fallback_control(selector)
        if fallback is not None:
            return fallback
        if must_exist:
            raise LookupError("UIA element not found: %s" % selector)
        return None

    def _resolve_fallback_control(self, selector: Dict[str, Any]) -> Optional[Any]:
        automation_id = selector.get("automation_id")
        if not automation_id:
            return None
        control = self._automation.Control(
            searchDepth=int(selector.get("search_depth", 8)),
            AutomationId=automation_id,
        )
        exists = control.Exists(0, 0) if hasattr(control, "Exists") else True
        return control if exists else None

    def _control_search_kwargs(self, selector: Dict[str, Any]) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {"searchDepth": int(selector.get("search_depth", 8))}
        mapping = {
            "name": "Name",
            "automation_id": "AutomationId",
            "class_name": "ClassName",
            "control_type": "ControlType",
        }
        for source_key, target_key in mapping.items():
            value = selector.get(source_key)
            if value:
                kwargs[target_key] = value
        return kwargs

    def _snapshot(self, control: Any) -> Dict[str, Any]:
        return {
            "name": str(getattr(control, "Name", "")),
            "automation_id": str(getattr(control, "AutomationId", "")),
            "class_name": str(getattr(control, "ClassName", "")),
            "control_type": str(getattr(control, "ControlTypeName", "")),
            "bounding_rect": self._rect_to_list(getattr(control, "BoundingRectangle", [])),
        }

    def _rect_to_list(self, rect: Any) -> list[int]:
        if not rect:
            return []
        if isinstance(rect, (list, tuple)):
            return list(rect)
        lower_attrs = ("left", "top", "right", "bottom")
        if all(hasattr(rect, attr) for attr in lower_attrs):
            return [int(getattr(rect, attr)) for attr in lower_attrs]
        upper_attrs = ("Left", "Top", "Right", "Bottom")
        if all(hasattr(rect, attr) for attr in upper_attrs):
            return [int(getattr(rect, attr)) for attr in upper_attrs]
        return list(rect)

    def _is_checked(self, control: Any) -> bool:
        if hasattr(control, "GetTogglePattern"):
            pattern = control.GetTogglePattern()
            return getattr(pattern, "ToggleState") == 1
        if hasattr(control, "ToggleState"):
            return getattr(control, "ToggleState") == 1
        raise TypeError("UIA control does not expose toggle state")

    def _load_uiautomation(self) -> Any:
        try:
            import uiautomation as automation  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "uiautomation is required on Windows for UIA element execution"
            ) from exc
        return automation
