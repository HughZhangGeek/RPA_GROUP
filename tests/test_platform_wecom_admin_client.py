import unittest

from rpa_platform.integrations.wecom_admin_client import (
    AmbiguousWecomAppError,
    WecomAdminError,
    MissingWecomAppError,
    RetryableWecomOrderError,
    WecomAdminClient,
    WecomAdminTransport,
    WecomCustomApp,
    WecomSaveAppRequest,
    WecomSessionExpiredError,
)


class FakeTransport(WecomAdminTransport):
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_json(self, path, params, headers):
        self.calls.append({"method": "GET", "path": path, "params": params, "headers": headers})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post_json(self, path, payload, headers):
        self.calls.append({"method": "POST", "path": path, "payload": payload, "headers": headers})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_app(raw=None):
    return WecomCustomApp(
        app_id="app-1",
        authcorp_name="上海测试客户",
        name="简道云",
        logo="logo-url",
        description="desc",
        customized_app_status=0,
        aes_app_id="aes-app-1",
        raw=raw
        or {
            "app_id": "app-1",
            "authcorp_name": "上海测试客户",
            "name": "简道云",
            "logo": "logo-url",
            "description": "desc",
            "customized_app_status": 0,
            "sdk_auth": {"aes_app_id": "aes-app-1"},
        },
    )


