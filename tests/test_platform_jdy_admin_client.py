import unittest

from rpa_platform.integrations.jdy_admin_client import (
    AmbiguousCorpDeployError,
    JdyAdminClient,
    JdyAdminTransport,
    JdyInstallRequest,
    MissingCorpDeployError,
)


class FakeTransport(JdyAdminTransport):
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def post_json(self, path, payload):
        self.calls.append({"path": path, "payload": payload})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class JdyAdminClientTest(unittest.TestCase):
    def test_search_corp_deploy_list_normalizes_rows(self):
        transport = FakeTransport(
            [
                {
                    "has_more": False,
                    "corp_deploy_list": [
                        {
                            "_id": "row-1",
                            "corp_id": "corp-secret",
                            "name": "安徽云速付",
                            "tenant_id": "",
                            "suite_name": "简道云",
                            "integrate_suite_name": "简道云",
                            "suite_id": 1,
                            "suite_scenario": "main",
                        }
                    ],
                }
            ]
        )
        client = JdyAdminClient(transport)

        result = client.search_corp_deploy_list("安徽云速付")

        self.assertFalse(result.has_more)
        self.assertEqual(result.rows[0].deploy_id, "row-1")
        self.assertEqual(result.rows[0].default_userid, "row-1")
        self.assertEqual(result.rows[0].corp_id, "corp-secret")
        self.assertEqual(result.rows[0].suite_id, 1)
        self.assertEqual(transport.calls[0]["path"], "/api/fx_sa/wxwork/get_corp_deploy_list")
        self.assertEqual(transport.calls[0]["payload"]["filter"], "安徽云速付")

    def test_resolve_unique_uses_corp_id_without_name_fallback(self):
        transport = FakeTransport(
            [
                {
                    "has_more": False,
                    "corp_deploy_list": [
                        {
                            "_id": "row-1",
                            "corp_id": "corp-secret",
                            "name": "安徽云速付",
                            "tenant_id": "",
                            "suite_name": "简道云",
                            "integrate_suite_name": "简道云",
                            "suite_id": 1,
                            "suite_scenario": "main",
                        }
                    ],
                },
            ]
        )
        client = JdyAdminClient(transport)

        row = client.resolve_unique_corp(plain_corp_id="ww-demo", enterprise_name="安徽云速付")

        self.assertEqual(row.name, "安徽云速付")
        self.assertEqual([call["payload"]["filter"] for call in transport.calls], ["ww-demo"])

    def test_resolve_unique_allows_empty_corp_id_and_uses_enterprise_name(self):
        transport = FakeTransport(
            [
                {
                    "has_more": False,
                    "corp_deploy_list": [
                        {
                            "corp_id": "corp-secret",
                            "name": "安徽云速付",
                            "tenant_id": "",
                            "suite_name": "简道云",
                            "integrate_suite_name": "简道云",
                            "suite_id": 1,
                            "suite_scenario": "main",
                        }
                    ],
                },
            ]
        )
        client = JdyAdminClient(transport)

        row = client.resolve_unique_corp(plain_corp_id="", enterprise_name="安徽云速付")

        self.assertEqual(row.corp_id, "corp-secret")
        self.assertEqual([call["payload"]["filter"] for call in transport.calls], ["安徽云速付"])

    def test_resolve_unique_reports_chinese_business_errors(self):
        with self.assertRaisesRegex(MissingCorpDeployError, "根据 CorpID 未检索到企业"):
            JdyAdminClient(
                FakeTransport(
                    [
                        {"has_more": False, "corp_deploy_list": []},
                    ]
                )
            ).resolve_unique_corp("ww-demo", "")

        duplicate_name = {
            "has_more": False,
            "corp_deploy_list": [
                {"corp_id": "a", "name": "安徽云速付", "suite_id": 1, "suite_scenario": "main"},
                {"corp_id": "b", "name": "安徽云速付", "suite_id": 1, "suite_scenario": "main"},
            ],
        }
        with self.assertRaisesRegex(AmbiguousCorpDeployError, "根据企业名称检索到多家企业"):
            JdyAdminClient(FakeTransport([duplicate_name])).resolve_unique_corp("", "安徽云速付")

        with self.assertRaisesRegex(MissingCorpDeployError, "请填写 CorpID 或企业名称后重试"):
            JdyAdminClient(FakeTransport([])).resolve_unique_corp("", "")

    def test_resolve_unique_rejects_no_match_and_multiple_matches(self):
        with self.assertRaises(MissingCorpDeployError):
            JdyAdminClient(
                FakeTransport(
                    [
                        {"has_more": False, "corp_deploy_list": []},
                        {"has_more": False, "corp_deploy_list": []},
                    ]
                )
            ).resolve_unique_corp("ww-demo", "安徽云速付")

        duplicate = {
            "has_more": False,
            "corp_deploy_list": [
                {"corp_id": "a", "name": "安徽云速付", "suite_id": 1, "suite_scenario": "main"},
                {"corp_id": "b", "name": "安徽云速付", "suite_id": 1, "suite_scenario": "main"},
            ],
        }
        with self.assertRaises(AmbiguousCorpDeployError):
            JdyAdminClient(FakeTransport([duplicate])).resolve_unique_corp("ww-demo", "安徽云速付")

    def test_check_owner_and_install_bind_use_expected_payloads(self):
        transport = FakeTransport(
            [
                {
                    "can_bind_corp_secret": True,
                    "can_update_corp_secret": True,
                    "owner": {"corp_id": "owner-corp-secret"},
                    "corp": {
                        "name": "安徽云速付",
                        "token": "existing-token",
                        "encoding_aes_key": "existing-aes",
                    },
                },
                {"tenant_id": "user-1", "owner_id": "user-1"},
            ]
        )
        client = JdyAdminClient(transport)

        owner = client.check_wework_owner("user-1", suite_id=1, suite_scenario="main")
        install = client.install_corp_deploy(
            JdyInstallRequest(
                corp_id="corp-secret",
                corp_name="安徽云速付",
                tenant_id="user-1",
                token="token-secret",
                encoding_aes_key="aes-secret",
                suite_id=1,
                suite_scenario="main",
            )
        )

        self.assertTrue(owner.can_bind_corp_secret)
        self.assertTrue(owner.can_update_corp_secret)
        self.assertEqual(owner.owner_corp_id, "owner-corp-secret")
        self.assertEqual(owner.corp_name, "安徽云速付")
        self.assertEqual(owner.existing_token, "existing-token")
        self.assertEqual(owner.existing_encoding_aes_key, "existing-aes")
        self.assertEqual(install.owner_id, "user-1")
        self.assertEqual(transport.calls[0]["path"], "/api/fx_sa/wxwork/get_owner")
        self.assertEqual(transport.calls[1]["path"], "/api/fx_sa/wxwork/install_corp_deploy")
        self.assertEqual(transport.calls[0]["payload"]["user_id"], "user-1")
        self.assertEqual(transport.calls[1]["payload"]["user_id"], "user-1")
        self.assertEqual(transport.calls[1]["payload"]["tenant_id"], "user-1")
        self.assertEqual(transport.calls[1]["payload"]["encoding_aes_key"], "aes-secret")

    def test_blank_userid_omits_owner_and_install_user_fields_to_preserve_jdy_default(self):
        transport = FakeTransport(
            [
                {
                    "can_bind_corp_secret": True,
                    "can_update_corp_secret": False,
                },
                {"tenant_id": "backend-default-user", "owner_id": "backend-default-user"},
            ]
        )
        client = JdyAdminClient(transport)

        owner = client.check_wework_owner("", suite_id=1, suite_scenario="main")
        install = client.install_corp_deploy(
            JdyInstallRequest(
                corp_id="corp-secret",
                corp_name="安徽云速付",
                tenant_id="",
                token="token-secret",
                encoding_aes_key="aes-secret",
                suite_id=1,
                suite_scenario="main",
            )
        )

        self.assertTrue(owner.can_bind_corp_secret)
        self.assertEqual(install.owner_id, "backend-default-user")
        self.assertNotIn("user_id", transport.calls[0]["payload"])
        self.assertNotIn("user_id", transport.calls[1]["payload"])
        self.assertNotIn("tenant_id", transport.calls[1]["payload"])


if __name__ == "__main__":
    unittest.main()
