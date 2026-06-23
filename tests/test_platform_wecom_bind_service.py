from datetime import datetime
import unittest

from rpa_platform.integrations.jdy_admin_client import (
    JdyAdminClient,
    JdyAdminError,
    JdyAdminTransport,
    OwnerCannotBindError,
)
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient, WecomAdminTransport
from rpa_platform.services.wecom_bind_service import (
    FixedWecomSecretGenerator,
    JdyWecomBindInput,
    JdyWecomBindService,
)


class FakeJdyTransport(JdyAdminTransport):
    def __init__(
        self,
        call_log,
        can_bind_corp_secret=True,
        can_update_corp_secret=False,
        install_response=None,
        corp_name="上海测试客户",
    ):
        self.call_log = call_log
        self.can_bind_corp_secret = can_bind_corp_secret
        self.can_update_corp_secret = can_update_corp_secret
        self.install_response = install_response or {"tenant_id": "user-1", "owner_id": "user-1"}
        self.corp_name = corp_name
        self.calls = []

    def post_json(self, path, payload):
        call = {"client": "jdy", "method": "POST", "path": path, "payload": payload}
        self.calls.append(call)
        self.call_log.append(call)
        if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
            return {
                "has_more": False,
                "corp_deploy_list": [
                    {
                        "corp_id": "corp-secret",
                        "name": self.corp_name,
                        "tenant_id": "old-user",
                        "suite_name": "简道云",
                        "integrate_suite_name": "简道云集成",
                        "suite_id": 1,
                        "suite_scenario": "main",
                    }
                ],
            }
        if path == "/api/fx_sa/wxwork/get_owner":
            return {
                "can_bind_corp_secret": self.can_bind_corp_secret,
                "can_update_corp_secret": self.can_update_corp_secret,
            }
        if path == "/api/fx_sa/wxwork/install_corp_deploy":
            return self.install_response
        raise AssertionError("unexpected jdy path %s" % path)


class FakeWecomTransport(WecomAdminTransport):
    def __init__(self, call_log, apps_by_keyword=None):
        self.call_log = call_log
        self.apps_by_keyword = apps_by_keyword
        self.calls = []

    def get_json(self, path, params, headers):
        call = {"client": "wecom", "method": "GET", "path": path, "params": params, "headers": headers}
        self.calls.append(call)
        self.call_log.append(call)
        if path == "/wwopen/developer/customApp/tpl/app/list":
            if self.apps_by_keyword is not None:
                return {"data": {"corpapp": self.apps_by_keyword.get(params.get("corp_name_keyword"), [])}}
            return {
                "data": {
                    "corpapp": [
                        {
                            "app_id": "app-1",
                            "authcorp_name": "上海测试客户",
                            "name": "简道云",
                            "logo": "logo-url",
                            "description": "desc",
                            "customized_app_status": 0,
                            "sdk_auth": {"aes_app_id": "aes-app-1"},
                        }
                    ]
                }
            }
        raise AssertionError("unexpected wecom path %s" % path)

    def post_json(self, path, payload, headers):
        call = {"client": "wecom", "method": "POST", "path": path, "payload": payload, "headers": headers}
        self.calls.append(call)
        self.call_log.append(call)
        if path == "/wwopen/developer/customApp/tpl/corpApp":
            return {"data": {"corpapp": payload["corpapp"]}}
        if path == "/wwopen/api/customApp/privilege/getCustomizedAppPrivilege":
            return {
                "data": {
                    "privilege_list": [
                        {"id": 310000, "b_check": False},
                        {"id": 10006, "b_check": False},
                        {"id": 42, "b_check": False},
                    ]
                }
            }
        if path == "/wwopen/api/customApp/privilege/setCustomizedAppPrivilege":
            return {"data": {"privilege_list": payload["privilege_list"]}}
        if path == "/wwopen/api/customApp/price/GetStandardPriceInfoForCA":
            return {"data": {"base_price_info": {}}}
        if path == "/wwopen/api/customApp/price/SetStandardPriceInfoForCA":
            return {"data": {"is_already_set_try_info": True, "base_price_info": payload["base_price_info"]}}
        if path == "/wwopen/developer/order/add":
            return {
                "data": {
                    "auditorder": {
                        "auditorderid": "order-1",
                        "corpappid": "app-1",
                        "authcorp_name": "上海测试客户",
                        "status": 1,
                    }
                }
            }
        if path == "/wwopen/developer/order/set":
            return {
                "data": {
                    "auditorder": {
                        "auditorderid": payload["auditorder"]["auditorderid"],
                        "corpappid": "app-1",
                        "authcorp_name": "上海测试客户",
                        "status": 5,
                    }
                }
            }
        raise AssertionError("unexpected wecom path %s" % path)