class WecomAdminClientTest(unittest.TestCase):
    def test_resolve_unique_custom_app_uses_runbook_corpapp_response(self):
        transport = FakeTransport(
            [
                {
                    "data": {
                        "total": 1,
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
                        ],
                    }
                }
            ]
        )
        client = WecomAdminClient(transport)

        app = client.resolve_unique_custom_app(
            suiteid=1,
            enterprise_name="上海测试客户",
            suite_name="简道云",
        )

        self.assertEqual(app.app_id, "app-1")
        self.assertEqual(app.authcorp_name, "上海测试客户")
        self.assertEqual(app.name, "简道云")
        self.assertEqual(app.logo, "logo-url")
        self.assertEqual(app.description, "desc")
        self.assertEqual(app.customized_app_status, 0)
        self.assertEqual(app.aes_app_id, "aes-app-1")
        self.assertEqual(app.raw["sdk_auth"]["aes_app_id"], "aes-app-1")
        self.assertEqual(transport.calls[0]["method"], "GET")
        self.assertEqual(transport.calls[0]["path"], "/wwopen/developer/customApp/tpl/app/list")
        self.assertEqual(
            transport.calls[0]["params"],
            {
                "lang": "zh_CN",
                "ajax": 1,
                "f": "json",
                "suiteid": "1",
                "scene": 1,
                "corp_name_keyword": "上海测试客户",
                "offset": 0,
                "limit": 10,
                "random": 0,
            },
        )
        self.assertEqual(
            transport.calls[0]["headers"],
            {
                "x-wecom-developer-page": "/sass/customApp/tpl/info",
                "x-wecom-developer-perm": "50",
            },
        )

    def test_resolve_unique_custom_app_accepts_real_corpapp_list_wrapper(self):
        transport = FakeTransport(
            [
                {
                    "data": {
                        "total": 1,
                        "corpapp_list": {
                            "corpapp": [
                                {
                                    "app_id": "app-1",
                                    "authcorp_name": "南京示例集团",
                                    "name": "简道云",
                                    "customized_app_status": 0,
                                    "sdk_auth": {"aes_app_id": "aes-app-1"},
                                }
                            ]
                        },
                    }
                }
            ]
        )

        app = WecomAdminClient(transport).resolve_unique_custom_app(
            suiteid=1009479,
            enterprise_name="南京示例集团",
            suite_name="简道云",
        )

        self.assertEqual(app.app_id, "app-1")
        self.assertEqual(app.authcorp_name, "南京示例集团")
        self.assertEqual(app.aes_app_id, "aes-app-1")

    def test_resolve_unique_custom_app_filters_authcorp_name_and_app_name(self):
        transport = FakeTransport(
            [
                {
                    "data": {
                        "corpapp": [
                            {
                                "app_id": "wrong-corp",
                                "authcorp_name": "别的客户",
                                "name": "简道云",
                                "sdk_auth": {"aes_app_id": "aes-wrong"},
                            },
                            {
                                "app_id": "wrong-name",
                                "authcorp_name": "上海测试客户",
                                "name": "别的应用",
                                "sdk_auth": {"aes_app_id": "aes-wrong"},
                            },
                        ]
                    }
                }
            ]
        )

        with self.assertRaises(MissingWecomAppError):
            WecomAdminClient(transport).resolve_unique_custom_app(
                suiteid=1,
                enterprise_name="上海测试客户",
                suite_name="简道云",
            )

    def test_resolve_unique_custom_app_rejects_ambiguous_matches(self):
        duplicate = {
            "data": {
                "corpapp": [
                    {
                        "app_id": "app-1",
                        "authcorp_name": "上海测试客户",
                        "name": "简道云",
                        "sdk_auth": {"aes_app_id": "aes-app-1"},
                    },
                    {
                        "app_id": "app-2",
                        "authcorp_name": "上海测试客户",
                        "name": "简道云",
                        "sdk_auth": {"aes_app_id": "aes-app-2"},
                    },
                ]
            }
        }

        with self.assertRaises(AmbiguousWecomAppError):
            WecomAdminClient(FakeTransport([duplicate])).resolve_unique_custom_app(
                suiteid=1,
                enterprise_name="上海测试客户",
                suite_name="简道云",
            )

    def test_resolve_unique_custom_app_reports_expired_session(self):
        response = {"result": {"errCode": -3, "message": "outsession"}}

        with self.assertRaises(WecomSessionExpiredError):
            WecomAdminClient(FakeTransport([response])).resolve_unique_custom_app(
                suiteid=1,
                enterprise_name="上海测试客户",
                suite_name="简道云",
            )

    def test_save_development_info_posts_runbook_payload_and_returns_response_corpapp(self):
        transport = FakeTransport(
            [
                {
                    "data": {
                        "corpapp": {
                            "app_id": "app-1",
                            "suiteid": "1",
                            "name": "简道云",
                            "saved": True,
                        }
                    }
                }
            ]
        )
        client = WecomAdminClient(transport)

        result = client.save_development_info(
            WecomSaveAppRequest(
                suiteid=1009479,
                app=make_app(
                    raw={
                        "app_id": "old-app",
                        "authcorp_name": "上海测试客户",
                        "name": "旧名称",
                        "logo": "old-logo",
                        "description": "old-desc",
                        "customized_app_status": 0,
                        "sdk_auth": {"aes_app_id": "aes-app-1"},
                        "raw_only": "kept",
                    }
                ),
                homeurl="https://wxwork.jiandaoyun.com/home",
                callbackurl="https://wxwork.jiandaoyun.com/callback",
                redirect_domain="wxwork.jiandaoyun.com",
                token="token-secret",
                encoding_aes_key="aes-secret",
            )
        )

        call = transport.calls[0]
        self.assertEqual(call["path"], "/wwopen/developer/customApp/tpl/corpApp")
        self.assertEqual(
            call["headers"],
            {
                "x-wecom-developer-page": "/sass/customApp/app/create",
                "x-wecom-developer-perm": "50",
            },
        )
        self.assertEqual(set(call["payload"].keys()), {"suiteid", "corpapp"})
        self.assertEqual(call["payload"]["suiteid"], "1009479")
        corpapp = call["payload"]["corpapp"]
        self.assertEqual(corpapp["raw_only"], "kept")
        self.assertEqual(corpapp["app_id"], "app-1")
        self.assertEqual(corpapp["suiteid"], 1009479)
        self.assertEqual(corpapp["page_type"], "CREATE")
        self.assertEqual(corpapp["name"], "简道云")
        self.assertEqual(corpapp["name_pinyin"], "jiandaoyun")
        self.assertEqual(corpapp["logo"], "logo-url")
        self.assertEqual(corpapp["description"], "desc")
        self.assertEqual(corpapp["homeurl"], "https://wxwork.jiandaoyun.com/home")
        self.assertEqual(corpapp["redirect_domain"], "wxwork.jiandaoyun.com")
        self.assertEqual(corpapp["domain_belong_to"], 0)
        self.assertEqual(corpapp["jssdkdomain_list"], {"domains": []})
        self.assertEqual(corpapp["white_ip_list"], {"ip": []})
        self.assertEqual(corpapp["callbackurl"], "https://wxwork.jiandaoyun.com/callback")
        self.assertEqual(corpapp["token"], "token-secret")
        self.assertEqual(corpapp["aeskey"], "aes-secret")
        self.assertTrue(corpapp["enter_homeurl_in_wx"])
        self.assertFalse(corpapp["is_homeurl_miniprogram"])
        self.assertEqual(corpapp["miniprogram_enter_path"], "")
        self.assertEqual(corpapp["miniprogramInfo"], {})
        self.assertEqual(result, {"app_id": "app-1", "suiteid": "1", "name": "简道云", "saved": True})

    def test_set_target_privileges_uses_suite_payload_and_returns_privilege_list(self):
        transport = FakeTransport(
            [
                {
                    "data": {
                        "privilege_list": [
                            {"id": 310000, "b_check": False, "name": "通讯录", "keep": "a"},
                            {"id": 310001, "b_check": False, "name": "客户", "keep": "b"},
                            {"id": 310002, "b_check": False, "name": "群聊", "keep": "c"},
                            {"id": 310100, "b_check": False, "name": "会话", "keep": "d"},
                            {"id": 10006, "b_check": False, "name": "身份", "keep": "e"},
                            {"id": 10010, "b_check": False, "name": "登录", "keep": "f"},
                            {"id": 42, "b_check": False, "name": "非目标", "keep": "g"},
                        ]
                    }
                },
                {"data": {"privilege_list": [{"id": 310000, "b_check": True}]}},
            ]
        )
        client = WecomAdminClient(transport)

        result = client.set_target_privileges(suiteid=1, app_id="app-1")

        self.assertEqual(
            [call["path"] for call in transport.calls],
            [
                "/wwopen/api/customApp/privilege/getCustomizedAppPrivilege",
                "/wwopen/api/customApp/privilege/setCustomizedAppPrivilege",
            ],
        )
        self.assertEqual(transport.calls[0]["payload"], {"thirdapp_id": ["app-1"], "suiteid": "1"})
        self.assertEqual(
            transport.calls[0]["headers"],
            {
                "x-wecom-developer-page": "/sass/customApp/app/detail",
                "x-wecom-developer-perm": "50,51",
            },
        )
        set_call = transport.calls[1]
        self.assertEqual(set_call["payload"]["thirdapp_id"], ["app-1"])
        self.assertEqual(set_call["payload"]["suiteid"], "1")
        self.assertNotIn("corpappid", set_call["payload"])
        self.assertNotIn("privileges", set_call["payload"])
        privileges = set_call["payload"]["privilege_list"]
        target_ids = {310000, 310001, 310002, 310100, 10006, 10010}
        self.assertTrue(all(item["b_check"] for item in privileges if item["id"] in target_ids))
        self.assertFalse([item for item in privileges if item["id"] == 42][0]["b_check"])
        self.assertEqual([item for item in privileges if item["id"] == 310000][0]["keep"], "a")
        self.assertEqual(result, [{"id": 310000, "b_check": True}])

    def test_set_trial_rule_uses_nested_try_rule_info(self):
        transport = FakeTransport(
            [
                {"data": {"base_price_info": {"old": True}}},
                {
                    "data": {
                        "is_already_set_try_info": True,
                        "base_price_info": {
                            "try_rule_info": {
                                "try_time": 60,
                                "second_try_time": 15,
                            }
                        },
                    }
                },
            ]
        )
        client = WecomAdminClient(transport)

        result = client.set_trial_rule(app_id="app-1")

        self.assertEqual(
            [call["path"] for call in transport.calls],
            [
                "/wwopen/api/customApp/price/GetStandardPriceInfoForCA",
                "/wwopen/api/customApp/price/SetStandardPriceInfoForCA",
            ],
        )
        self.assertEqual(transport.calls[0]["payload"], {"corpappid": "app-1"})
        payload = transport.calls[1]["payload"]
        self.assertEqual(
            payload,
            {
                "corpappid": "app-1",
                "base_price_info": {
                    "try_rule_info": {
                        "try_rule_type": 2,
                        "try_time": 60,
                        "second_try_time": 15,
                        "prove_file": {"file_id": None, "file_name": None},
                    }
                },
                "clear_base_price_info": False,
            },
        )
        self.assertTrue(result["data"]["is_already_set_try_info"])

    def test_set_sso_redirect_domain_posts_sdk_auth_inside_corpapp(self):
        transport = FakeTransport(
            [
                {
                    "data": {
                        "corpapp": {
                            "app_id": "app-1",
                            "sdk_auth": {
                                "aes_app_id": "aes-app-1",
                                "redirect_domain2": "wxwork.jiandaoyun.com",
                            },
                        }
                    }
                }
            ]
        )
        client = WecomAdminClient(transport)

        client.set_sso_redirect_domain(
            suiteid=1,
            app_id="app-1",
            aes_app_id="aes-app-1",
            redirect_domain="wxwork.jiandaoyun.com",
        )

        call = transport.calls[0]
        self.assertEqual(call["path"], "/wwopen/developer/customApp/tpl/corpApp")
        self.assertEqual(
            call["headers"],
            {
                "x-wecom-developer-page": "/sass/customApp/app/detail/sso",
                "x-wecom-developer-perm": "50",
            },
        )
        self.assertEqual(
            call["payload"],
            {
                "suiteid": "1",
                "corpapp": {
                    "app_id": "app-1",
                    "sdk_auth": {
                        "aes_app_id": "aes-app-1",
                        "redirect_domain2": "wxwork.jiandaoyun.com",
                        "bundleid": "",
                        "signature_android": "",
                        "packagename": "",
                        "b_ios": False,
                        "b_android": False,
                    },
                },
            },
        )

    def test_save_development_info_rejects_missing_response_corpapp(self):
        client = WecomAdminClient(FakeTransport([{"data": {}}]))

        with self.assertRaises(WecomAdminError):
            client.save_development_info(
                WecomSaveAppRequest(
                    suiteid=1009479,
                    app=make_app(),
                    homeurl="https://wxwork.jiandaoyun.com/home",
                    callbackurl="https://wxwork.jiandaoyun.com/callback",
                    redirect_domain="wxwork.jiandaoyun.com",
                    token="token-secret",
                    encoding_aes_key="aes-secret",
                )
            )

    def test_target_privilege_write_accepts_empty_success_response(self):
        transport = FakeTransport(
            [
                {"data": {"privilege_list": [{"id": 310000, "b_check": False}]}},
                {"data": {}},
            ]
        )
        client = WecomAdminClient(transport)

        result = client.set_target_privileges(suiteid=1, app_id="app-1")

        self.assertEqual(result, [{"id": 310000, "b_check": True}])

    def test_target_privilege_read_rejects_missing_privilege_list_without_writing(self):
        transport = FakeTransport([{"data": {}}])
        client = WecomAdminClient(transport)

        with self.assertRaises(WecomAdminError):
            client.set_target_privileges(suiteid=1, app_id="app-1")

        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0]["path"], "/wwopen/api/customApp/privilege/getCustomizedAppPrivilege")

    def test_target_privilege_read_rejects_non_list_privilege_list_without_writing(self):
        transport = FakeTransport([{"data": {"privilege_list": {"not": "a-list"}}}])
        client = WecomAdminClient(transport)

        with self.assertRaises(WecomAdminError):
            client.set_target_privileges(suiteid=1, app_id="app-1")

        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0]["path"], "/wwopen/api/customApp/privilege/getCustomizedAppPrivilege")

    def test_trial_rule_rejects_missing_confirmation(self):
        transport = FakeTransport(
            [
                {"data": {"base_price_info": {"old": True}}},
                {"data": {"base_price_info": {"try_rule_info": {"try_time": 60, "second_try_time": 14}}}},
            ]
        )
        client = WecomAdminClient(transport)

        with self.assertRaises(WecomAdminError):
            client.set_trial_rule(app_id="app-1")

    def test_sso_redirect_domain_rejects_missing_confirmation(self):
        client = WecomAdminClient(FakeTransport([{"data": {"corpapp": {"sdk_auth": {}}}}]))

        with self.assertRaises(WecomAdminError):
            client.set_sso_redirect_domain(
                suiteid=1,
                app_id="app-1",
                aes_app_id="aes-app-1",
                redirect_domain="wxwork.jiandaoyun.com",
            )

    def test_create_online_order_posts_expected_payload_and_returns_runbook_order(self):
        transport = FakeTransport(
            [
                {
                    "data": {
                        "auditorder": {
                            "auditorderid": "order-1",
                            "corpappid": "app-1",
                            "authcorp_name": "上海测试客户",
                            "status": 1,
                        }
                    }
                }
            ]
        )
        client = WecomAdminClient(transport)

        order = client.create_online_order(suiteid=1009479, app_id="app-1")

        call = transport.calls[0]
        self.assertEqual(call["path"], "/wwopen/developer/order/add")
        self.assertEqual(
            call["headers"],
            {
                "x-wecom-developer-page": "/sass/customApp/deploy/list",
                "x-wecom-developer-perm": "51",
            },
        )
        self.assertEqual(call["payload"], {"auditorder": {"suiteid": 1009479, "corpappid": "app-1"}, "skipNotice": False})
        self.assertEqual(order.auditorderid, "order-1")
        self.assertEqual(order.corpappid, "app-1")
        self.assertEqual(order.authcorp_name, "上海测试客户")
        self.assertEqual(order.status, 1)

    def test_create_online_order_rejects_missing_response_auditorder(self):
        client = WecomAdminClient(FakeTransport([{"data": {}}]))

        with self.assertRaises(WecomAdminError):
            client.create_online_order(suiteid=1009479, app_id="app-1")

    def test_submit_online_order_returns_order_and_preserves_retryable_order_error(self):
        transport = FakeTransport(
            [
                {
                    "data": {
                        "auditorder": {
                            "auditorderid": "order-1",
                            "corpappid": "app-1",
                            "authcorp_name": "上海测试客户",
                            "status": 5,
                        }
                    }
                },
                RetryableWecomOrderError("locked"),
            ]
        )
        client = WecomAdminClient(transport)

        order = client.submit_online_order("order-1")

        call = transport.calls[0]
        self.assertEqual(call["path"], "/wwopen/developer/order/set")
        self.assertEqual(
            call["headers"],
            {
                "x-wecom-developer-page": "/sass/customApp/deploy/detail",
                "x-wecom-developer-perm": "51",
            },
        )
        self.assertEqual(call["payload"], {"auditorder": {"auditorderid": "order-1", "status": 5}})
        self.assertEqual(order.auditorderid, "order-1")
        self.assertEqual(order.corpappid, "app-1")
        self.assertEqual(order.authcorp_name, "上海测试客户")
        self.assertEqual(order.status, 5)

        with self.assertRaises(RetryableWecomOrderError):
            client.submit_online_order("order-2")

    def test_submit_online_order_rejects_missing_response_auditorder(self):
        client = WecomAdminClient(FakeTransport([{"data": {}}]))

        with self.assertRaises(WecomAdminError):
            client.submit_online_order("order-1")


if __name__ == "__main__":
    unittest.main()
