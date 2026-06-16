import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus


class PlatformDryRunSmokeTest(unittest.TestCase):
    def test_default_db_path_is_persistent_workspace_local_file(self):
        from scripts.dev.run_platform_dryrun import default_dryrun_db_path

        path = default_dryrun_db_path()

        self.assertTrue(path.is_absolute())
        self.assertEqual(path.name, "platform-dryrun.db")
        self.assertEqual(path.parent.name, ".local")

    def test_dryrun_reaches_waiting_review_and_redacts_secrets(self):
        from scripts.dev.run_platform_dryrun import run_dryrun

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_dryrun(db_path=str(Path(tmpdir) / "platform-dryrun.db"))

        detail = result["task_detail"]
        serialized = json.dumps(result, ensure_ascii=False)
        step_keys = [step["step_key"] for step in detail["steps"]]

        self.assertEqual(result["runner_result"]["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertTrue(result["scheduler_result"]["claimed"])
        self.assertEqual(result["scheduler_result"]["task_id"], result["task_id"])
        self.assertEqual(detail["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(detail["current_step_key"], "wecom_submit_review")
        self.assertEqual(
            step_keys,
            [
                "jdy_resolve_corp",
                "derive_wecom_urls",
                "wecom_configure_app",
                "jdy_check_owner",
                "jdy_install_bind",
                "wecom_submit_review",
            ],
        )
        self.assertNotIn("fake-token", serialized)
        self.assertNotIn("fake-aes-key", serialized)
        self.assertIn("***", detail["runtime_context"]["wecom"]["token"])
        self.assertIn("***", detail["runtime_context"]["wecom"]["encoding_aes_key"])

    def test_main_prints_redacted_task_detail(self):
        from scripts.dev.run_platform_dryrun import main

        with tempfile.TemporaryDirectory() as tmpdir:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--db-path", str(Path(tmpdir) / "platform-dryrun.db")])

        printed = output.getvalue()
        data = json.loads(printed)
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["task_detail"]["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertNotIn("fake-token", printed)
        self.assertNotIn("fake-aes-key", printed)

    def test_service_dryrun_reaches_online_delay_and_redacts_secrets(self):
        from scripts.dev.run_platform_dryrun import run_wecom_bind_service_dryrun

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_wecom_bind_service_dryrun(db_path=str(Path(tmpdir) / "service.db"))

        detail = result["task_detail"]
        serialized = json.dumps(result, ensure_ascii=False)

        self.assertEqual(result["runner_result"]["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertTrue(result["scheduler_result"]["claimed"])
        self.assertEqual(result["scheduler_result"]["task_id"], result["task_id"])
        self.assertEqual(detail["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(detail["current_step_key"], "jdy_wecom_bind_service")
        self.assertIn("order-1", serialized)
        self.assertIn("***", serialized)
        self.assertNotIn("token-secret", serialized)
        self.assertNotIn("aes-secret", serialized)

    def test_service_dryrun_main_mode_prints_redacted_task_detail(self):
        from scripts.dev.run_platform_dryrun import main

        with tempfile.TemporaryDirectory() as tmpdir:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--mode",
                        "wecom-bind-service",
                        "--db-path",
                        str(Path(tmpdir) / "service.db"),
                    ]
                )

        printed = output.getvalue()
        data = json.loads(printed)
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["task_detail"]["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertNotIn("token-secret", printed)
        self.assertNotIn("aes-secret", printed)

    def test_script_path_entrypoint_prints_redacted_task_detail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/dev/run_platform_dryrun.py",
                    "--db-path",
                    str(Path(tmpdir) / "platform-dryrun.db"),
                ],
                cwd=str(Path(__file__).resolve().parents[1]),
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertEqual(data["task_detail"]["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertNotIn("fake-token", completed.stdout)
        self.assertNotIn("fake-aes-key", completed.stdout)

    def test_prepare_only_then_worker_once_claims_existing_task(self):
        from scripts.dev.run_platform_dryrun import prepare_dryrun
        from scripts.dev.run_platform_worker_once import run_worker_once

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "platform-dryrun.db")
            prepared = prepare_dryrun(db_path=db_path, reset=True)
            result = run_worker_once(db_path=db_path)

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(prepared["task_detail"]["status"], TaskStatus.PENDING.value)
        self.assertTrue(result["scheduler_result"]["claimed"])
        self.assertEqual(result["task_detail"]["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(result["task_detail"]["current_step_key"], "wecom_submit_review")
        self.assertNotIn("fake-token", serialized)
        self.assertNotIn("fake-aes-key", serialized)

    def test_worker_once_script_path_claims_existing_task(self):
        from scripts.dev.run_platform_dryrun import prepare_dryrun

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "platform-dryrun.db")
            prepare_dryrun(db_path=db_path, reset=True)
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/dev/run_platform_worker_once.py",
                    "--db-path",
                    db_path,
                ],
                cwd=str(Path(__file__).resolve().parents[1]),
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertTrue(data["scheduler_result"]["claimed"])
        self.assertEqual(data["task_detail"]["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertNotIn("fake-token", completed.stdout)
        self.assertNotIn("fake-aes-key", completed.stdout)


if __name__ == "__main__":
    unittest.main()
