import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from rpa_platform.integrations.jdy_admin_client import JdyAdminClient
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient
from rpa_platform.services.wecom_bind_service import FixedWecomSecretGenerator
from scripts.dev.run_platform_dryrun import FakeServiceJdyAdminTransport, FakeServiceWecomAdminTransport


class WecomBindUnattendedWriteTest(unittest.TestCase):
    PRIVATE_FORM_ID = "5e4ba3a09c38890006fbdf71"
    PUBLIC_FORM_ID = "6258e5f6e09e970007b0150c"

    def _context(self):
        return {
            "enterprise_name": "上海测试客户",
            "enterprise_short_name": "上海测试客户",
            "plain_corp_id": "ww001",
            "requested_user_id": "user-1",
            "suite_id": "1",
            "suite_scenario": "main",
            "wecom_suiteid": "1009479",
            "suite_name": "简道云",
        }

    def _clients(self, jdy_transport=None, wecom_transport=None):
        jdy_transport = jdy_transport or FakeServiceJdyAdminTransport()
        wecom_transport = wecom_transport or FakeServiceWecomAdminTransport()
        return (
            JdyAdminClient(jdy_transport),
            WecomAdminClient(wecom_transport),
            jdy_transport,
            wecom_transport,
        )

    def test_fake_transport_success_runs_full_write_and_redacts_public_result(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        jdy_client, wecom_client, jdy_transport, wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_unattended_wecom_bind_write(
                task_id="task-success",
                context=self._context(),
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                context_file=Path(tmpdir) / "context.json",
                lock_file=Path(tmpdir) / "write.lock",
                now=datetime(2026, 6, 20, 12, 0, 0),
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["mode"], "unattended_write")
        self.assertEqual(result["preflight"]["status"], "ok")
        self.assertEqual(result["wecom"]["auditorderid"], "order-1")
        self.assertEqual(result["wecom"]["auditorder_status"], 5)
        self.assertEqual(result["submit_result"]["status"], "success")
        self.assertIn("/api/fx_sa/wxwork/install_corp_deploy", [call["path"] for call in jdy_transport.calls])
        self.assertIn("/wwopen/developer/order/set", [call["path"] for call in wecom_transport.calls])
        self.assertNotIn("token-secret", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("aes-secret", json.dumps(result, ensure_ascii=False))

    def test_private_form_success_result_contains_jdy_writeback_fields(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        context = dict(self._context())
        context.update(
            {
                "source_entry_id": self.PRIVATE_FORM_ID,
                "current_home_url": "//dashboard",
                "current_webhook_url": "//corp/service",
            }
        )
        jdy_client, wecom_client, _jdy_transport, _wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_unattended_wecom_bind_write(
                task_id="task-private-writeback",
                context=context,
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                context_file=Path(tmpdir) / "context.json",
                lock_file=Path(tmpdir) / "write.lock",
                now=datetime(2026, 6, 20, 12, 0, 0),
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["secret_corp_id"], "corp-secret")
        self.assertEqual(result["home_url"], "https://wxwork.jiandaoyun.com/wxwork/corp-secret/dashboard")
        self.assertEqual(result["webhook_url"], "https://wxwork.jiandaoyun.com/wxwork/corp/corp-secret/service")
        self.assertEqual(result["wx_token"], "token-secret")
        self.assertEqual(result["wx_key"], "aes-secret")

    def test_public_form_success_result_omits_secret_token_fields_and_uses_generated_urls(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        context = dict(self._context())
        context.update(
            {
                "source_entry_id": self.PUBLIC_FORM_ID,
                "home_url": "//dashboard",
                "webhook_url": "//corp/service",
                "current_home_url": "//dashboard",
                "current_webhook_url": "//corp/service",
            }
        )
        jdy_client, wecom_client, _jdy_transport, _wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_unattended_wecom_bind_write(
                task_id="task-public-writeback",
                context=context,
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                context_file=Path(tmpdir) / "context.json",
                lock_file=Path(tmpdir) / "write.lock",
                now=datetime(2026, 6, 20, 12, 0, 0),
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["secret_corp_id"], "corp-secret")
        self.assertEqual(result["home_url"], "https://wxwork.jiandaoyun.com/wxwork/corp-secret/dashboard")
        self.assertEqual(result["webhook_url"], "https://wxwork.jiandaoyun.com/wxwork/corp/corp-secret/service")
        self.assertNotIn("wx_token", result)
        self.assertNotIn("wx_key", result)

    def test_preflight_failed_does_not_write(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        class RejectWriteJdyTransport(FakeServiceJdyAdminTransport):
            def post_json(self, path, payload):
                if path == "/api/fx_sa/wxwork/install_corp_deploy":
                    raise AssertionError("preflight failure must not install")
                return super().post_json(path, payload)

        def failed_preflight(*_args, **_kwargs):
            return {"status": "blocked", "reason": "jdy_corp_not_unique_or_missing"}

        jdy_client, wecom_client, _jdy_transport, wecom_transport = self._clients(
            jdy_transport=RejectWriteJdyTransport()
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_unattended_wecom_bind_write(
                task_id="task-preflight-blocked",
                context=self._context(),
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                preflight_runner=failed_preflight,
                context_file=Path(tmpdir) / "context.json",
                lock_file=Path(tmpdir) / "write.lock",
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "business_unexecutable")
        self.assertEqual(result["mode"], "unattended_write")
        self.assertEqual(result["reason"], "jdy_corp_not_unique_or_missing")
        self.assertNotIn("/wwopen/developer/order/add", [call["path"] for call in wecom_transport.calls])

    def test_recovered_login_preflight_continues_to_real_write(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        def recovered_preflight(*_args, **_kwargs):
            return {
                "status": "ready_for_real_bind",
                "reason": "ready_for_confirm_write",
                "preflight": {"status": "ok", "reason": "ready_for_confirm_write"},
                "login_recovery": {"notify_attempts": 1, "restored": True},
            }

        jdy_client, wecom_client, _jdy_transport, wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_unattended_wecom_bind_write(
                task_id="task-recovered-login",
                context=self._context(),
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                preflight_runner=recovered_preflight,
                context_file=Path(tmpdir) / "context.json",
                lock_file=Path(tmpdir) / "write.lock",
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["preflight"]["status"], "ok")
        self.assertEqual(result["login_recovery"]["notify_attempts"], 1)
        self.assertIn("/wwopen/developer/order/set", [call["path"] for call in wecom_transport.calls])

    def test_login_recovery_metadata_kwarg_is_preserved_for_recovery_handler(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        jdy_client, wecom_client, _jdy_transport, _wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_unattended_wecom_bind_write(
                task_id="task-login-recovery-metadata",
                context=self._context(),
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                preflight_runner=lambda *_args, **_kwargs: {"status": "ok", "reason": "ready_for_confirm_write"},
                login_recovery={"notify_attempts": 1, "restored": True},
                context_file=Path(tmpdir) / "context.json",
                lock_file=Path(tmpdir) / "write.lock",
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["login_recovery"], {"notify_attempts": 1, "restored": True})

    def test_real_write_reuses_candidate_lookup_instead_of_wrong_incoming_short_name(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        class MismatchedJdyTransport(FakeServiceJdyAdminTransport):
            def post_json(self, path, payload):
                response = super().post_json(path, payload)
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    response["corp_deploy_list"][0]["name"] = "温州华绘印务"
                return response

        class CandidateWecomTransport(FakeServiceWecomAdminTransport):
            def get_json(self, path, params, headers):
                self.calls.append({"method": "GET", "path": path, "params": dict(params), "headers": dict(headers)})
                if path == "/wwopen/developer/customApp/tpl/app/list":
                    keyword = params.get("corp_name_keyword")
                    if keyword == "温州华绘印务":
                        return {
                            "data": {
                                "corpapp": [
                                    {
                                        "app_id": "app-huahui",
                                        "authcorp_name": "温州华绘印务",
                                        "name": "简道云",
                                        "logo": "logo-url",
                                        "description": "desc",
                                        "customized_app_status": 0,
                                        "sdk_auth": {"aes_app_id": "aes-huahui"},
                                    }
                                ]
                            }
                        }
                    if keyword == "温州市华绘印务有限公司":
                        return {"data": {"corpapp": []}}
                raise ValueError("Unsupported fake WeCom service GET path: %s" % path)

            def post_json(self, path, payload, headers):
                if path == "/wwopen/developer/order/add":
                    return {
                        "data": {
                            "auditorder": {
                                "auditorderid": "order-huahui",
                                "corpappid": "app-huahui",
                                "authcorp_name": "温州华绘印务",
                                "status": 1,
                            }
                        }
                    }
                return super().post_json(path, payload, headers)

        context = dict(self._context())
        context.update(
            {
                "enterprise_name": "温州市华绘印务有限公司",
                "enterprise_short_name": "温州市华绘印务有限公司",
                "plain_corp_id": "ww-huahui",
            }
        )
        jdy_client, wecom_client, _jdy_transport, wecom_transport = self._clients(
            jdy_transport=MismatchedJdyTransport(),
            wecom_transport=CandidateWecomTransport(),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_unattended_wecom_bind_write(
                task_id="task-huahui",
                context=context,
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                preflight_runner=lambda *_args, **_kwargs: {"status": "ok", "reason": "ready_for_confirm_write"},
                context_file=Path(tmpdir) / "context.json",
                lock_file=Path(tmpdir) / "write.lock",
                now=datetime(2026, 6, 20, 12, 0, 0),
                wait_seconds=0,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["start_result"]["context"]["wecom"]["lookup_source"], "jdy_corp_name")
        self.assertEqual(
            [call["params"]["corp_name_keyword"] for call in wecom_transport.calls if call["method"] == "GET"],
            ["温州华绘印务", "温州市华绘印务有限公司"],
        )

    def test_missing_cookie_or_login_source_returns_blocked_without_write(self):
        from scripts.dev.check_wecom_bind_real_readonly import CookieSourceError
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        def missing_cookie_preflight(*_args, **_kwargs):
            raise CookieSourceError("missing cookie source: set JDY_ADMIN_COOKIE")

        jdy_client, wecom_client, jdy_transport, _wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_unattended_wecom_bind_write(
                task_id="task-missing-cookie",
                context=self._context(),
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                preflight_runner=missing_cookie_preflight,
                context_file=Path(tmpdir) / "context.json",
                lock_file=Path(tmpdir) / "write.lock",
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["mode"], "unattended_write")
        self.assertEqual(result["reason"], "missing_cookie_source")
        self.assertNotIn("/api/fx_sa/wxwork/install_corp_deploy", [call["path"] for call in jdy_transport.calls])

    def test_existing_success_context_prevents_duplicate_write(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        jdy_client, wecom_client, jdy_transport, _wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            context_file = Path(tmpdir) / "context.json"
            context_file.write_text(
                json.dumps(
                    {
                        "wecom": {
                            "auditorderid": "au-existing",
                            "auditorder_status": 5,
                            "token": "token-secret",
                            "encoding_aes_key": "aes-secret",
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = run_unattended_wecom_bind_write(
                task_id="task-success-before",
                context=self._context(),
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                context_file=context_file,
                lock_file=Path(tmpdir) / "write.lock",
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "already_completed")
        self.assertEqual(result["mode"], "unattended_write")
        self.assertEqual(result["wecom"]["auditorderid"], "au-existing")
        self.assertEqual(result["wecom"]["auditorder_status"], 5)
        self.assertEqual(jdy_transport.calls, [])
        self.assertNotIn("token-secret", json.dumps(result, ensure_ascii=False))

    def test_active_lock_blocks_concurrent_write(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        jdy_client, wecom_client, jdy_transport, _wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_file = Path(tmpdir) / "write.lock"
            lock_file.write_text("task-other", encoding="utf-8")
            result = run_unattended_wecom_bind_write(
                task_id="task-locked",
                context=self._context(),
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                context_file=Path(tmpdir) / "context.json",
                lock_file=lock_file,
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["mode"], "unattended_write")
        self.assertEqual(result["reason"], "write_already_running")
        self.assertEqual(jdy_transport.calls, [])

    def test_lock_is_released_when_write_raises(self):
        from rpa_platform.worker.wecom_bind_unattended_write import run_unattended_wecom_bind_write

        def exploding_preflight(*_args, **_kwargs):
            raise RuntimeError("boom")

        jdy_client, wecom_client, _jdy_transport, _wecom_transport = self._clients()
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_file = Path(tmpdir) / "write.lock"
            result = run_unattended_wecom_bind_write(
                task_id="task-exploding",
                context=self._context(),
                jdy_client=jdy_client,
                wecom_client=wecom_client,
                secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
                preflight_runner=exploding_preflight,
                context_file=Path(tmpdir) / "context.json",
                lock_file=lock_file,
                wait_seconds=0,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["mode"], "unattended_write")
        self.assertEqual(result["reason"], "real_write_failed")
        self.assertFalse(lock_file.exists())


if __name__ == "__main__":
    unittest.main()
