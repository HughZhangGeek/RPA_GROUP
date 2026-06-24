import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Protocol, Tuple

from openpyxl import load_workbook

from rpa_platform.worker.dingtalk_group_handoff import (
    DEFAULT_ELEMENTS_DIR,
    DEFAULT_NORMAL_GROUP_CONFIDENCE,
    DEFAULT_SEARCH_REGION,
    DingtalkGroupHandoffSmokeRunner,
    HandoffElementPaths,
)
from rpa_platform.worker.uia_driver import UiaAutomationDriver


DEFAULT_WORKBOOK = DEFAULT_ELEMENTS_DIR / "需要转交的群.xlsx"
DEFAULT_MEMBER_NAME = "\u5b63\u94b0\u6770"
DEFAULT_MEMBER_ALREADY_IN_REGION = (600, 300, 600, 200)
DEFAULT_MEMBER_ALREADY_IN_CONFIDENCE = 0.70
DEFAULT_SETTINGS_POSITION = (1874, 66)
DEFAULT_CONFIRM_POSITION = (700, 805)
DEFAULT_ADD_MEMBER_POSITION = (1613, 243)

STATUS_SUCCESS = "添加成功"
STATUS_MEMBER_ALREADY_IN = "成员已在群内"
STATUS_GROUP_NOT_FOUND = "群不存在"
STATUS_ADD_MEMBER_ENTRY_FAILED = "添加成员入口失败"
STATUS_CONFIRM_NOT_CLICKED = "确认按钮未点击"


class GroupHandoffBackend(Protocol):
    def handoff_group(self, group_name: str, member_name: str) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class BatchOptions:
    workbook: Path = DEFAULT_WORKBOOK
    sheet: str = "Sheet1"
    member_name: str = DEFAULT_MEMBER_NAME
    start_row: int = 2
    limit: Optional[int] = None
    dry_run: bool = False
    skip_completed: bool = False
    save_every: int = 1


@dataclass(frozen=True)
class BatchRowResult:
    row: int
    group_name: str
    status: str


@dataclass(frozen=True)
class BatchResult:
    processed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    planned_groups: List[str] = field(default_factory=list)
    rows: List[BatchRowResult] = field(default_factory=list)


class DingtalkGroupHandoffBatchRunner:
    def __init__(self, backend: GroupHandoffBackend) -> None:
        self._backend = backend

    def run(self, options: BatchOptions) -> BatchResult:
        workbook_path = Path(options.workbook)
        workbook = load_workbook(workbook_path)
        sheet = workbook[options.sheet]

        processed = 0
        failed = 0
        skipped = 0
        planned_groups: List[str] = []
        rows: List[BatchRowResult] = []
        changed_since_save = 0

        for row_number in range(int(options.start_row), sheet.max_row + 1):
            group_name = _cell_text(sheet.cell(row=row_number, column=1).value)
            if not group_name:
                continue
            status_cell = sheet.cell(row=row_number, column=2)
            if options.skip_completed and _cell_text(status_cell.value):
                skipped += 1
                continue
            if options.limit is not None and (processed + len(planned_groups)) >= options.limit:
                break

            if options.dry_run:
                planned_groups.append(group_name)
                continue

            try:
                status = self._backend.handoff_group(group_name, options.member_name)
            except Exception as exc:
                _try_close_dialogs(self._backend)
                status = "异常：%s" % _short_error(exc)

            status_cell.value = status
            rows.append(BatchRowResult(row=row_number, group_name=group_name, status=status))
            processed += 1
            if _is_failure_status(status):
                failed += 1
            changed_since_save += 1
            if changed_since_save >= max(int(options.save_every), 1):
                workbook.save(workbook_path)
                changed_since_save = 0

        if changed_since_save:
            workbook.save(workbook_path)

        return BatchResult(
            processed_count=processed,
            failed_count=failed,
            skipped_count=skipped,
            planned_groups=planned_groups,
            rows=rows,
        )