def make_service(
    call_log,
    can_bind_corp_secret=True,
    can_update_corp_secret=False,
    install_response=None,
    corp_name="上海测试客户",
    apps_by_keyword=None,
):
    jdy_transport = FakeJdyTransport(
        call_log,
        can_bind_corp_secret=can_bind_corp_secret,
        can_update_corp_secret=can_update_corp_secret,
        install_response=install_response,
        corp_name=corp_name,
    )
    wecom_transport = FakeWecomTransport(call_log, apps_by_keyword=apps_by_keyword)
    service = JdyWecomBindService(
        jdy_client=JdyAdminClient(jdy_transport),
        wecom_client=WecomAdminClient(wecom_transport),
        secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
    )
    return service, jdy_transport, wecom_transport


def make_request():
    return JdyWecomBindInput(
        enterprise_name="上海测试客户",
        plain_corp_id="ww001",
        requested_user_id="user-1",
        suite_id=1,
        suite_scenario="main",
        wecom_suiteid=1009479,
        suite_name="简道云",
    )


class JdyWecomBindServiceTest(unittest.TestCase):
    def test_start_bind_runs_jdy_install_before_wecom_save_and_returns_delay(self):
        call_log = []
        service, jdy_transport, _wecom_transport = make_service(call_log)

        result = service.start_bind(make_request(), now=datetime(2026, 6, 16, 10, 0, 0))

        all_paths = [call["path"] for call in call_log]
        install_index = all_paths.index("/api/fx_sa/wxwork/install_corp_deploy")
        save_index = all_paths.index("/wwopen/developer/customApp/tpl/corpApp")
        self.assertLess(install_index, save_index)
        self.assertEqual(result.status, "waiting_wecom_online_delay")
        self.assertEqual(result.next_check_at, datetime(2026, 6, 16, 10, 5, 0))
        self.assertEqual(
            result.context["jdy"],
            {
                "corp_secret_id": "corp-secret",
                "corp_name": "上海测试客户",
                "original_tenant_id": "old-user",
                "requested_user_id": "user-1",
                "effective_user_id": "user-1",
                "effective_user_id_source": "incoming_userid",
                "incoming_userid_empty": False,
                "install_tenant_id": "user-1",
                "install_owner_id": "user-1",
                "bound_user_id": "user-1",
                "suite_id": 1,
                "suite_scenario": "main",
                "suite_name": "简道云",
                "integrate_suite_name": "简道云集成",
            },
        )
        self.assertEqual(
            result.context["wecom"],
            {
                "suiteid": 1009479,
                "suite_name": "简道云",
                "app_id": "app-1",
                "aes_app_id": "aes-app-1",
                "lookup_source": "jdy_corp_name",
                "lookup_sources": ["jdy_corp_name"],
                "lookup_candidates": [{"source": "jdy_corp_name", "name": "上海测试客户"}],
                "homeurl": "https://wxwork.jiandaoyun.com/wxwork/corp-secret/dashboard",
                "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/corp-secret/service",
                "redirect_domain": "wxwork.jiandaoyun.com",
                "token": "token-secret",
                "encoding_aes_key": "aes-secret",
                "auditorderid": "order-1",
                "auditorder_status": 1,
                "order_created_at": "2026-06-16 10:00:00",
            },
        )
        install_payload = [
            call["payload"]
            for call in jdy_transport.calls
            if call["path"] == "/api/fx_sa/wxwork/install_corp_deploy"
        ][0]
        self.assertEqual(install_payload["tenant_id"], "user-1")
        self.assertEqual(install_payload["token"], "token-secret")
        self.assertEqual(install_payload["encoding_aes_key"], "aes-secret")
        save_payload = [
            call["payload"]
            for call in call_log
            if call["path"] == "/wwopen/developer/customApp/tpl/corpApp"
            and call["payload"]["corpapp"].get("token") == "token-secret"
        ][0]
        save_corpapp = save_payload["corpapp"]
        self.assertEqual(save_corpapp["homeurl"], result.context["wecom"]["homeurl"])
        self.assertEqual(save_corpapp["callbackurl"], result.context["wecom"]["callbackurl"])
        self.assertEqual(save_corpapp["redirect_domain"], result.context["wecom"]["redirect_domain"])
        self.assertEqual(save_corpapp["token"], result.context["wecom"]["token"])
        self.assertEqual(save_corpapp["aeskey"], result.context["wecom"]["encoding_aes_key"])
        sso_payload = [
            call["payload"]
            for call in call_log
            if call["path"] == "/wwopen/developer/customApp/tpl/corpApp"
            and call["payload"]["corpapp"].get("sdk_auth", {}).get("redirect_domain2")
        ][0]
        sdk_auth = sso_payload["corpapp"]["sdk_auth"]
        self.assertEqual(sdk_auth["redirect_domain2"], "wxwork.jiandaoyun.com")
        self.assertEqual(sdk_auth["aes_app_id"], "aes-app-1")
        order_payload = [
            call["payload"]
            for call in call_log
            if call["path"] == "/wwopen/developer/order/add"
        ][0]
        self.assertEqual(order_payload["auditorder"]["suiteid"], 1009479)
        self.assertEqual(order_payload["auditorder"]["corpappid"], "app-1")

    def test_start_bind_uses_jdy_corp_default_userid_when_requested_userid_empty(self):
        call_log = []
        service, jdy_transport, _wecom_transport = make_service(call_log)

        result = service.start_bind(
            JdyWecomBindInput(
                enterprise_name="上海测试客户",
                plain_corp_id="ww001",
                requested_user_id="",
                suite_id=1,
                suite_scenario="main",
                wecom_suiteid=1009479,
                suite_name="简道云",
            ),
            now=datetime(2026, 6, 16, 10, 0, 0),
        )

        owner_call = [
            call
            for call in jdy_transport.calls
            if call["path"] == "/api/fx_sa/wxwork/get_owner"
        ][0]
        install_call = [
            call
            for call in jdy_transport.calls
            if call["path"] == "/api/fx_sa/wxwork/install_corp_deploy"
        ][0]
        self.assertEqual(owner_call["payload"]["user_id"], "old-user")
        self.assertEqual(install_call["payload"]["tenant_id"], "old-user")
        self.assertEqual(result.context["jdy"]["requested_user_id"], "")
        self.assertEqual(result.context["jdy"]["effective_user_id"], "old-user")
        self.assertEqual(result.context["jdy"]["effective_user_id_source"], "jdy_corp_default_userid")
        self.assertTrue(result.context["jdy"]["incoming_userid_empty"])

    def test_submit_online_uses_saved_audit_order(self):
        call_log = []
        service, _jdy_transport, wecom_transport = make_service(call_log)

        result = service.submit_online_order({"wecom": {"auditorderid": "order-1"}})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.context, {"wecom": {"auditorder_status": 5}})
        self.assertEqual(wecom_transport.calls[-1]["path"], "/wwopen/developer/order/set")

    def test_start_bind_rejects_owner_that_cannot_bind_without_install_or_save(self):
        call_log = []
        service, _jdy_transport, _wecom_transport = make_service(call_log, can_bind_corp_secret=False)

        with self.assertRaises(OwnerCannotBindError):
            service.start_bind(make_request(), now=datetime(2026, 6, 16, 10, 0, 0))

        all_paths = [call["path"] for call in call_log]
        self.assertNotIn("/api/fx_sa/wxwork/install_corp_deploy", all_paths)
        self.assertNotIn("/wwopen/developer/customApp/tpl/corpApp", all_paths)

    def test_start_bind_allows_owner_that_can_update_existing_corp_secret(self):
        call_log = []
        service, _jdy_transport, _wecom_transport = make_service(
            call_log,
            can_bind_corp_secret=False,
            can_update_corp_secret=True,
        )

        result = service.start_bind(make_request(), now=datetime(2026, 6, 16, 10, 0, 0))

        all_paths = [call["path"] for call in call_log]
        self.assertIn("/api/fx_sa/wxwork/install_corp_deploy", all_paths)
        self.assertIn("/wwopen/developer/customApp/tpl/corpApp", all_paths)
        self.assertEqual(result.context["wecom"]["token"], "token-secret")

    def test_start_bind_uses_jdy_corp_name_candidate_before_wrong_incoming_short_name(self):
        call_log = []
        service, _jdy_transport, wecom_transport = make_service(
            call_log,
            corp_name="温州华绘印务",
            apps_by_keyword={
                "温州华绘印务": [
                    {
                        "app_id": "app-huahui",
                        "authcorp_name": "温州华绘印务",
                        "name": "简道云",
                        "logo": "logo-url",
                        "description": "desc",
                        "customized_app_status": 0,
                        "sdk_auth": {"aes_app_id": "aes-huahui"},
                    }
                ],
                "温州市华绘印务有限公司": [],
            },
        )

        result = service.start_bind(
            JdyWecomBindInput(
                enterprise_name="温州市华绘印务有限公司",
                enterprise_short_name="温州市华绘印务有限公司",
                plain_corp_id="ww-huahui",
                requested_user_id="user-1",
                suite_id=1,
                suite_scenario="main",
                wecom_suiteid=1009479,
                suite_name="简道云",
            ),
            now=datetime(2026, 6, 16, 10, 0, 0),
        )

        self.assertEqual(result.context["wecom"]["app_id"], "app-huahui")
        self.assertEqual(result.context["wecom"]["lookup_source"], "jdy_corp_name")
        self.assertEqual(
            [call["params"]["corp_name_keyword"] for call in wecom_transport.calls if call["method"] == "GET"],
            ["温州华绘印务", "温州市华绘印务有限公司"],
        )

    def test_start_bind_rejects_empty_install_result_without_wecom_writes(self):
        call_log = []
        service, _jdy_transport, _wecom_transport = make_service(
            call_log,
            install_response={"tenant_id": "", "owner_id": ""},
        )

        with self.assertRaises(JdyAdminError):
            service.start_bind(make_request(), now=datetime(2026, 6, 16, 10, 0, 0))

        all_paths = [call["path"] for call in call_log]
        self.assertNotIn("/wwopen/developer/customApp/tpl/corpApp", all_paths)
        self.assertNotIn("/wwopen/developer/order/add", all_paths)

    def test_start_bind_rejects_empty_install_owner_without_wecom_writes(self):
        call_log = []
        service, _jdy_transport, _wecom_transport = make_service(
            call_log,
            install_response={"tenant_id": "user-1", "owner_id": ""},
        )

        with self.assertRaises(JdyAdminError):
            service.start_bind(make_request(), now=datetime(2026, 6, 16, 10, 0, 0))

        all_paths = [call["path"] for call in call_log]
        self.assertNotIn("/wwopen/developer/customApp/tpl/corpApp", all_paths)
        self.assertNotIn("/wwopen/developer/order/add", all_paths)


if __name__ == "__main__":
    unittest.main()
