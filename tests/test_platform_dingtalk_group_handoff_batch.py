import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from openpyxl import Workbook, load_workbook

from rpa_platform.worker.dingtalk_group_handoff_batch import (
    BatchOptions,
    DingtalkGroupHandoffBatchRunner,
)


class DingtalkGroupHandoffBatchTest(unittest.TestCase):
    def test_processes_non_empty_groups_writes_status_and_continues_after_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = _write_workbook(
                Path(tmpdir) / "groups.xlsx",
                [
                    ("群名称", "群状态"),
                    ("群A", ""),
                    ("", ""),
                    ("群B", ""),
                    ("群C", ""),
                ],
            )
            backend = _FakeHandoffBackend(
                {
                    "群A": "添加成功",
                    "群B": RuntimeError("添加成员入口失败"),
                    "群C": "成员已在群内",
                }
            )

            result = DingtalkGroupHandoffBatchRunner(backend).run(
                BatchOptions(workbook=workbook)
            )

            self.assertEqual(result.processed_count, 3)
            self.assertEqual(result.failed_count, 1)
            self.assertEqual(backend.calls, [("群A", "季钰杰"), ("群B", "季钰杰"), ("群C", "季钰杰")])
            self.assertEqual(_column_values(workbook, "B", 2, 5), ["添加成功", None, "异常：添加成员入口失败", "成员已在群内"])

    def test_skip_completed_and_limit_apply_before_gui_work(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = _write_workbook(
                Path(tmpdir) / "groups.xlsx",
                [
                    ("群名称", "群状态"),
                    ("已完成群", "添加成功"),
                    ("群A", ""),
                    ("群B", ""),
                    ("群C", ""),
                ],
            )
            backend = _FakeHandoffBackend({"群A": "群不存在", "群B": "添加成功", "群C": "添加成功"})

            result = DingtalkGroupHandoffBatchRunner(backend).run(
                BatchOptions(workbook=workbook, skip_completed=True, limit=2)
            )

            self.assertEqual(result.processed_count, 2)
            self.assertEqual(backend.calls, [("群A", "季钰杰"), ("群B", "季钰杰")])
            self.assertEqual(_column_values(workbook, "B", 2, 5), ["添加成功", "群不存在", "添加成功", None])

    def test_dry_run_lists_groups_without_writing_or_clicking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = _write_workbook(
                Path(tmpdir) / "groups.xlsx",
                [
                    ("群名称", "群状态"),
                    ("群A", ""),
                    ("群B", ""),
                ],
            )
            backend = _FakeHandoffBackend({"群A": "添加成功", "群B": "添加成功"})

            result = DingtalkGroupHandoffBatchRunner(backend).run(
                BatchOptions(workbook=workbook, dry_run=True)
            )

            self.assertEqual(result.processed_count, 0)
            self.assertEqual(result.planned_groups, ["群A", "群B"])
            self.assertEqual(backend.calls, [])
            self.assertEqual(_column_values(workbook, "B", 2, 3), [None, None])

    def test_dev_script_entrypoint_supports_dry_run_limit(self):
        from scripts.dev.run_dingtalk_group_handoff_batch import main

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = _write_workbook(
                Path(tmpdir) / "groups.xlsx",
                [
                    ("群名称", "群状态"),
                    ("群A", ""),
                    ("群B", ""),
                ],
            )
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(["--workbook", str(workbook), "--dry-run", "--limit", "1"])

            self.assertEqual(exit_code, 0)
            self.assertIn("1. 群A", output.getvalue())
            self.assertNotIn("群B", output.getvalue())
            self.assertEqual(_column_values(workbook, "B", 2, 3), [None, None])


class _FakeHandoffBackend:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def handoff_group(self, group_name, member_name):
        self.calls.append((group_name, member_name))
        outcome = self.outcomes[group_name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _write_workbook(path: Path, rows) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def _column_values(path: Path, column: str, start: int, end: int):
    workbook = load_workbook(path)
    sheet = workbook["Sheet1"]
    return [sheet[f"{column}{row}"].value for row in range(start, end + 1)]


if __name__ == "__main__":
    unittest.main()
