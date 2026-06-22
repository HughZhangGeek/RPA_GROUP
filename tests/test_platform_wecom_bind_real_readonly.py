import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyAdminTransport
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient, WecomAdminTransport
from rpa_platform.services.wecom_bind_service import JdyWecomBindInput


class RecordingJdyTransport(JdyAdminTransport):
    def __init__(self, owner_response=None):
        self.owner_response = owner_response or {"can_bind_corp_secret": True}
        self.calls = []

    def post_json(self, path, payload):
        self.calls.append({"method": "POST", "path": path, "payload": dict(payload)})
        if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
            return {
                "has_more": False,
                "corp_deploy_list": [
                    {
                        "corp_id": "corp-secret-123456",
                        "name": "上海测试客户",
                        "tenant_id": "old-user",
                        "suite_name": "简道云",
                        "integrate_suite_name": "简道云集成",
                        "suite_id": 1,
                        "suite_scenario": "main",
                    }
                ],
            }
        if path == "/api/fx_sa/wxwork/get_owner":
            return dict(self.owner_response)
        raise AssertionError("readonly preflight must not call Jiandaoyun write path %s" % path)


class RecordingWecomTransport(WecomAdminTransport):
    def __init__(self, apps_by_keyword=None):
        self.calls = []
        self.apps_by_keyword = apps_by_keyword

    def get_json(self, path, params, headers):
        self.calls.append(
            {"method": "GET", "path": path, "params": dict(params), "headers": dict(headers)}
        )
        if path == "/wwopen/developer/customApp/tpl/app/list":
            if self.apps_by_keyword is not None:
                return {"data": {"corpapp": self.apps_by_keyword.get(params.get("corp_name_keyword"), [])}}
            return {
                "data": {
                    "total": 1,
                    "corpapp": [
                        {
                            "app_id": "app-123456789",
                            "authcorp_name": "上海测试客户",
                            "name": "简道云",
                            "logo": "logo-url",
                            "description": "desc",
                            "customized_app_status": 0,
                            "sdk_auth": {"aes_app_id": "aes-app-123456789"},
                        }
                    ],
                }
            }
        raise AssertionError("unexpected WeCom readonly path %s" % path)

    def post_json(self, path, payload, headers):
        raise AssertionError("readonly preflight must not POST to WeCom path %s" % path)


def make_request():
    return JdyWecomBindInput(
        enterprise_name="上海测试客户",
        plain_corp_id="ww-plain-secret",
        requested_user_id="user-1",
        suite_id=1,
        suite_scenario="main",
        wecom_suiteid=1009479,
        suite_name="简道云",
    )


def make_full_and_short_name_request():
    return JdyWecomBindInput(
        enterprise_name="南京示例品牌管理有限公司",
        enterprise_short_name="南京示例集团",
        plain_corp_id="ww001",
        requested_user_id="user-1",
        suite_id=1,
        suite_scenario="main",
        wecom_suiteid=1009479,
        suite_name="简道云",
    )


