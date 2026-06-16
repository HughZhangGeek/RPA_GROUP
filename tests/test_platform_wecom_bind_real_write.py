import io
import json
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


class RealWriteScriptTest(unittest.TestCase):
    def test_main_requires_confirm_write_before_any_write(self):
        from scripts.dev.run_wecom_bind_real_write import main

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--enterprise-name",
                        "上海测试客户",
                        "--enterprise-short-name",
                        "上海测试客户",
                        "--plain-corp-id",
                        "ww001",
                        "--requested-user-id",
                        "user-1",
                        "--context-file",
                        str(Path(tmpdir) / "context.json"),
                        "--use-fake-transport-for-test",
                        "--wait-seconds",
                        "0",
                    ]
                )

        data = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(data["status"], "blocked")
        self.assertEqual(data["reason"], "missing_confirm_write")

    def test_main_fake_write_runs_full_flow_and_redacts_secrets(self):
        from scripts.dev.run_wecom_bind_real_write import main

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            context_file = Path(tmpdir) / "context.json"
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--enterprise-name",
                        "上海测试客户",
                        "--enterprise-short-name",
                        "上海测试客户",
                        "--plain-corp-id",
                        "ww001",
                        "--requested-user-id",
                        "user-1",
                        "--context-file",
                        str(context_file),
                        "--use-fake-transport-for-test",
                        "--wait-seconds",
                        "0",
                        "--confirm-write",
                    ]
                )

            printed = output.getvalue()
            data = json.loads(printed)
            context = json.loads(context_file.read_text(encoding="utf-8"))
            context_mode = stat.S_IMODE(context_file.stat().st_mode)

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["start_result"]["status"], "waiting_wecom_online_delay")
        self.assertEqual(data["submit_result"]["status"], "success")
        self.assertNotIn("token-secret", printed)
        self.assertNotIn("aes-secret", printed)
        self.assertEqual(context["wecom"]["token"], "token-secret")
        self.assertEqual(context["wecom"]["encoding_aes_key"], "aes-secret")
        self.assertEqual(context["wecom"]["auditorder_status"], 5)
        self.assertEqual(context_mode, 0o600)

    def test_main_continues_when_wecom_save_response_omits_corpapp_but_list_confirms_fields(self):
        from scripts.dev import run_wecom_bind_real_write as script
        from scripts.dev.run_platform_dryrun import FakeServiceWecomAdminTransport

        class MissingCorpappSaveResponseTransport(FakeServiceWecomAdminTransport):
            def __init__(self):
                super().__init__()
                self.saved_corpapp = None

            def get_json(self, path, params, headers):
                response = super().get_json(path, params, headers)
                if (
                    path == "/wwopen/developer/customApp/tpl/app/list"
                    and self.saved_corpapp is not None
                ):
                    row = response["data"]["corpapp"][0]
                    row.update(
                        {
                            "homeurl": self.saved_corpapp["homeurl"],
                            "callbackurl": self.saved_corpapp["callbackurl"],
                            "token": self.saved_corpapp["token"],
                            "aeskey": self.saved_corpapp["aeskey"],
                            "redirect_domain": self.saved_corpapp["redirect_domain"],
                        }
                    )
                return response

            def post_json(self, path, payload, headers):
                if (
                    path == "/wwopen/developer/customApp/tpl/corpApp"
                    and "token" in payload.get("corpapp", {})
                ):
                    self.calls.append(
                        {"method": "POST", "path": path, "payload": dict(payload), "headers": dict(headers)}
                    )
                    self.saved_corpapp = dict(payload["corpapp"])
                    return {"data": {}}
                return super().post_json(path, payload, headers)

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            context_file = Path(tmpdir) / "context.json"
            with patch.object(script, "FakeServiceWecomAdminTransport", MissingCorpappSaveResponseTransport):
                with redirect_stdout(output):
                    exit_code = script.main(
                        [
                            "--enterprise-name",
                            "上海测试客户",
                            "--enterprise-short-name",
                            "上海测试客户",
                            "--plain-corp-id",
                            "ww001",
                            "--requested-user-id",
                            "user-1",
                            "--context-file",
                            str(context_file),
                            "--use-fake-transport-for-test",
                            "--wait-seconds",
                            "0",
                            "--confirm-write",
                        ]
                    )

            printed = output.getvalue()
            data = json.loads(printed)
            context = json.loads(context_file.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["start_result"]["status"], "waiting_wecom_online_delay")
        self.assertEqual(context["wecom"]["token"], "token-secret")
        self.assertNotIn("token-secret", printed)
        self.assertNotIn("aes-secret", printed)

    def test_main_allows_confirmed_review_preflight_for_owner_update_recovery(self):
        from scripts.dev import run_wecom_bind_real_write as script
        from scripts.dev.run_platform_dryrun import FakeServiceJdyAdminTransport

        class OwnerCanUpdateTransport(FakeServiceJdyAdminTransport):
            def post_json(self, path, payload):
                if path == "/api/fx_sa/wxwork/get_owner":
                    self.calls.append({"path": path, "payload": dict(payload)})
                    return {"can_bind_corp_secret": False, "can_update_corp_secret": True}
                return super().post_json(path, payload)

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            context_file = Path(tmpdir) / "context.json"
            with patch.object(script, "FakeServiceJdyAdminTransport", OwnerCanUpdateTransport):
                with redirect_stdout(output):
                    exit_code = script.main(
                        [
                            "--enterprise-name",
                            "上海测试客户",
                            "--enterprise-short-name",
                            "上海测试客户",
                            "--plain-corp-id",
                            "ww001",
                            "--requested-user-id",
                            "user-1",
                            "--context-file",
                            str(context_file),
                            "--use-fake-transport-for-test",
                            "--wait-seconds",
                            "0",
                            "--confirm-write",
                        ]
                    )

            data = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["preflight"]["status"], "review")
        self.assertEqual(data["preflight"]["jdy"]["owner_state"], "can_update_corp_secret")

    def test_main_recovers_jdy_corp_from_owner_when_bound_corp_is_missing_from_list(self):
        from scripts.dev import run_wecom_bind_real_write as script
        from scripts.dev.run_platform_dryrun import FakeServiceJdyAdminTransport, FakeServiceWecomAdminTransport

        class MissingListOwnerRecoveryTransport(FakeServiceJdyAdminTransport):
            def post_json(self, path, payload):
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    self.calls.append({"path": path, "payload": dict(payload)})
                    return {"has_more": False, "corp_deploy_list": []}
                if path == "/api/fx_sa/wxwork/get_owner":
                    self.calls.append({"path": path, "payload": dict(payload)})
                    return {
                        "can_bind_corp_secret": False,
                        "can_update_corp_secret": True,
                        "owner": {"corp_id": "corp-secret-from-owner"},
                        "corp": {"name": "南京示例集团"},
                    }
                return super().post_json(path, payload)

        class ShortNameWecomTransport(FakeServiceWecomAdminTransport):
            def get_json(self, path, params, headers):
                response = super().get_json(path, params, headers)
                if path == "/wwopen/developer/customApp/tpl/app/list":
                    response["data"]["corpapp"][0]["authcorp_name"] = "南京示例集团"
                return response

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            context_file = Path(tmpdir) / "context.json"
            with patch.object(script, "FakeServiceJdyAdminTransport", MissingListOwnerRecoveryTransport):
                with patch.object(script, "FakeServiceWecomAdminTransport", ShortNameWecomTransport):
                    with redirect_stdout(output):
                        exit_code = script.main(
                            [
                                "--enterprise-name",
                                "南京示例品牌管理有限公司",
                                "--enterprise-short-name",
                                "南京示例集团",
                                "--plain-corp-id",
                                "ww001",
                                "--requested-user-id",
                                "user-1",
                                "--context-file",
                                str(context_file),
                                "--use-fake-transport-for-test",
                                "--wait-seconds",
                                "0",
                                "--confirm-write",
                            ]
                        )

            printed = output.getvalue()
            data = json.loads(printed)
            context = json.loads(context_file.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["status"], "success")
        self.assertEqual(context["jdy"]["corp_secret_id"], "corp-secret-from-owner")
        self.assertEqual(context["jdy"]["corp_name"], "南京示例集团")
        self.assertNotIn("corp-secret-from-owner", printed)

    def test_main_reuses_existing_jdy_secret_from_owner_recovery_without_reinstalling(self):
        from scripts.dev import run_wecom_bind_real_write as script
        from scripts.dev.run_platform_dryrun import FakeServiceJdyAdminTransport, FakeServiceWecomAdminTransport

        class ExistingSecretOwnerRecoveryTransport(FakeServiceJdyAdminTransport):
            def post_json(self, path, payload):
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    self.calls.append({"path": path, "payload": dict(payload)})
                    return {"has_more": False, "corp_deploy_list": []}
                if path == "/api/fx_sa/wxwork/get_owner":
                    self.calls.append({"path": path, "payload": dict(payload)})
                    return {
                        "can_bind_corp_secret": False,
                        "can_update_corp_secret": True,
                        "owner": {"corp_id": "corp-secret-from-owner"},
                        "corp": {
                            "name": "南京示例集团",
                            "token": "existing-token",
                            "encoding_aes_key": "existing-aes",
                        },
                    }
                if path == "/api/fx_sa/wxwork/install_corp_deploy":
                    raise AssertionError("recovery with existing owner secret must not reinstall JDY")
                return super().post_json(path, payload)

        class ShortNameWecomTransport(FakeServiceWecomAdminTransport):
            def get_json(self, path, params, headers):
                response = super().get_json(path, params, headers)
                if path == "/wwopen/developer/customApp/tpl/app/list":
                    response["data"]["corpapp"][0]["authcorp_name"] = "南京示例集团"
                return response

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            context_file = Path(tmpdir) / "context.json"
            with patch.object(script, "FakeServiceJdyAdminTransport", ExistingSecretOwnerRecoveryTransport):
                with patch.object(script, "FakeServiceWecomAdminTransport", ShortNameWecomTransport):
                    with redirect_stdout(output):
                        exit_code = script.main(
                            [
                                "--enterprise-name",
                                "南京示例品牌管理有限公司",
                                "--enterprise-short-name",
                                "南京示例集团",
                                "--plain-corp-id",
                                "ww001",
                                "--requested-user-id",
                                "user-1",
                                "--context-file",
                                str(context_file),
                                "--use-fake-transport-for-test",
                                "--wait-seconds",
                                "0",
                                "--confirm-write",
                            ]
                        )

            printed = output.getvalue()
            context = json.loads(context_file.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(context["wecom"]["token"], "existing-token")
        self.assertEqual(context["wecom"]["encoding_aes_key"], "existing-aes")
        self.assertNotIn("existing-token", printed)
        self.assertNotIn("existing-aes", printed)

    def test_main_skips_wecom_development_save_when_fields_are_already_present(self):
        from scripts.dev import run_wecom_bind_real_write as script
        from scripts.dev.run_platform_dryrun import FakeServiceWecomAdminTransport

        class AlreadyConfiguredWecomTransport(FakeServiceWecomAdminTransport):
            def get_json(self, path, params, headers):
                response = super().get_json(path, params, headers)
                if path == "/wwopen/developer/customApp/tpl/app/list":
                    row = response["data"]["corpapp"][0]
                    row.update(
                        {
                            "homeurl": "https://wxwork.jiandaoyun.com/wxwork/corp-secret/dashboard",
                            "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/corp-secret/service",
                            "token": "existing-token",
                            "aeskey": "existing-aes",
                            "redirect_domain": "wxwork.jiandaoyun.com",
                        }
                    )
                return response

            def post_json(self, path, payload, headers):
                if (
                    path == "/wwopen/developer/customApp/tpl/corpApp"
                    and "token" in payload.get("corpapp", {})
                ):
                    raise AssertionError("already configured app should not repeat development save")
                return super().post_json(path, payload, headers)

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            context_file = Path(tmpdir) / "context.json"
            with patch.object(script, "FakeServiceWecomAdminTransport", AlreadyConfiguredWecomTransport):
                with redirect_stdout(output):
                    exit_code = script.main(
                        [
                            "--enterprise-name",
                            "上海测试客户",
                            "--enterprise-short-name",
                            "上海测试客户",
                            "--plain-corp-id",
                            "ww001",
                            "--requested-user-id",
                            "user-1",
                            "--context-file",
                            str(context_file),
                            "--use-fake-transport-for-test",
                            "--wait-seconds",
                            "0",
                            "--confirm-write",
                        ]
                    )

            data = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["status"], "success")


if __name__ == "__main__":
    unittest.main()