class DingtalkGroupHandoffGuiBackend:
    def __init__(
        self,
        elements_dir: Path = DEFAULT_ELEMENTS_DIR,
        uia_driver: Any = None,
        gui_backend: Any = None,
        clipboard_backend: Any = None,
        sleep: Any = time.sleep,
        search_region: Tuple[int, int, int, int] = DEFAULT_SEARCH_REGION,
        normal_group_confidence: float = DEFAULT_NORMAL_GROUP_CONFIDENCE,
        member_already_in_region: Tuple[int, int, int, int] = DEFAULT_MEMBER_ALREADY_IN_REGION,
        member_already_in_confidence: float = DEFAULT_MEMBER_ALREADY_IN_CONFIDENCE,
        settings_position: Tuple[int, int] = DEFAULT_SETTINGS_POSITION,
        confirm_position: Tuple[int, int] = DEFAULT_CONFIRM_POSITION,
        add_member_position: Tuple[int, int] = DEFAULT_ADD_MEMBER_POSITION,
        step_delay_seconds: float = 0.8,
    ) -> None:
        if gui_backend is None:
            import pyautogui  # type: ignore

            gui_backend = pyautogui
        if clipboard_backend is None:
            import pyperclip  # type: ignore

            clipboard_backend = pyperclip

        self._paths = HandoffElementPaths.from_dir(Path(elements_dir))
        self._member_already_in_image = Path(elements_dir) / "member_already_in.png"
        self._uia_driver = uia_driver or UiaAutomationDriver()
        self._gui = gui_backend
        self._clipboard = clipboard_backend
        self._sleep = sleep
        self._search_region = search_region
        self._normal_group_confidence = normal_group_confidence
        self._member_already_in_region = member_already_in_region
        self._member_already_in_confidence = member_already_in_confidence
        self._settings_position = settings_position
        self._confirm_position = confirm_position
        self._add_member_position = add_member_position
        self._step_delay_seconds = step_delay_seconds
        self._smoke_runner = DingtalkGroupHandoffSmokeRunner(
            uia_driver=self._uia_driver,
            gui_backend=self._gui,
            clipboard_backend=self._clipboard,
            sleep=self._sleep,
        )

    def handoff_group(self, group_name: str, member_name: str) -> str:
        self._smoke_runner.click_collected_path(
            self._paths.group_search_input,
            click_mode="position",
        )
        self._smoke_runner.paste_search_text(group_name)
        self._sleep(self._step_delay_seconds)

        self._smoke_runner.click_collected_path(
            self._paths.select_search_type_group,
            click_mode="position",
        )
        self._sleep(self._step_delay_seconds)

        if not self._click_image_if_present(
            self._paths.normal_group_image,
            confidence=self._normal_group_confidence,
            region=self._search_region,
        ):
            self.close_active_dialogs()
            return STATUS_GROUP_NOT_FOUND
        self._sleep(self._step_delay_seconds)

        self._uia_driver.click_position(*self._settings_position)
        self._sleep(self._step_delay_seconds)

        try:
            self._smoke_runner.click_collected_path(
                self._paths.add_member_button,
                override_position=self._add_member_position,
            )
        except Exception:
            self.close_active_dialogs()
            return STATUS_ADD_MEMBER_ENTRY_FAILED
        self._sleep(self._step_delay_seconds)

        self._clipboard.copy(member_name)
        self._gui.hotkey("ctrl", "a")
        self._gui.hotkey("ctrl", "v")
        self._press("enter")
        self._sleep(self._step_delay_seconds)

        if self._click_image_if_present(
            self._member_already_in_image,
            confidence=self._member_already_in_confidence,
            region=self._member_already_in_region,
            click=False,
        ):
            self.close_active_dialogs()
            return STATUS_MEMBER_ALREADY_IN

        try:
            self._uia_driver.click_position(*self._confirm_position)
        except Exception:
            self.close_active_dialogs()
            return STATUS_CONFIRM_NOT_CLICKED
        self._sleep(self._step_delay_seconds)
        return STATUS_SUCCESS

    def close_active_dialogs(self) -> None:
        self._press("esc")
        self._sleep(0.2)

    def _click_image_if_present(
        self,
        image_path: Path,
        confidence: float,
        region: Tuple[int, int, int, int],
        click: bool = True,
    ) -> bool:
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
            return False
        if click:
            self._uia_driver.click_position(*_box_center(box))
        return True

    def _press(self, key: str) -> None:
        if hasattr(self._gui, "press"):
            self._gui.press(key)
            return
        self._gui.hotkey(key)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch add a DingTalk handoff member from an Excel workbook."
    )
    parser.add_argument("--workbook", default=str(DEFAULT_WORKBOOK))
    parser.add_argument("--sheet", default="Sheet1")
    parser.add_argument("--member-name", default=DEFAULT_MEMBER_NAME)
    parser.add_argument("--start-row", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-completed", action="store_true")
    parser.add_argument("--save-every", type=int, default=1)
    parser.add_argument("--elements-dir", default=str(DEFAULT_ELEMENTS_DIR))
    parser.add_argument("--pause-before-start", type=float, default=3.0)
    parser.add_argument("--step-delay", type=float, default=0.8)
    args = parser.parse_args(argv)

    options = BatchOptions(
        workbook=Path(args.workbook),
        sheet=args.sheet,
        member_name=args.member_name,
        start_row=args.start_row,
        limit=args.limit,
        dry_run=args.dry_run,
        skip_completed=args.skip_completed,
        save_every=args.save_every,
    )
    if args.dry_run:
        backend: GroupHandoffBackend = _DryRunBackend()
    else:
        _validate_local_assets(Path(args.elements_dir))
        if args.pause_before_start > 0:
            print(
                "Starting in %.1f seconds. Keep DingTalk visible and move the local "
                "mouse out of the RDP window." % args.pause_before_start
            )
            time.sleep(args.pause_before_start)
        backend = DingtalkGroupHandoffGuiBackend(
            elements_dir=Path(args.elements_dir),
            step_delay_seconds=args.step_delay,
        )

    result = DingtalkGroupHandoffBatchRunner(backend).run(options)
    if args.dry_run:
        for index, group_name in enumerate(result.planned_groups, start=1):
            print("%s. %s" % (index, group_name))
    else:
        print(
            "processed=%s failed=%s skipped=%s workbook=%s"
            % (result.processed_count, result.failed_count, result.skipped_count, options.workbook)
        )
    return 0


class _DryRunBackend:
    def handoff_group(self, group_name: str, member_name: str) -> str:
        raise RuntimeError("dry-run backend should not be called")


def _cell_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _short_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:60]


def _is_failure_status(status: str) -> bool:
    return status.startswith("异常：") or status in {
        STATUS_ADD_MEMBER_ENTRY_FAILED,
        STATUS_CONFIRM_NOT_CLICKED,
    }


def _try_close_dialogs(backend: Any) -> None:
    close = getattr(backend, "close_active_dialogs", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        return


def _validate_local_assets(elements_dir: Path) -> None:
    paths = HandoffElementPaths.from_dir(elements_dir)
    required = [
        paths.group_search_input,
        paths.select_search_type_group,
        paths.normal_group_image,
        paths.add_member_button,
        elements_dir / "member_already_in.png",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing DingTalk handoff assets: %s" % ", ".join(missing))


def _box_center(box: Any) -> Tuple[int, int]:
    left = int(getattr(box, "left", box[0] if isinstance(box, (list, tuple)) else 0))
    top = int(getattr(box, "top", box[1] if isinstance(box, (list, tuple)) else 0))
    width = int(getattr(box, "width", box[2] if isinstance(box, (list, tuple)) else 0))
    height = int(getattr(box, "height", box[3] if isinstance(box, (list, tuple)) else 0))
    return int(left + width / 2), int(top + height / 2)


if __name__ == "__main__":
    raise SystemExit(main())
