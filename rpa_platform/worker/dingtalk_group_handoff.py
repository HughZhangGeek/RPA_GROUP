import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rpa_platform.worker.uia_driver import UiaAutomationDriver


DEFAULT_ELEMENTS_DIR = Path(".local") / "elements" / "dingtalk_group_handoff"
DEFAULT_GROUP_NAME = "帆软测试&简道云沟通群"
DEFAULT_SEARCH_REGION = (386, 90, 880, 348)
DEFAULT_NORMAL_GROUP_CONFIDENCE = 0.75


@dataclass(frozen=True)
class HandoffElementPaths:
    group_search_input: Path
    select_search_type_group: Path
    normal_group_image: Path
    group_settings_button: Path
    add_member_button: Path

    @classmethod
    def from_dir(cls, elements_dir: Path) -> "HandoffElementPaths":
        return cls(
            group_search_input=elements_dir / "group_search_input.json",
            select_search_type_group=elements_dir / "select_search_type_group.json",
            normal_group_image=elements_dir / "normal_group.png",
            group_settings_button=elements_dir / "group_settings_button.json",
            add_member_button=elements_dir / "add_member_button.json",
        )


class DingtalkGroupHandoffSmokeRunner:
    def __init__(
        self,
        uia_driver: Any,
        gui_backend: Any,
        clipboard_backend: Any,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._uia_driver = uia_driver
        self._gui = gui_backend
        self._clipboard = clipboard_backend
        self._sleep = sleep

    def run(
        self,
        group_name: str,
        paths: HandoffElementPaths,
        search_region: Tuple[int, int, int, int] = DEFAULT_SEARCH_REGION,
        normal_group_confidence: float = DEFAULT_NORMAL_GROUP_CONFIDENCE,
        search_click_mode: str = "auto",
        settings_click_mode: str = "auto",
        add_member_click_mode: str = "auto",
        settings_position: Optional[Tuple[int, int]] = None,
        add_member_position: Optional[Tuple[int, int]] = None,
        step_delay_seconds: float = 0.8,
        stop_before_add_member: bool = False,
    ) -> None:
        self.click_collected_path(paths.group_search_input, click_mode=search_click_mode)
        self.paste_search_text(group_name)
        self._sleep(step_delay_seconds)

        self.click_collected_path(paths.select_search_type_group, click_mode="position")
        self._sleep(step_delay_seconds)

        self.click_image(
            paths.normal_group_image,
            confidence=normal_group_confidence,
            region=search_region,
        )
        self._sleep(step_delay_seconds)

        self.click_collected_path(
            paths.group_settings_button,
            click_mode=settings_click_mode,
            override_position=settings_position,
        )
        self._sleep(step_delay_seconds)

        if stop_before_add_member:
            return
        self.click_collected_path(
            paths.add_member_button,
            click_mode=add_member_click_mode,
            override_position=add_member_position,
        )

    def paste_search_text(self, group_name: str) -> None:
        self._clipboard.copy(group_name)
        self._gui.hotkey("ctrl", "a")
        self._gui.hotkey("ctrl", "v")

    def click_collected_path(
        self,
        path: Path,
        click_mode: str = "auto",
        override_position: Optional[Tuple[int, int]] = None,
    ) -> None:
        self.click_collected_config(
            _read_json(path),
            click_mode=click_mode,
            override_position=override_position,
        )

    def click_collected_config(
        self,
        config: Dict[str, Any],
        click_mode: str = "auto",
        override_position: Optional[Tuple[int, int]] = None,
    ) -> None:
        if override_position is not None:
            self._click_position(override_position)
            return
        if click_mode == "position" or _is_generic_large_panel_capture(config):
            self._click_position(_fallback_position(config))
            return
        if click_mode == "uia":
            self._uia_driver.click_element(config["target"])
            return
        if click_mode != "auto":
            raise ValueError("Unsupported click_mode: %s" % click_mode)

        try:
            self._uia_driver.click_element(config["target"])
        except Exception:
            self._click_position(_fallback_position(config))

    def click_image(
        self,
        image_path: Path,
        confidence: float,
        region: Tuple[int, int, int, int],
    ) -> None:
        try:
            box = self._gui.locateOnScreen(
                str(image_path),
                confidence=confidence,
                region=region,
            )
        except Exception as exc:
            if exc.__class__.__name__ != "ImageNotFoundException":
                raise
            box = None
        if box is None:
            raise LookupError("Image not found: %s" % image_path)
        self._click_position(_box_center(box))

    def _click_position(self, position: Tuple[int, int]) -> None:
        self._uia_driver.click_position(position[0], position[1])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the local DingTalk group handoff smoke chain on Windows."
    )
    parser.add_argument("--elements-dir", default=str(DEFAULT_ELEMENTS_DIR))
    parser.add_argument("--group-name", default=DEFAULT_GROUP_NAME)
    parser.add_argument("--search-region", default=_format_region(DEFAULT_SEARCH_REGION))
    parser.add_argument("--normal-group-confidence", type=float, default=DEFAULT_NORMAL_GROUP_CONFIDENCE)
    parser.add_argument("--search-click-mode", choices=("auto", "uia", "position"), default="auto")
    parser.add_argument("--settings-click-mode", choices=("auto", "uia", "position"), default="auto")
    parser.add_argument("--add-member-click-mode", choices=("auto", "uia", "position"), default="auto")
    parser.add_argument("--settings-position", default="")
    parser.add_argument("--add-member-position", default="")
    parser.add_argument("--pause-before-start", type=float, default=3.0)
    parser.add_argument("--step-delay", type=float, default=0.8)
    parser.add_argument("--stop-before-add-member", action="store_true")
    args = parser.parse_args(argv)

    import pyautogui  # type: ignore
    import pyperclip  # type: ignore

    elements_dir = Path(args.elements_dir)
    paths = HandoffElementPaths.from_dir(elements_dir)
    _validate_paths(paths)

    if args.pause_before_start > 0:
        print("Starting in %.1f seconds. Keep DingTalk visible." % args.pause_before_start)
        time.sleep(args.pause_before_start)

    runner = DingtalkGroupHandoffSmokeRunner(
        uia_driver=UiaAutomationDriver(),
        gui_backend=pyautogui,
        clipboard_backend=pyperclip,
    )
    runner.run(
        group_name=args.group_name,
        paths=paths,
        search_region=_parse_region(args.search_region),
        normal_group_confidence=args.normal_group_confidence,
        search_click_mode=args.search_click_mode,
        settings_click_mode=args.settings_click_mode,
        add_member_click_mode=args.add_member_click_mode,
        settings_position=_parse_optional_position(args.settings_position),
        add_member_position=_parse_optional_position(args.add_member_position),
        step_delay_seconds=args.step_delay,
        stop_before_add_member=args.stop_before_add_member,
    )
    print("DingTalk group handoff smoke chain completed.")
    return 0


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_paths(paths: HandoffElementPaths) -> None:
    for path in (
        paths.group_search_input,
        paths.select_search_type_group,
        paths.normal_group_image,
        paths.group_settings_button,
        paths.add_member_button,
    ):
        if not path.exists():
            raise FileNotFoundError(str(path))