class WecomBindRealReadonlyPreflightTest(unittest.TestCase):
    def test_readonly_preflight_uses_only_read_endpoints_and_returns_redacted_summary(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        jdy_transport = RecordingJdyTransport()
        wecom_transport = RecordingWecomTransport()

        result = run_readonly_preflight(
            make_request(),
            jdy_client=JdyAdminClient(jdy_transport),
            wecom_client=WecomAdminClient(wecom_transport),
        )

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reason"], "ready_for_confirm_write")
        self.assertEqual(result["enterprise_name"], "上海测试客户")
        self.assertEqual(result["jdy"]["original_tenant_id"], "old-user")
        self.assertEqual(result["jdy"]["requested_user_id"], "user-1")
        self.assertEqual(result["wecom"]["app_id"], "app-123456789")
        self.assertNotIn("ww-plain-secret", serialized)
        self.assertNotIn("corp-secret-123456", serialized)
        self.assertNotIn("aes-app-123456789", serialized)
        self.assertIn("***", result["plain_corp_id"])
        self.assertIn("***", result["jdy"]["corp_secret_id"])
        self.assertIn("***", result["wecom"]["aes_app_id"])
        self.assertEqual(
            [call["path"] for call in jdy_transport.calls],
            [
                "/api/fx_sa/wxwork/get_corp_deploy_list",
                "/api/fx_sa/wxwork/get_owner",
            ],
        )
        self.assertEqual(
            [call["path"] for call in wecom_transport.calls],
            ["/wwopen/developer/customApp/tpl/app/list"],
        )

    def test_readonly_preflight_accepts_jdy_full_name_and_short_name_pair(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        class ShortNameJdyTransport(RecordingJdyTransport):
            def post_json(self, path, payload):
                response = super().post_json(path, payload)
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    response["corp_deploy_list"][0]["name"] = "南京示例集团"
                return response

        class ShortNameWecomTransport(RecordingWecomTransport):
            def get_json(self, path, params, headers):
                response = super().get_json(path, params, headers)
                if path == "/wwopen/developer/customApp/tpl/app/list":
                    response["data"]["corpapp"][0]["authcorp_name"] = "南京示例集团"
                return response

        jdy_transport = ShortNameJdyTransport()
        wecom_transport = ShortNameWecomTransport()

        result = run_readonly_preflight(
            make_full_and_short_name_request(),
            jdy_client=JdyAdminClient(jdy_transport),
            wecom_client=WecomAdminClient(wecom_transport),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["enterprise_name"], "南京示例品牌管理有限公司")
        self.assertEqual(result["enterprise_short_name"], "南京示例集团")
        self.assertEqual(result["jdy"]["corp_name"], "南京示例集团")
        self.assertEqual(result["wecom"]["authcorp_name"], "南京示例集团")
        self.assertEqual(wecom_transport.calls[0]["params"]["corp_name_keyword"], "南京示例集团")

    def test_readonly_preflight_allows_unique_corp_id_name_mismatch_when_jdy_name_finds_wecom_app(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        class MismatchedNameJdyTransport(RecordingJdyTransport):
            def post_json(self, path, payload):
                response = super().post_json(path, payload)
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    response["corp_deploy_list"][0]["name"] = "凯棠管理"
                return response

        class MismatchedNameWecomTransport(RecordingWecomTransport):
            def get_json(self, path, params, headers):
                response = super().get_json(path, params, headers)
                if path == "/wwopen/developer/customApp/tpl/app/list":
                    response["data"]["corpapp"][0]["authcorp_name"] = "凯棠管理"
                return response

        result = run_readonly_preflight(
            JdyWecomBindInput(
                enterprise_name="江苏凯棠工程项目管理有限公司",
                enterprise_short_name="江苏凯棠工程项目管理有限公司",
                plain_corp_id="ww4fc007a22672730b",
                requested_user_id="69c888c9ff5bda0e12474dc7",
                suite_id=1,
                suite_scenario="main",
                wecom_suiteid=1009479,
                suite_name="简道云",
            ),
            jdy_client=JdyAdminClient(MismatchedNameJdyTransport()),
            wecom_client=WecomAdminClient(MismatchedNameWecomTransport()),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reason"], "ready_for_confirm_write")
        self.assertTrue(result["jdy"]["corp_name_mismatch"])
        self.assertEqual(result["jdy"]["corp_name"], "凯棠管理")
        self.assertEqual(result["jdy"]["owner_state"], "can_bind_corp_secret")
        self.assertEqual(result["wecom"]["authcorp_name"], "凯棠管理")
        self.assertEqual(result["wecom"]["lookup_source"], "jdy_corp_name")
        self.assertEqual(result["wecom"]["lookup_sources"], ["jdy_corp_name"])
        self.assertEqual(
            result["wecom"]["lookup_candidates"],
            [
                {"source": "jdy_corp_name", "name": "凯棠管理"},
                {"source": "incoming_enterprise_name", "name": "江苏凯棠工程项目管理有限公司"},
            ],
        )

    def test_readonly_preflight_allows_multiple_candidate_names_when_they_resolve_same_app(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        class JdyNameTransport(RecordingJdyTransport):
            def post_json(self, path, payload):
                response = super().post_json(path, payload)
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    response["corp_deploy_list"][0]["name"] = "温州华绘印务"
                return response

        same_app = {
            "app_id": "app-huahui",
            "authcorp_name": "温州华绘印务",
            "name": "简道云",
            "logo": "logo-url",
            "description": "desc",
            "customized_app_status": 0,
            "sdk_auth": {"aes_app_id": "aes-huahui"},
        }
        incoming_same_app = dict(same_app)
        incoming_same_app["authcorp_name"] = "温州市华绘印务有限公司"
        wecom_transport = RecordingWecomTransport(
            apps_by_keyword={
                "温州华绘印务": [same_app],
                "温州市华绘印务有限公司": [incoming_same_app],
            }
        )

        result = run_readonly_preflight(
            JdyWecomBindInput(
                enterprise_name="温州市华绘印务有限公司",
                enterprise_short_name="",
                plain_corp_id="ww-huahui",
                requested_user_id="user-1",
                suite_id=1,
                suite_scenario="main",
                wecom_suiteid=1009479,
                suite_name="简道云",
            ),
            jdy_client=JdyAdminClient(JdyNameTransport()),
            wecom_client=WecomAdminClient(wecom_transport),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reason"], "ready_for_confirm_write")
        self.assertTrue(result["jdy"]["corp_name_mismatch"])
        self.assertEqual(result["wecom"]["app_id"], "app-huahui")
        self.assertEqual(result["wecom"]["lookup_source"], "jdy_corp_name")
        self.assertEqual(result["wecom"]["lookup_sources"], ["jdy_corp_name", "incoming_enterprise_name"])
        self.assertEqual(
            [call["params"]["corp_name_keyword"] for call in wecom_transport.calls],
            ["温州华绘印务", "温州市华绘印务有限公司"],
        )

    def test_readonly_preflight_blocks_when_candidate_names_resolve_different_apps(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        class JdyNameTransport(RecordingJdyTransport):
            def post_json(self, path, payload):
                response = super().post_json(path, payload)
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    response["corp_deploy_list"][0]["name"] = "温州华绘印务"
                return response

        wecom_transport = RecordingWecomTransport(
            apps_by_keyword={
                "温州华绘印务": [
                    {
                        "app_id": "app-jdy",
                        "authcorp_name": "温州华绘印务",
                        "name": "简道云",
                        "sdk_auth": {"aes_app_id": "aes-jdy"},
                    }
                ],
                "温州市华绘印务有限公司": [
                    {
                        "app_id": "app-incoming",
                        "authcorp_name": "温州市华绘印务有限公司",
                        "name": "简道云",
                        "sdk_auth": {"aes_app_id": "aes-incoming"},
                    }
                ],
            }
        )

        result = run_readonly_preflight(
            JdyWecomBindInput(
                enterprise_name="温州市华绘印务有限公司",
                enterprise_short_name="",
                plain_corp_id="ww-huahui",
                requested_user_id="user-1",
                suite_id=1,
                suite_scenario="main",
                wecom_suiteid=1009479,
                suite_name="简道云",
            ),
            jdy_client=JdyAdminClient(JdyNameTransport()),
            wecom_client=WecomAdminClient(wecom_transport),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "wecom_app_lookup_conflict")
        self.assertEqual(result["wecom"]["lookup_source"], "")
        self.assertEqual(result["wecom"]["lookup_sources"], ["jdy_corp_name", "incoming_enterprise_name"])
        self.assertIn("lookup_conflict", result["wecom"])

    def test_readonly_preflight_blocks_when_no_candidate_name_finds_wecom_app(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        class JdyNameTransport(RecordingJdyTransport):
            def post_json(self, path, payload):
                response = super().post_json(path, payload)
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    response["corp_deploy_list"][0]["name"] = "温州华绘印务"
                return response

        result = run_readonly_preflight(
            JdyWecomBindInput(
                enterprise_name="温州市华绘印务有限公司",
                enterprise_short_name="",
                plain_corp_id="ww-huahui",
                requested_user_id="user-1",
                suite_id=1,
                suite_scenario="main",
                wecom_suiteid=1009479,
                suite_name="简道云",
            ),
            jdy_client=JdyAdminClient(JdyNameTransport()),
            wecom_client=WecomAdminClient(RecordingWecomTransport(apps_by_keyword={})),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "wecom_app_not_found")
        self.assertEqual(result["wecom"]["lookup_source"], "")

    def test_readonly_preflight_reports_explainable_already_bound_owner_state(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        result = run_readonly_preflight(
            make_request(),
            jdy_client=JdyAdminClient(
                RecordingJdyTransport(
                    owner_response={
                        "can_bind_corp_secret": False,
                        "can_update_corp_secret": True,
                    }
                )
            ),
            wecom_client=WecomAdminClient(RecordingWecomTransport()),
        )

        self.assertEqual(result["status"], "review")
        self.assertEqual(result["reason"], "owner_already_bound_can_update_corp_secret")
        self.assertEqual(result["jdy"]["owner_state"], "can_update_corp_secret")

    def test_readonly_preflight_recovers_corp_from_owner_when_bound_corp_is_missing_from_list(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        class MissingListOwnerRecoveryTransport(RecordingJdyTransport):
            def post_json(self, path, payload):
                if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
                    self.calls.append({"method": "POST", "path": path, "payload": dict(payload)})
                    return {"has_more": False, "corp_deploy_list": []}
                return super().post_json(path, payload)

        class ShortNameWecomTransport(RecordingWecomTransport):
            def get_json(self, path, params, headers):
                response = super().get_json(path, params, headers)
                if path == "/wwopen/developer/customApp/tpl/app/list":
                    response["data"]["corpapp"][0]["authcorp_name"] = "南京示例集团"
                return response

        jdy_transport = MissingListOwnerRecoveryTransport(
            owner_response={
                "can_bind_corp_secret": False,
                "can_update_corp_secret": True,
                "owner": {"corp_id": "corp-secret-from-owner"},
                "corp": {"name": "南京示例集团"},
            }
        )

        result = run_readonly_preflight(
            make_full_and_short_name_request(),
            jdy_client=JdyAdminClient(jdy_transport),
            wecom_client=WecomAdminClient(ShortNameWecomTransport()),
        )
        serialized = json.dumps(result, ensure_ascii=False)

        self.assertEqual(result["status"], "review")
        self.assertEqual(result["reason"], "owner_already_bound_can_update_corp_secret")
        self.assertEqual(result["jdy"]["corp_name"], "南京示例集团")
        self.assertIn("***", result["jdy"]["corp_secret_id"])
        self.assertNotIn("corp-secret-from-owner", serialized)

    def test_readonly_preflight_reports_transport_error_without_sensitive_values(self):
        from scripts.dev.check_wecom_bind_real_readonly import JsonHttpError, run_readonly_preflight

        class FailingJdyTransport(JdyAdminTransport):
            def post_json(self, path, payload):
                raise JsonHttpError("POST https://dc.jdydevelop.com/api/fx_sa/wxwork/get_corp_deploy_list failed")

        result = run_readonly_preflight(
            make_request(),
            jdy_client=JdyAdminClient(FailingJdyTransport()),
            wecom_client=WecomAdminClient(RecordingWecomTransport()),
        )
        serialized = json.dumps(result, ensure_ascii=False)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "jdy_corp_not_unique_or_missing")
        self.assertNotIn("ww-plain-secret", serialized)

    def test_readonly_preflight_reports_jdy_session_expired(self):
        from scripts.dev.check_wecom_bind_real_readonly import JsonHttpError, run_readonly_preflight

        class ExpiredJdyTransport(JdyAdminTransport):
            def post_json(self, path, payload):
                raise JsonHttpError(
                    'POST https://dc.jdydevelop.com/api/fx_sa/wxwork/get_owner failed: {"code":1007,"error":"用户尚未登录"}'
                )

        result = run_readonly_preflight(
            make_request(),
            jdy_client=JdyAdminClient(ExpiredJdyTransport()),
            wecom_client=WecomAdminClient(RecordingWecomTransport()),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "jdy_session_expired")
        self.assertIn("用户尚未登录", result["detail"])

    def test_readonly_preflight_reports_wecom_session_expired(self):
        from scripts.dev.check_wecom_bind_real_readonly import run_readonly_preflight

        class ExpiredWecomTransport(RecordingWecomTransport):
            def get_json(self, path, params, headers):
                self.calls.append(
                    {"method": "GET", "path": path, "params": dict(params), "headers": dict(headers)}
                )
                return {"result": {"errCode": -3, "message": "outsession"}}

        result = run_readonly_preflight(
            make_request(),
            jdy_client=JdyAdminClient(RecordingJdyTransport()),
            wecom_client=WecomAdminClient(ExpiredWecomTransport()),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "wecom_session_expired")
        self.assertEqual(result["detail"], "WeCom admin session expired: outsession")

    def test_main_prints_json_without_sensitive_values_with_injected_clients(self):
        from scripts.dev.check_wecom_bind_real_readonly import main

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--enterprise-name",
                    "上海测试客户",
                    "--plain-corp-id",
                    "ww-plain-secret",
                    "--requested-user-id",
                    "user-1",
                    "--use-fake-transport-for-test",
                ]
            )

        printed = output.getvalue()
        data = json.loads(printed)
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["status"], "ok")
        self.assertNotIn("ww-plain-secret", printed)
        self.assertNotIn("corp-secret-123456", printed)
        self.assertNotIn("aes-app-123456789", printed)

    def test_main_reports_missing_cookie_source_as_redacted_json(self):
        from scripts.dev.check_wecom_bind_real_readonly import main

        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--enterprise-name",
                        "上海测试客户",
                        "--plain-corp-id",
                        "ww-plain-secret",
                        "--requested-user-id",
                        "user-1",
                    ]
                )

        printed = output.getvalue()
        data = json.loads(printed)
        self.assertEqual(exit_code, 2)
        self.assertEqual(data["status"], "blocked")
        self.assertEqual(data["reason"], "missing_cookie_source")
        self.assertNotIn("ww-plain-secret", printed)

    def test_wecom_cookie_transport_posts_with_wecom_ajax_query(self):
        from scripts.dev import check_wecom_bind_real_readonly as script

        captured = {}

        def fake_request_json(method, url, payload, headers, timeout):
            captured.update({"method": method, "url": url, "payload": payload, "headers": headers})
            return {"data": {}}

        with patch.object(script, "_request_json", fake_request_json):
            script.WecomCookieTransport("sid=secret").post_json(
                "/wwopen/developer/example",
                {"hello": "world"},
                {"x-wecom-developer-page": "/page", "x-wecom-developer-perm": "50"},
            )

        self.assertEqual(captured["method"], "POST")
        self.assertIn("lang=zh_CN", captured["url"])
        self.assertIn("ajax=1", captured["url"])
        self.assertIn("f=json", captured["url"])
        self.assertIn("random=0", captured["url"])
        self.assertEqual(captured["payload"], {"hello": "world"})
        self.assertEqual(captured["headers"]["x-wecom-developer-page"], "/page")


if __name__ == "__main__":
    unittest.main()
