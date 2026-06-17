import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


class WecomBindCookieCaptureTest(unittest.TestCase):
    def test_default_cookie_capture_paths_stay_under_local(self):
        from scripts.dev.capture_wecom_bind_cookies import default_capture_paths

        paths = default_capture_paths(Path("/repo"))

        self.assertEqual(paths["profile_dir"], Path("/repo/.local/wecom-bind-browser-profile"))
        self.assertEqual(paths["node_work_dir"], Path("/repo/.local/playwright-cookie-capture"))
        self.assertEqual(paths["jdy_cookie_file"], Path("/repo/.local/jdy-admin.cookie"))
        self.assertEqual(paths["wecom_cookie_file"], Path("/repo/.local/wecom-admin.cookie"))

    def test_default_jdy_entry_uses_wework_bind_page(self):
        from scripts.dev.capture_wecom_bind_cookies import JDY_URL

        self.assertEqual(JDY_URL, "https://dc.jdydevelop.com/fx_sa/wework_bind")

    def test_write_cookie_file_creates_parent_and_uses_owner_only_permissions(self):
        from scripts.dev.capture_wecom_bind_cookies import write_cookie_file

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / ".local" / "jdy.cookie"

            write_cookie_file(target, "sid=secret; vst=secret")

            self.assertEqual(target.read_text(encoding="utf-8"), "sid=secret; vst=secret")
            mode = stat.S_IMODE(target.stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_main_fake_capture_writes_cookies_and_prints_only_paths(self):
        from scripts.dev.capture_wecom_bind_cookies import main

        with tempfile.TemporaryDirectory() as tmpdir:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--repo-root",
                        tmpdir,
                        "--use-fake-capture-for-test",
                    ]
                )

            printed = output.getvalue()
            data = json.loads(printed)
            jdy_cookie_file = Path(data["jdy_cookie_file"])
            wecom_cookie_file = Path(data["wecom_cookie_file"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["status"], "cookies_saved")
            self.assertTrue(jdy_cookie_file.exists())
            self.assertTrue(wecom_cookie_file.exists())
            self.assertNotIn("jdy_sid_secret", printed)
            self.assertNotIn("wecom_sid_secret", printed)
            self.assertEqual(jdy_cookie_file.read_text(encoding="utf-8"), "sid=jdy_sid_secret")
            self.assertEqual(wecom_cookie_file.read_text(encoding="utf-8"), "wwrtx.sid=fake_sid")

    def test_main_can_run_readonly_preflight_after_fake_capture(self):
        from scripts.dev.capture_wecom_bind_cookies import main

        with tempfile.TemporaryDirectory() as tmpdir:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--repo-root",
                        tmpdir,
                        "--use-fake-capture-for-test",
                        "--assume-logged-in",
                        "--run-preflight",
                        "--enterprise-name",
                        "上海测试客户",
                        "--plain-corp-id",
                        "ww-plain-secret",
                        "--requested-user-id",
                        "user-1",
                        "--use-fake-preflight-for-test",
                    ]
                )

            data = json.loads(output.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["status"], "cookies_saved")
            self.assertEqual(data["preflight"]["status"], "ok")
            self.assertEqual(os.environ.get("JDY_ADMIN_COOKIE_FILE"), None)

    def test_main_accepts_assume_logged_in_flag_for_export_only_flow(self):
        from scripts.dev.capture_wecom_bind_cookies import main

        with tempfile.TemporaryDirectory() as tmpdir:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--repo-root",
                        tmpdir,
                        "--use-fake-capture-for-test",
                        "--assume-logged-in",
                        "--auto-wait-seconds",
                        "5",
                    ]
                )

            data = json.loads(output.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["status"], "cookies_saved")

    def test_npm_install_command_uses_cmd_shim_on_windows(self):
        from scripts.dev import capture_wecom_bind_cookies as script

        with mock.patch.object(script.os, "name", "nt"):
            self.assertEqual(script._npm_install_command()[0], "npm.cmd")

        with mock.patch.object(script.os, "name", "posix"):
            self.assertEqual(script._npm_install_command()[0], "npm")


if __name__ == "__main__":
    unittest.main()