def _fallback_position(config: Dict[str, Any]) -> Tuple[int, int]:
    position = config.get("fallback_position")
    if not isinstance(position, dict):
        raise ValueError("fallback_position is required for position click")
    return int(position["x"]), int(position["y"])


def _box_center(box: Any) -> Tuple[int, int]:
    left = int(getattr(box, "left", box[0] if isinstance(box, (list, tuple)) else 0))
    top = int(getattr(box, "top", box[1] if isinstance(box, (list, tuple)) else 0))
    width = int(getattr(box, "width", box[2] if isinstance(box, (list, tuple)) else 0))
    height = int(getattr(box, "height", box[3] if isinstance(box, (list, tuple)) else 0))
    return int(left + width / 2), int(top + height / 2)


def _is_generic_large_panel_capture(config: Dict[str, Any]) -> bool:
    target = config.get("target")
    if not isinstance(target, dict):
        return False
    class_name = str(target.get("class_name", "")).lower()
    control_type = str(target.get("control_type", "")).lower()
    name = str(target.get("name", "")).strip()
    rect = target.get("bounding_rect_hint")
    if not isinstance(rect, list) or len(rect) != 4:
        return False
    left, top, right, bottom = [int(value) for value in rect]
    width = right - left
    height = bottom - top
    is_generic_panel = "chrome_renderwidgethosthwnd" in class_name or "pane" in control_type
    return is_generic_panel and not name and (width >= 300 or height >= 200)


def _parse_region(raw: str) -> Tuple[int, int, int, int]:
    values = _parse_int_csv(raw, expected=4, label="region")
    return values[0], values[1], values[2], values[3]


def _parse_optional_position(raw: str) -> Optional[Tuple[int, int]]:
    if not raw:
        return None
    values = _parse_int_csv(raw, expected=2, label="position")
    return values[0], values[1]


def _parse_int_csv(raw: str, expected: int, label: str) -> Tuple[int, ...]:
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if len(values) != expected:
        raise ValueError("%s must contain %s comma-separated integers" % (label, expected))
    return values


def _format_region(region: Tuple[int, int, int, int]) -> str:
    return ",".join(str(value) for value in region)


if __name__ == "__main__":
    raise SystemExit(main())
