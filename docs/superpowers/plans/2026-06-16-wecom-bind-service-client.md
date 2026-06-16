# 企微绑定接口服务封装 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Mac 上已真实跑通的简道云企微绑定接口链路封装成 `rpa_platform` 下可调用、可 fake、可 dry-run 的服务能力。

**Architecture:** 旧 `RPA.py` 是线上稳定系统，本计划不读取它的业务逻辑、不修改它、不部署、不重启。企微绑定作为平台服务能力独立落在 `rpa_platform/integrations` 与 `rpa_platform/services`，通过注入 transport 复用 Windows 登录态 Cookie/Profile；Windows 企业微信客户端 RPA 的建群、群发、弹窗、风控恢复不进入本计划。

**Tech Stack:** Python 3.8 兼容代码、`dataclasses`、`typing.Protocol`、SQLiteStore 现有任务状态、`unittest`、fake transport、现有脱敏工具、现有 `conda run -n RPA_GROUP python -m unittest` 验证链路。

---

## Current Boundaries

- Repository: `/Users/hugh/jdycsm_project/RPA_GROUP`
- Branch: `feature/rpa-platform-foundation`
- Do not modify `RPA.py`.
- Do not deploy or restart services.
- Do not commit `.env`, `config.py`, logs, databases, screenshots, zip files, Cookie, cURL, or `.local/platform-dryrun.db`.
- Protect:
  - `docs/superpowers/handoff/2026-06-15-rpa-platform-mac-dryrun-next-handoff.md`
  - `docs/jdy_wework_bind_full_flow_runbook.md`
  - `.local/platform-dryrun.db`
- Commit messages, PR title, and PR body must be Chinese unless explicitly asked otherwise.
- Source of truth for the business sequence: `docs/jdy_wework_bind_full_flow_runbook.md`

## Implementation Boundary

This plan builds one service capability:

```text
JdyWecomBindService
-> Jiandaoyun admin client
-> WeCom developer admin API client
-> fake transports for unit tests and dry-run
-> task runner adapter that can be claimed by the existing scheduler
```

This plan does not build:

```text
Windows 企业微信客户端 RPA
外部群创建
群发消息
客户端弹窗处理
风控截图识别与恢复
真实 Cookie 读取器
真实浏览器控制
```

## Correct Business Sequence

The service must execute this order:

```text
1. 简道云查企业部署行
2. 企微查企业应用
3. 生成 token/aeskey
4. 派生 homeurl/callbackurl/redirect_domain
5. 简道云校验 User_ID
6. 简道云 install_corp_deploy 写入 token/aeskey
7. 企微保存开发信息并触发回调校验
8. 企微设置权限
9. 企微设置 60+15 试用
10. 企微设置授权登录域
11. 企微 order/add 创建上线单
12. 进入 waiting_wecom_online_delay，next_check_at = now + 5 minutes
13. 到点后 order/set 提交上线
```

The previous hybrid/browser-use flow order must not be copied into this service. The key correction is that `jdy_install_bind` happens before `wecom_save_development_info`.

## File Structure

- Create `rpa_platform/integrations/wecom_admin_client.py`
  - Typed WeCom developer admin API client.
  - Accepts injected `WecomAdminTransport`.
  - Builds exact endpoint paths, headers, and payload shapes from the runbook.
  - Normalizes responses into dataclasses.
  - Contains no Cookie acquisition logic.
- Create `rpa_platform/services/__init__.py`
  - Package marker for platform service orchestration.
- Create `rpa_platform/services/wecom_bind_service.py`
  - Orchestrates the full bind service sequence.
  - Generates secrets through injected generator.
  - Returns a resumable context after `order/add`.
  - Submits `order/set` from saved context after the delay.
- Create `rpa_platform/worker/wecom_bind_runner.py`
  - Small scheduler-compatible runner that calls `JdyWecomBindService`.
  - Handles `waiting_wecom_online_delay` and retryable `order/set` failures.
- Modify `rpa_platform/domain/state_machine.py`
  - Add `WAITING_WECOM_ONLINE_DELAY`.
  - Allow transitions from `RUNNING` to this state and from this state to `CHECKING_LOGIN`, `RUNNING`, `SUCCESS`, `FAILED`, `WAITING_MANUAL_INTERVENTION`, `CANCELLED`.
- Modify `rpa_platform/storage/sqlite_store.py`
  - Include `waiting_wecom_online_delay` in runnable delayed-task claiming, using the existing `next_check_at` pattern.
- Modify `rpa_platform/domain/default_flows.py`
  - Add `WECOM_BIND_SERVICE_FLOW_STEPS`.
  - Keep `WECOM_APP_LAUNCH_FLOW_STEPS` available for existing tests until a later cleanup plan retires it.
- Modify `scripts/dev/run_platform_dryrun.py`
  - Keep existing dry-run behavior.
  - Add a service dry-run mode that uses fake Jdy and fake WeCom transports.
- Create `tests/test_platform_wecom_admin_client.py`
  - Unit tests for WeCom endpoint contracts, headers, payloads, response parsing, and retryable online-submit classification.
- Create `tests/test_platform_wecom_bind_service.py`
  - Unit tests for the full service order, context, delay state, redaction expectations, and submit-online resume.
- Create `tests/test_platform_wecom_bind_runner.py`
  - Unit tests for scheduler-compatible runner state changes.
- Modify `tests/test_platform_worker_scheduler.py`
  - Add coverage that delayed `waiting_wecom_online_delay` tasks are claimable only after `next_check_at`.
- Modify `tests/test_platform_dryrun_smoke.py`
  - Add smoke coverage for service dry-run output without secret leakage.

## Runtime Context Contract

The service writes these fields to task context:

```python
{
    "jdy": {
        "corp_secret_id": "corp-secret",
        "corp_name": "上海测试客户",
        "original_tenant_id": "old-user",
        "requested_user_id": "user-1",
        "install_tenant_id": "user-1",
        "install_owner_id": "user-1",
        "bound_user_id": "user-1",
        "suite_id": 1,
        "suite_scenario": "main",
        "suite_name": "简道云",
        "integrate_suite_name": "简道云"
    },
    "wecom": {
        "suiteid": 1009479,
        "suite_name": "简道云",
        "app_id": "app-1",
        "aes_app_id": "aes-app-1",
        "homeurl": "https://wxwork.jiandaoyun.com/wxwork/corp-secret/dashboard",
        "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/corp-secret/service",
        "redirect_domain": "wxwork.jiandaoyun.com",
        "token": "token-secret",
        "encoding_aes_key": "aes-secret",
        "auditorderid": "order-1",
        "auditorder_status": 1,
        "order_created_at": "2026-06-16 10:00:00"
    }
}
```

Raw `token` and `encoding_aes_key` may live in runtime context because the service must resume, but all task-detail output and dry-run console output must pass through existing redaction helpers.

## Task 1: WeCom Admin Client Endpoint Contracts

**Files:**
- Create: `rpa_platform/integrations/wecom_admin_client.py`
- Create: `tests/test_platform_wecom_admin_client.py`

- [ ] **Step 1: Write failing client contract tests**

Create `tests/test_platform_wecom_admin_client.py`:

```python
import unittest

from rpa_platform.integrations.wecom_admin_client import (
    RetryableWecomOrderError,
    WecomAdminClient,
    WecomAdminTransport,
    WecomCustomApp,
    WecomSaveAppRequest,
)


class FakeWecomTransport(WecomAdminTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get_json(self, path, params, headers):
        self.calls.append({"method": "GET", "path": path, "params": params, "headers": headers})
        return self.responses.pop(0)

    def post_json(self, path, payload, headers):
        self.calls.append({"method": "POST", "path": path, "payload": payload, "headers": headers})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class WecomAdminClientTest(unittest.TestCase):
    def test_resolve_unique_custom_app_uses_list_endpoint_and_headers(self):
        transport = FakeWecomTransport([
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
        ])
        client = WecomAdminClient(transport)

        app = client.resolve_unique_custom_app(
            enterprise_name="上海测试客户",
            suiteid=1009479,
            suite_name="简道云",
        )

        call = transport.calls[0]
        self.assertEqual(app.app_id, "app-1")
        self.assertEqual(app.aes_app_id, "aes-app-1")
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["path"], "/wwopen/developer/customApp/tpl/app/list")
        self.assertEqual(call["params"]["suiteid"], 1009479)
        self.assertEqual(call["params"]["corp_name_keyword"], "上海测试客户")
        self.assertEqual(call["headers"]["x-wecom-developer-page"], "/sass/customApp/tpl/info")
        self.assertEqual(call["headers"]["x-wecom-developer-perm"], "50")

    def test_save_development_info_inherits_template_fields_and_overlays_bind_fields(self):
        app = WecomCustomApp(
            app_id="app-1",
            authcorp_name="上海测试客户",
            name="简道云",
            logo="logo-url",
            description="desc",
            customized_app_status=0,
            aes_app_id="aes-app-1",
            raw={"kitid": "kit-1", "sdk_auth": {"aes_app_id": "aes-app-1"}},
        )
        transport = FakeWecomTransport([
            {"data": {"corpapp": {"app_id": "app-1", "homeurl": "home", "callbackurl": "callback", "redirect_domain": "wxwork.jiandaoyun.com", "sdk_auth": {"aes_app_id": "aes-app-1"}}}}
        ])
        client = WecomAdminClient(transport)

        result = client.save_development_info(
            WecomSaveAppRequest(
                suiteid=1009479,
                app=app,
                homeurl="home",
                callbackurl="callback",
                redirect_domain="wxwork.jiandaoyun.com",
                token="token-secret",
                encoding_aes_key="aes-secret",
            )
        )

        payload = transport.calls[0]["payload"]
        corpapp = payload["corpapp"]
        self.assertEqual(result["homeurl"], "home")
        self.assertEqual(corpapp["app_id"], "app-1")
        self.assertEqual(corpapp["name"], "简道云")
        self.assertEqual(corpapp["logo"], "logo-url")
        self.assertEqual(corpapp["description"], "desc")
        self.assertEqual(corpapp["callbackurl"], "callback")
        self.assertEqual(corpapp["token"], "token-secret")
        self.assertEqual(corpapp["aeskey"], "aes-secret")
        self.assertEqual(transport.calls[0]["headers"]["x-wecom-developer-page"], "/sass/customApp/app/create")

    def test_privilege_trial_sso_and_order_payloads_match_runbook(self):
        transport = FakeWecomTransport([
            {"data": {"privilege_list": [{"id": 310000, "b_check": False}, {"id": 10006, "b_check": False}]}},
            {"data": {"privilege_list": [{"id": 310000, "b_check": True}, {"id": 10006, "b_check": True}]}},
            {"data": {"base_price_info": {}}},
            {"data": {"is_already_set_try_info": True, "base_price_info": {"try_rule_info": {"try_time": 60, "second_try_time": 15}}}},
            {"data": {"corpapp": {"sdk_auth": {"aes_app_id": "aes-app-1", "redirect_domain2": "wxwork.jiandaoyun.com"}}}},
            {"data": {"auditorder": {"auditorderid": "order-1", "corpappid": "app-1", "authcorp_name": "上海测试客户", "status": 1}}},
        ])
        client = WecomAdminClient(transport)

        client.set_target_privileges(suiteid=1009479, app_id="app-1")
        client.set_trial_rule(app_id="app-1")
        client.set_sso_redirect_domain(suiteid=1009479, app_id="app-1", aes_app_id="aes-app-1", redirect_domain="wxwork.jiandaoyun.com")
        order = client.create_online_order(suiteid=1009479, app_id="app-1")

        privilege_write = transport.calls[1]
        trial_write = transport.calls[3]
        sso_write = transport.calls[4]
        order_add = transport.calls[5]
        self.assertEqual(privilege_write["path"], "/wwopen/api/customApp/privilege/setCustomizedAppPrivilege")
        self.assertEqual(privilege_write["payload"]["thirdapp_id"], ["app-1"])
        self.assertTrue(privilege_write["payload"]["privilege_list"][0]["b_check"])
        self.assertEqual(trial_write["path"], "/wwopen/api/customApp/price/SetStandardPriceInfoForCA")
        self.assertEqual(trial_write["payload"]["base_price_info"]["try_rule_info"]["try_time"], 60)
        self.assertEqual(trial_write["payload"]["base_price_info"]["try_rule_info"]["second_try_time"], 15)
        self.assertEqual(sso_write["payload"]["corpapp"]["sdk_auth"]["redirect_domain2"], "wxwork.jiandaoyun.com")
        self.assertEqual(order_add["path"], "/wwopen/developer/order/add")
        self.assertEqual(order.auditorderid, "order-1")

    def test_submit_online_order_classifies_not_ready_as_retryable(self):
        transport = FakeWecomTransport([RetryableWecomOrderError("当前状态暂不允许上线")])
        client = WecomAdminClient(transport)

        with self.assertRaises(RetryableWecomOrderError):
            client.submit_online_order(auditorderid="order-1")

        call = transport.calls[0]
        self.assertEqual(call["path"], "/wwopen/developer/order/set")
        self.assertEqual(call["payload"]["auditorder"]["status"], 5)
        self.assertEqual(call["payload"]["auditorder"]["auditorderid"], "order-1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing client tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_wecom_admin_client -v
```

Expected: fail with `ModuleNotFoundError: No module named 'rpa_platform.integrations.wecom_admin_client'`.

- [ ] **Step 3: Implement `wecom_admin_client.py`**

Create `rpa_platform/integrations/wecom_admin_client.py`:

```python
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol


class WecomAdminTransport(Protocol):
    def get_json(self, path: str, params: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        raise NotImplementedError

    def post_json(self, path: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        raise NotImplementedError


class WecomAdminError(RuntimeError):
    """Base error for WeCom developer admin API failures."""


class MissingWecomAppError(WecomAdminError):
    """Raised when no WeCom custom app can be resolved."""


class AmbiguousWecomAppError(WecomAdminError):
    """Raised when the WeCom custom app search is not unique."""


class RetryableWecomOrderError(WecomAdminError):
    """Raised when order/set should be retried after a delay."""


@dataclass(frozen=True)
class WecomCustomApp:
    app_id: str
    authcorp_name: str
    name: str
    logo: str
    description: str
    customized_app_status: int
    aes_app_id: str
    raw: Dict[str, Any]


@dataclass(frozen=True)
class WecomSaveAppRequest:
    suiteid: int
    app: WecomCustomApp
    homeurl: str
    callbackurl: str
    redirect_domain: str
    token: str
    encoding_aes_key: str


@dataclass(frozen=True)
class WecomOnlineOrder:
    auditorderid: str
    corpappid: str
    authcorp_name: str
    status: int


class WecomAdminClient:
    def __init__(self, transport: WecomAdminTransport):
        self.transport = transport

    def resolve_unique_custom_app(self, enterprise_name: str, suiteid: int, suite_name: str) -> WecomCustomApp:
        data = self.transport.get_json(
            "/wwopen/developer/customApp/tpl/app/list",
            {
                "lang": "zh_CN",
                "ajax": 1,
                "f": "json",
                "suiteid": suiteid,
                "scene": 1,
                "corp_name_keyword": enterprise_name,
                "offset": 0,
                "limit": 10,
                "random": 0,
            },
            {
                "x-wecom-developer-page": "/sass/customApp/tpl/info",
                "x-wecom-developer-perm": "50",
            },
        )
        rows = data.get("data", {}).get("corpapp", [])
        matches = [
            self._parse_custom_app(row)
            for row in rows
            if row.get("authcorp_name") == enterprise_name and row.get("name") == suite_name
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AmbiguousWecomAppError("enterprise custom app matched multiple rows")
        raise MissingWecomAppError("enterprise custom app was not found")

    def save_development_info(self, request: WecomSaveAppRequest) -> Dict[str, Any]:
        corpapp = dict(request.app.raw)
        corpapp.update(
            {
                "app_id": request.app.app_id,
                "suiteid": request.suiteid,
                "page_type": "CREATE",
                "name": request.app.name,
                "name_pinyin": "jiandaoyun",
                "logo": request.app.logo,
                "description": request.app.description,
                "homeurl": request.homeurl,
                "redirect_domain": request.redirect_domain,
                "domain_belong_to": 0,
                "jssdkdomain_list": {"domains": []},
                "white_ip_list": {"ip": []},
                "callbackurl": request.callbackurl,
                "token": request.token,
                "aeskey": request.encoding_aes_key,
                "enter_homeurl_in_wx": True,
                "is_homeurl_miniprogram": False,
                "miniprogram_enter_path": "",
                "miniprogramInfo": {},
            }
        )
        data = self.transport.post_json(
            "/wwopen/developer/customApp/tpl/corpApp",
            {"suiteid": str(request.suiteid), "corpapp": corpapp},
            {
                "x-wecom-developer-page": "/sass/customApp/app/create",
                "x-wecom-developer-perm": "50",
            },
        )
        return data.get("data", {}).get("corpapp", {})

    def set_target_privileges(self, suiteid: int, app_id: str) -> List[Dict[str, Any]]:
        read = self.transport.post_json(
            "/wwopen/api/customApp/privilege/getCustomizedAppPrivilege",
            {"thirdapp_id": [app_id], "suiteid": str(suiteid)},
            {
                "x-wecom-developer-page": "/sass/customApp/app/detail",
                "x-wecom-developer-perm": "50,51",
            },
        )
        privilege_list = read.get("data", {}).get("privilege_list", [])
        enabled_ids = {310000, 310001, 310002, 310100, 10006, 10010}
        patched = []
        for item in privilege_list:
            copied = dict(item)
            if int(copied.get("id", 0)) in enabled_ids:
                copied["b_check"] = True
            patched.append(copied)
        written = self.transport.post_json(
            "/wwopen/api/customApp/privilege/setCustomizedAppPrivilege",
            {"thirdapp_id": [app_id], "suiteid": str(suiteid), "privilege_list": patched},
            {
                "x-wecom-developer-page": "/sass/customApp/app/detail",
                "x-wecom-developer-perm": "50,51",
            },
        )
        return written.get("data", {}).get("privilege_list", patched)

    def set_trial_rule(self, app_id: str) -> Dict[str, Any]:
        self.transport.post_json(
            "/wwopen/api/customApp/price/GetStandardPriceInfoForCA",
            {"corpappid": app_id},
            {
                "x-wecom-developer-page": "/sass/customApp/app/detail",
                "x-wecom-developer-perm": "50,51",
            },
        )
        payload = {
            "corpappid": app_id,
            "base_price_info": {
                "try_rule_info": {
                    "try_rule_type": 2,
                    "try_time": 60,
                    "second_try_time": 15,
                    "prove_file": {"file_id": None, "file_name": None},
                }
            },
            "clear_base_price_info": False,
        }
        data = self.transport.post_json(
            "/wwopen/api/customApp/price/SetStandardPriceInfoForCA",
            payload,
            {
                "x-wecom-developer-page": "/sass/customApp/app/detail",
                "x-wecom-developer-perm": "50,51",
            },
        )
        return data.get("data", {})

    def set_sso_redirect_domain(self, suiteid: int, app_id: str, aes_app_id: str, redirect_domain: str) -> Dict[str, Any]:
        data = self.transport.post_json(
            "/wwopen/developer/customApp/tpl/corpApp",
            {
                "suiteid": str(suiteid),
                "corpapp": {
                    "app_id": app_id,
                    "sdk_auth": {
                        "aes_app_id": aes_app_id,
                        "redirect_domain2": redirect_domain,
                        "bundleid": "",
                        "signature_android": "",
                        "packagename": "",
                        "b_ios": False,
                        "b_android": False,
                    },
                },
            },
            {"x-wecom-developer-page": "/sass/customApp/app/detail/sso"},
        )
        return data.get("data", {}).get("corpapp", {})

    def create_online_order(self, suiteid: int, app_id: str) -> WecomOnlineOrder:
        data = self.transport.post_json(
            "/wwopen/developer/order/add",
            {"auditorder": {"suiteid": suiteid, "corpappid": app_id}, "skipNotice": False},
            {
                "x-wecom-developer-page": "/sass/customApp/deploy/list",
                "x-wecom-developer-perm": "51",
            },
        )
        return self._parse_order(data.get("data", {}).get("auditorder", {}))

    def submit_online_order(self, auditorderid: str) -> WecomOnlineOrder:
        try:
            data = self.transport.post_json(
                "/wwopen/developer/order/set",
                {"auditorder": {"status": 5, "auditorderid": auditorderid}},
                {
                    "x-wecom-developer-page": "/sass/customApp/deploy/detail",
                    "x-wecom-developer-perm": "51",
                },
            )
        except RetryableWecomOrderError:
            raise
        return self._parse_order(data.get("data", {}).get("auditorder", {}))

    @staticmethod
    def _parse_custom_app(row: Dict[str, Any]) -> WecomCustomApp:
        sdk_auth = row.get("sdk_auth") or {}
        return WecomCustomApp(
            app_id=str(row.get("app_id", "")),
            authcorp_name=str(row.get("authcorp_name", "")),
            name=str(row.get("name", "")),
            logo=str(row.get("logo", "")),
            description=str(row.get("description", "")),
            customized_app_status=int(row.get("customized_app_status") or 0),
            aes_app_id=str(sdk_auth.get("aes_app_id", "")),
            raw=dict(row),
        )

    @staticmethod
    def _parse_order(row: Dict[str, Any]) -> WecomOnlineOrder:
        return WecomOnlineOrder(
            auditorderid=str(row.get("auditorderid", "")),
            corpappid=str(row.get("corpappid", "")),
            authcorp_name=str(row.get("authcorp_name", "")),
            status=int(row.get("status") or 0),
        )
```

- [ ] **Step 4: Run client tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_wecom_admin_client -v
```

Expected: all tests in `WecomAdminClientTest` pass.

## Task 2: Full Bind Service Orchestration

**Files:**
- Create: `rpa_platform/services/__init__.py`
- Create: `rpa_platform/services/wecom_bind_service.py`
- Create: `tests/test_platform_wecom_bind_service.py`

- [ ] **Step 1: Write failing service-order tests**

Create `tests/test_platform_wecom_bind_service.py`:

```python
from datetime import datetime
import unittest

from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyAdminTransport
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient, WecomAdminTransport
from rpa_platform.services.wecom_bind_service import (
    FixedWecomSecretGenerator,
    JdyWecomBindInput,
    JdyWecomBindService,
)


class FakeJdyTransport(JdyAdminTransport):
    def __init__(self):
        self.calls = []

    def post_json(self, path, payload):
        self.calls.append({"path": path, "payload": payload})
        if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
            return {
                "has_more": False,
                "corp_deploy_list": [
                    {
                        "corp_id": "corp-secret",
                        "name": "上海测试客户",
                        "tenant_id": "old-user",
                        "suite_name": "简道云",
                        "integrate_suite_name": "简道云",
                        "suite_id": 1,
                        "suite_scenario": "main",
                    }
                ],
            }
        if path == "/api/fx_sa/wxwork/get_owner":
            return {"can_bind_corp_secret": True}
        if path == "/api/fx_sa/wxwork/install_corp_deploy":
            return {"tenant_id": "user-1", "owner_id": "user-1"}
        raise AssertionError("unexpected jdy path %s" % path)


class FakeWecomTransport(WecomAdminTransport):
    def __init__(self):
        self.calls = []

    def get_json(self, path, params, headers):
        self.calls.append({"method": "GET", "path": path, "params": params, "headers": headers})
        return {
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

    def post_json(self, path, payload, headers):
        self.calls.append({"method": "POST", "path": path, "payload": payload, "headers": headers})
        if path.endswith("/getCustomizedAppPrivilege"):
            return {"data": {"privilege_list": [{"id": 310000, "b_check": False}, {"id": 10006, "b_check": False}]}}
        if path.endswith("/setCustomizedAppPrivilege"):
            return {"data": {"privilege_list": payload["privilege_list"]}}
        if path.endswith("/GetStandardPriceInfoForCA"):
            return {"data": {"base_price_info": {}}}
        if path.endswith("/SetStandardPriceInfoForCA"):
            return {"data": {"is_already_set_try_info": True, "base_price_info": payload["base_price_info"]}}
        if path == "/wwopen/developer/customApp/tpl/corpApp" and payload["corpapp"].get("sdk_auth"):
            return {"data": {"corpapp": payload["corpapp"]}}
        if path == "/wwopen/developer/customApp/tpl/corpApp":
            return {"data": {"corpapp": payload["corpapp"]}}
        if path == "/wwopen/developer/order/add":
            return {"data": {"auditorder": {"auditorderid": "order-1", "corpappid": "app-1", "authcorp_name": "上海测试客户", "status": 1}}}
        if path == "/wwopen/developer/order/set":
            return {"data": {"auditorder": {"auditorderid": "order-1", "corpappid": "app-1", "authcorp_name": "上海测试客户", "status": 5}}}
        raise AssertionError("unexpected wecom path %s" % path)


class JdyWecomBindServiceTest(unittest.TestCase):
    def test_start_bind_runs_jdy_install_before_wecom_save_and_returns_delay(self):
        jdy_transport = FakeJdyTransport()
        wecom_transport = FakeWecomTransport()
        service = JdyWecomBindService(
            jdy_client=JdyAdminClient(jdy_transport),
            wecom_client=WecomAdminClient(wecom_transport),
            secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
        )

        result = service.start_bind(
            JdyWecomBindInput(
                enterprise_name="上海测试客户",
                plain_corp_id="ww001",
                requested_user_id="user-1",
                suite_id=1,
                suite_scenario="main",
                wecom_suiteid=1009479,
                suite_name="简道云",
            ),
            now=datetime(2026, 6, 16, 10, 0, 0),
        )

        all_paths = [call["path"] for call in jdy_transport.calls] + [call["path"] for call in wecom_transport.calls]
        install_index = all_paths.index("/api/fx_sa/wxwork/install_corp_deploy")
        save_index = all_paths.index("/wwopen/developer/customApp/tpl/corpApp")
        self.assertLess(install_index, save_index)
        self.assertEqual(result.status, "waiting_wecom_online_delay")
        self.assertEqual(result.next_check_at, datetime(2026, 6, 16, 10, 5, 0))
        self.assertEqual(result.context["jdy"]["original_tenant_id"], "old-user")
        self.assertEqual(result.context["jdy"]["install_owner_id"], "user-1")
        self.assertEqual(result.context["wecom"]["app_id"], "app-1")
        self.assertEqual(result.context["wecom"]["auditorderid"], "order-1")
        self.assertEqual(result.context["wecom"]["token"], "token-secret")
        self.assertEqual(result.context["wecom"]["encoding_aes_key"], "aes-secret")

    def test_submit_online_uses_saved_audit_order(self):
        wecom_transport = FakeWecomTransport()
        service = JdyWecomBindService(
            jdy_client=JdyAdminClient(FakeJdyTransport()),
            wecom_client=WecomAdminClient(wecom_transport),
            secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
        )

        result = service.submit_online_order({"wecom": {"auditorderid": "order-1"}})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.context["wecom"]["auditorder_status"], 5)
        self.assertEqual(wecom_transport.calls[-1]["path"], "/wwopen/developer/order/set")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing service tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_wecom_bind_service -v
```

Expected: fail with `ModuleNotFoundError: No module named 'rpa_platform.services'`.

- [ ] **Step 3: Implement the service package**

Create `rpa_platform/services/__init__.py`:

```python
"""Service orchestration modules for the RPA platform."""
```

Create `rpa_platform/services/wecom_bind_service.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
import secrets
import string
from typing import Any, Dict, Protocol

from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyInstallRequest, OwnerCannotBindError
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient, WecomSaveAppRequest


class WecomSecretGenerator(Protocol):
    def generate(self) -> Dict[str, str]:
        raise NotImplementedError


class RandomWecomSecretGenerator:
    def generate(self) -> Dict[str, str]:
        alphabet = string.ascii_letters + string.digits
        token = "".join(secrets.choice(alphabet) for _ in range(32))
        aes_key = "".join(secrets.choice(alphabet) for _ in range(43))
        return {"token": token, "encoding_aes_key": aes_key}


class FixedWecomSecretGenerator:
    def __init__(self, token: str, encoding_aes_key: str):
        self.token = token
        self.encoding_aes_key = encoding_aes_key

    def generate(self) -> Dict[str, str]:
        return {"token": self.token, "encoding_aes_key": self.encoding_aes_key}


@dataclass(frozen=True)
class JdyWecomBindInput:
    enterprise_name: str
    plain_corp_id: str
    requested_user_id: str
    suite_id: int
    suite_scenario: str
    wecom_suiteid: int
    suite_name: str


@dataclass(frozen=True)
class JdyWecomBindResult:
    status: str
    context: Dict[str, Any]
    next_check_at: datetime = None


class JdyWecomBindService:
    def __init__(
        self,
        jdy_client: JdyAdminClient,
        wecom_client: WecomAdminClient,
        secret_generator: WecomSecretGenerator,
    ):
        self.jdy_client = jdy_client
        self.wecom_client = wecom_client
        self.secret_generator = secret_generator

    def start_bind(self, request: JdyWecomBindInput, now: datetime) -> JdyWecomBindResult:
        corp = self.jdy_client.resolve_unique_corp(request.plain_corp_id, request.enterprise_name)
        app = self.wecom_client.resolve_unique_custom_app(
            enterprise_name=request.enterprise_name,
            suiteid=request.wecom_suiteid,
            suite_name=request.suite_name,
        )
        secrets_payload = self.secret_generator.generate()
        wecom_urls = {
            "homeurl": "https://wxwork.jiandaoyun.com/wxwork/%s/dashboard" % corp.corp_id,
            "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/%s/service" % corp.corp_id,
            "redirect_domain": "wxwork.jiandaoyun.com",
        }
        owner = self.jdy_client.check_wework_owner(
            request.requested_user_id,
            suite_id=request.suite_id,
            suite_scenario=request.suite_scenario,
        )
        if not owner.can_bind_corp_secret:
            raise OwnerCannotBindError("User_ID cannot bind corp secret")
        install = self.jdy_client.install_corp_deploy(
            JdyInstallRequest(
                corp_id=corp.corp_id,
                corp_name=corp.name,
                tenant_id=request.requested_user_id,
                token=secrets_payload["token"],
                encoding_aes_key=secrets_payload["encoding_aes_key"],
                suite_id=request.suite_id,
                suite_scenario=request.suite_scenario,
            )
        )
        self.wecom_client.save_development_info(
            WecomSaveAppRequest(
                suiteid=request.wecom_suiteid,
                app=app,
                homeurl=wecom_urls["homeurl"],
                callbackurl=wecom_urls["callbackurl"],
                redirect_domain=wecom_urls["redirect_domain"],
                token=secrets_payload["token"],
                encoding_aes_key=secrets_payload["encoding_aes_key"],
            )
        )
        self.wecom_client.set_target_privileges(suiteid=request.wecom_suiteid, app_id=app.app_id)
        self.wecom_client.set_trial_rule(app_id=app.app_id)
        self.wecom_client.set_sso_redirect_domain(
            suiteid=request.wecom_suiteid,
            app_id=app.app_id,
            aes_app_id=app.aes_app_id,
            redirect_domain=wecom_urls["redirect_domain"],
        )
        order = self.wecom_client.create_online_order(suiteid=request.wecom_suiteid, app_id=app.app_id)
        context = {
            "jdy": {
                "corp_secret_id": corp.corp_id,
                "corp_name": corp.name,
                "original_tenant_id": corp.tenant_id,
                "requested_user_id": request.requested_user_id,
                "install_tenant_id": install.tenant_id,
                "install_owner_id": install.owner_id,
                "bound_user_id": install.owner_id or install.tenant_id,
                "suite_id": corp.suite_id,
                "suite_scenario": corp.suite_scenario,
                "suite_name": corp.suite_name,
                "integrate_suite_name": corp.integrate_suite_name,
            },
            "wecom": {
                "suiteid": request.wecom_suiteid,
                "suite_name": request.suite_name,
                "app_id": app.app_id,
                "aes_app_id": app.aes_app_id,
                "homeurl": wecom_urls["homeurl"],
                "callbackurl": wecom_urls["callbackurl"],
                "redirect_domain": wecom_urls["redirect_domain"],
                "token": secrets_payload["token"],
                "encoding_aes_key": secrets_payload["encoding_aes_key"],
                "auditorderid": order.auditorderid,
                "auditorder_status": order.status,
                "order_created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
        return JdyWecomBindResult(
            status="waiting_wecom_online_delay",
            context=context,
            next_check_at=now + timedelta(minutes=5),
        )

    def submit_online_order(self, context: Dict[str, Any]) -> JdyWecomBindResult:
        order = self.wecom_client.submit_online_order(context["wecom"]["auditorderid"])
        return JdyWecomBindResult(
            status="success",
            context={"wecom": {"auditorder_status": order.status}},
        )
```

- [ ] **Step 4: Run service tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_wecom_bind_service -v
```

Expected: all tests in `JdyWecomBindServiceTest` pass.

## Task 3: State Machine and Delayed Claiming

**Files:**
- Modify: `rpa_platform/domain/state_machine.py`
- Modify: `rpa_platform/storage/sqlite_store.py`
- Modify: `tests/test_platform_state_machine.py`
- Modify: `tests/test_platform_worker_scheduler.py`

- [ ] **Step 1: Add failing state-machine and scheduler tests**

Append to `tests/test_platform_state_machine.py`:

```python
    def test_waiting_wecom_online_delay_transitions(self):
        ensure_task_transition(TaskStatus.RUNNING, TaskStatus.WAITING_WECOM_ONLINE_DELAY)
        ensure_task_transition(TaskStatus.WAITING_WECOM_ONLINE_DELAY, TaskStatus.CHECKING_LOGIN)
        ensure_task_transition(TaskStatus.WAITING_WECOM_ONLINE_DELAY, TaskStatus.RUNNING)
        ensure_task_transition(TaskStatus.WAITING_WECOM_ONLINE_DELAY, TaskStatus.SUCCESS)
```

Append to `tests/test_platform_worker_scheduler.py`:

```python
    def test_claims_due_wecom_online_delay_task_and_increments_attempts(self):
        task_id = self._create_task("ww001", "u001")
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at="2026-06-16 10:05:00",
            check_attempts=1,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-16 10:06:00"))

        self.assertEqual(claimed["id"], task_id)
        task = self.store.get_task(task_id)
        self.assertEqual(task["status"], TaskStatus.CHECKING_LOGIN.value)
        self.assertEqual(task["check_attempts"], 2)

    def test_skips_wecom_online_delay_task_before_next_check_time(self):
        task_id = self._create_task("ww001", "u001")
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at="2026-06-16 10:05:00",
            check_attempts=1,
            assigned_robot_id=None,
        )

        claimed = self.scheduler.claim_next_task(self.robot_id, now=self._dt("2026-06-16 10:04:00"))

        self.assertIsNone(claimed)
        self.assertEqual(self.store.get_task(task_id)["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
```

- [ ] **Step 2: Run failing scheduler/state tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_state_machine tests.test_platform_worker_scheduler -v
```

Expected: fail because `TaskStatus.WAITING_WECOM_ONLINE_DELAY` is not defined.

- [ ] **Step 3: Add `WAITING_WECOM_ONLINE_DELAY`**

Modify `rpa_platform/domain/state_machine.py`:

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    CHECKING_LOGIN = "checking_login"
    RUNNING = "running"
    WAITING_LOGIN = "waiting_login"
    WAITING_MANUAL_SELECTION = "waiting_manual_selection"
    WAITING_MANUAL_INTERVENTION = "waiting_manual_intervention"
    WAITING_WECOM_REVIEW = "waiting_wecom_review"
    WAITING_WECOM_ONLINE_DELAY = "waiting_wecom_online_delay"
    READY_TO_ONLINE = "ready_to_online"
    WAITING_TEST_CONFIRMATION = "waiting_test_confirmation"
    JDY_CALLBACK_FAILED = "jdy_callback_failed"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

Add the transition target to the `TaskStatus.RUNNING` set:

```python
        TaskStatus.WAITING_WECOM_ONLINE_DELAY,
```

Add a new transition set:

```python
    TaskStatus.WAITING_WECOM_ONLINE_DELAY: {
        TaskStatus.CHECKING_LOGIN,
        TaskStatus.RUNNING,
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.WAITING_MANUAL_INTERVENTION,
        TaskStatus.CANCELLED,
    },
```

- [ ] **Step 4: Add delayed claim support in SQLiteStore**

In `rpa_platform/storage/sqlite_store.py`, find the runnable-task query used by `claim_next_runnable_task`. Extend the delayed status list so `waiting_wecom_online_delay` follows the same `next_check_at <= now` rule as `waiting_wecom_review`.

Use this status tuple in the query-building code:

```python
delayed_statuses = (
    TaskStatus.WAITING_WECOM_REVIEW.value,
    TaskStatus.WAITING_WECOM_ONLINE_DELAY.value,
)
```

The claim behavior must set delayed tasks back to `checking_login`, assign the robot, mark the robot busy, and increment `check_attempts`, matching the existing review-wait path.

- [ ] **Step 5: Run state and scheduler tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_state_machine tests.test_platform_worker_scheduler -v
```

Expected: all tests pass.

## Task 4: Scheduler-Compatible Bind Runner

**Files:**
- Create: `rpa_platform/worker/wecom_bind_runner.py`
- Create: `tests/test_platform_wecom_bind_runner.py`

- [ ] **Step 1: Write failing runner tests**

Create `tests/test_platform_wecom_bind_runner.py`:

```python
from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient, RetryableWecomOrderError
from rpa_platform.services.wecom_bind_service import FixedWecomSecretGenerator, JdyWecomBindService
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.wecom_bind_runner import WecomBindServiceRunner
from tests.test_platform_wecom_bind_service import FakeJdyTransport, FakeWecomTransport


class RetryableOrderWecomTransport(FakeWecomTransport):
    def post_json(self, path, payload, headers):
        if path == "/wwopen/developer/order/set":
            self.calls.append({"method": "POST", "path": path, "payload": payload, "headers": headers})
            raise RetryableWecomOrderError("当前状态暂不允许上线")
        return super().post_json(path, payload, headers)


class WecomBindServiceRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(self.team_id, "企微绑定接口服务", "")
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[{"key": "jdy_wecom_bind_service", "name": "企微绑定接口服务", "action": "jdy_wecom_bind_service"}],
            created_by="test",
        )
        self.store.publish_flow_version(self.flow_id, version_id)
        self.task_id = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="上海测试客户",
            corp_id="ww001",
            source_user_id="user-1",
            idempotency_key="wecom_bind:ww001:user-1",
            payload={"user_id": "user-1", "企业客户名称": "上海测试客户", "企业微信明文 CorpID": "ww001"},
        ).task_id
        self.robot_id = self.store.register_robot("windows-rpa-01", "WIN-RPA-01", "C:/rpa/chrome-profile")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _runner(self, wecom_transport=None):
        service = JdyWecomBindService(
            jdy_client=JdyAdminClient(FakeJdyTransport()),
            wecom_client=WecomAdminClient(wecom_transport or FakeWecomTransport()),
            secret_generator=FixedWecomSecretGenerator("token-secret", "aes-secret"),
        )
        return WecomBindServiceRunner(self.store, service)

    def test_start_bind_moves_task_to_online_delay_and_releases_robot(self):
        result = self._runner().run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 0, 0),
        )

        task = self.store.get_task(self.task_id)
        context = self.store.get_task_context(self.task_id)
        steps = self.store.list_task_steps(self.task_id)
        self.assertEqual(result["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(task["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(task["next_check_at"], "2026-06-16 10:05:00")
        self.assertEqual(task["assigned_robot_id"], None)
        self.assertEqual(context["wecom"]["auditorderid"], "order-1")
        self.assertEqual(steps[-1]["step_key"], "jdy_wecom_bind_service")
        self.assertEqual(self.store.get_robot(self.robot_id)["status"], "idle")

    def test_online_delay_resume_submits_order_and_marks_success(self):
        self._runner().run_claimed_task(self.task_id, self.robot_id, now=datetime(2026, 6, 16, 10, 0, 0))
        self.store.set_task_status(self.task_id, TaskStatus.WAITING_WECOM_ONLINE_DELAY, assigned_robot_id=None)

        result = self._runner().run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 5, 1),
        )

        task = self.store.get_task(self.task_id)
        context = self.store.get_task_context(self.task_id)
        self.assertEqual(result["status"], TaskStatus.SUCCESS.value)
        self.assertEqual(task["status"], TaskStatus.SUCCESS.value)
        self.assertEqual(context["wecom"]["auditorder_status"], 5)

    def test_retryable_online_submit_keeps_online_delay_for_two_minutes(self):
        self._runner().run_claimed_task(self.task_id, self.robot_id, now=datetime(2026, 6, 16, 10, 0, 0))
        self.store.set_task_status(self.task_id, TaskStatus.WAITING_WECOM_ONLINE_DELAY, assigned_robot_id=None)

        result = self._runner(RetryableOrderWecomTransport()).run_claimed_task(
            self.task_id,
            self.robot_id,
            now=datetime(2026, 6, 16, 10, 5, 1),
        )

        task = self.store.get_task(self.task_id)
        self.assertEqual(result["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(task["next_check_at"], "2026-06-16 10:07:01")
        self.assertEqual(task["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing runner tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_wecom_bind_runner -v
```

Expected: fail with `ModuleNotFoundError: No module named 'rpa_platform.worker.wecom_bind_runner'`.

- [ ] **Step 3: Implement `WecomBindServiceRunner`**

Create `rpa_platform/worker/wecom_bind_runner.py`:

```python
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.integrations.wecom_admin_client import RetryableWecomOrderError
from rpa_platform.services.wecom_bind_service import JdyWecomBindInput, JdyWecomBindService
from rpa_platform.storage.sqlite_store import SQLiteStore


class WecomBindServiceRunner:
    def __init__(self, store: SQLiteStore, service: JdyWecomBindService):
        self.store = store
        self.service = service

    def run_claimed_task(self, task_id: str, robot_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        current_time = now or datetime.now()
        task = self.store.get_task(task_id)
        current_status = TaskStatus(task["status"])
        if current_status == TaskStatus.WAITING_WECOM_ONLINE_DELAY:
            return self._submit_online(task_id, robot_id, current_time)
        self.store.set_task_status(task_id, TaskStatus.RUNNING, assigned_robot_id=robot_id)
        task = self.store.get_task(task_id)
        self.store.set_task_current_step(task_id, "jdy_wecom_bind_service")
        result = self.service.start_bind(
            JdyWecomBindInput(
                enterprise_name=task["enterprise_name"],
                plain_corp_id=task["corp_id"],
                requested_user_id=task["source_user_id"],
                suite_id=1,
                suite_scenario="main",
                wecom_suiteid=1009479,
                suite_name="简道云",
            ),
            now=current_time,
        )
        self.store.merge_task_context(task_id, result.context)
        self.store.append_task_step(
            task_id,
            "jdy_wecom_bind_service",
            "企微绑定接口服务",
            "success",
            output_data=result.context,
        )
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at=result.next_check_at,
            assigned_robot_id=None,
        )
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.WAITING_WECOM_ONLINE_DELAY.value}

    def _submit_online(self, task_id: str, robot_id: str, now: datetime) -> Dict[str, Any]:
        self.store.set_task_current_step(task_id, "wecom_submit_online_order")
        try:
            result = self.service.submit_online_order(self.store.get_task_context(task_id))
        except RetryableWecomOrderError as exc:
            next_check_at = now + timedelta(minutes=2)
            self.store.append_task_step(
                task_id,
                "wecom_submit_online_order",
                "企微提交上线单",
                TaskStatus.WAITING_WECOM_ONLINE_DELAY.value,
                output_data={"error_type": "retryable_wecom_order", "error_detail": str(exc)},
            )
            self.store.set_task_status(
                task_id,
                TaskStatus.WAITING_WECOM_ONLINE_DELAY,
                next_check_at=next_check_at,
                assigned_robot_id=None,
            )
            self.store.update_robot_status(robot_id, "idle")
            return {"task_id": task_id, "status": TaskStatus.WAITING_WECOM_ONLINE_DELAY.value}
        self.store.merge_task_context(task_id, result.context)
        self.store.append_task_step(
            task_id,
            "wecom_submit_online_order",
            "企微提交上线单",
            "success",
            output_data=result.context,
        )
        self.store.set_task_status(task_id, TaskStatus.SUCCESS, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.SUCCESS.value}
```

- [ ] **Step 4: Run runner tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_wecom_bind_runner -v
```

Expected: all tests in `WecomBindServiceRunnerTest` pass.

## Task 5: Flow Constant and Dry-Run Mode

**Files:**
- Modify: `rpa_platform/domain/default_flows.py`
- Modify: `scripts/dev/run_platform_dryrun.py`
- Modify: `tests/test_platform_flow_steps.py`
- Modify: `tests/test_platform_dryrun_smoke.py`

- [ ] **Step 1: Write failing flow and dry-run tests**

Append to `tests/test_platform_flow_steps.py`:

```python
    def test_default_wecom_bind_service_flow_steps_validate_with_allowlist(self):
        from rpa_platform.domain.default_flows import WECOM_BIND_SERVICE_FLOW_STEPS

        keys = [step["key"] for step in WECOM_BIND_SERVICE_FLOW_STEPS]
        actions = [step["action"] for step in WECOM_BIND_SERVICE_FLOW_STEPS]
        self.assertEqual(keys, ["jdy_wecom_bind_service", "wecom_wait_online_delay", "wecom_submit_online_order"])
        self.assertEqual(actions, ["jdy_wecom_bind_service", "wecom_wait_online_delay", "wecom_submit_online_order"])
```

Append to `tests/test_platform_dryrun_smoke.py`:

```python
    def test_service_dryrun_reaches_online_delay_and_redacts_secrets(self):
        from scripts.dev.run_platform_dryrun import run_wecom_bind_service_dryrun

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_wecom_bind_service_dryrun(db_path=str(Path(tmpdir) / "service.db"))

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["runner_result"]["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(result["task_detail"]["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertEqual(result["task_detail"]["current_step_key"], "jdy_wecom_bind_service")
        self.assertIn("order-1", serialized)
        self.assertIn("***", serialized)
        self.assertNotIn("token-secret", serialized)
        self.assertNotIn("aes-secret", serialized)
```

Append to `tests/test_platform_dryrun_smoke.py`:

```python
    def test_service_dryrun_main_mode_prints_redacted_task_detail(self):
        from scripts.dev.run_platform_dryrun import main

        with tempfile.TemporaryDirectory() as tmpdir:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--mode", "wecom-bind-service", "--db-path", str(Path(tmpdir) / "service.db")])

        printed = output.getvalue()
        data = json.loads(printed)
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["task_detail"]["status"], TaskStatus.WAITING_WECOM_ONLINE_DELAY.value)
        self.assertNotIn("token-secret", printed)
        self.assertNotIn("aes-secret", printed)
```

- [ ] **Step 2: Run failing flow and dry-run tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_flow_steps tests.test_platform_dryrun_smoke -v
```

Expected: fail because `WECOM_BIND_SERVICE_FLOW_STEPS` and dry-run mode do not exist.

- [ ] **Step 3: Add service flow constant**

Append to `rpa_platform/domain/default_flows.py`:

```python
WECOM_BIND_SERVICE_FLOW_STEPS = [
    {
        "key": "jdy_wecom_bind_service",
        "name": "企微绑定接口服务",
        "action": "jdy_wecom_bind_service",
        "target": "service",
    },
    {
        "key": "wecom_wait_online_delay",
        "name": "等待企微上线单可提交",
        "action": "wecom_wait_online_delay",
        "target": "service",
    },
    {
        "key": "wecom_submit_online_order",
        "name": "企微提交上线单",
        "action": "wecom_submit_online_order",
        "target": "service",
    },
]
```

If `rpa_platform/domain/flow_steps.py` enforces an action allowlist, add these actions to the allowlist:

```python
SERVICE_ACTIONS = {
    "jdy_wecom_bind_service",
    "wecom_wait_online_delay",
    "wecom_submit_online_order",
}
```

- [ ] **Step 4: Add dry-run service mode**

Modify `scripts/dev/run_platform_dryrun.py` so argument parsing accepts:

```text
--mode hybrid
--mode wecom-bind-service
```

Keep the existing default behavior unchanged. Add a `run_wecom_bind_service_dryrun(db_path: str) -> dict` function that:

```python
from datetime import datetime
import json

from rpa_platform.domain.default_flows import WECOM_BIND_SERVICE_FLOW_STEPS
from rpa_platform.domain.redaction import redact_context
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient
from rpa_platform.services.wecom_bind_service import FixedWecomSecretGenerator, JdyWecomBindService
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.robot_registry import RobotRegistry
from rpa_platform.worker.scheduler import TaskScheduler
from rpa_platform.worker.wecom_bind_runner import WecomBindServiceRunner
```

Use fake transports with the same response shapes as `tests.test_platform_wecom_bind_service.FakeJdyTransport` and `FakeWecomTransport`. Do not import test modules from the script; define small local fake classes inside the script.

The `run_wecom_bind_service_dryrun(db_path: str) -> dict` function should:

```python
store = SQLiteStore(db_path)
store.init_schema()
team_id = store.create_team("交付团队")
flow_id = store.create_flow_template(team_id, "企微绑定接口服务", "")
version_id = store.create_flow_version(flow_id, WECOM_BIND_SERVICE_FLOW_STEPS, created_by="dryrun")
store.publish_flow_version(flow_id, version_id)
robot_id = RobotRegistry(store).register_robot("mac-fake-robot", "MAC-DRYRUN", "fake-profile")
task_id = store.create_task_from_published_flow(
    team_id=team_id,
    flow_template_id=flow_id,
    enterprise_name="上海测试客户",
    corp_id="ww001",
    source_user_id="user-1",
    idempotency_key="wecom_bind_service:ww001:user-1",
    payload={"user_id": "user-1", "企业客户名称": "上海测试客户", "企业微信明文 CorpID": "ww001"},
).task_id
service = JdyWecomBindService(
    jdy_client=JdyAdminClient(FakeJdyTransport()),
    wecom_client=WecomAdminClient(FakeWecomTransport()),
    secret_generator=FixedWecomSecretGenerator("token-secret", "aes-secret"),
)
runner = WecomBindServiceRunner(store, service)
result = TaskScheduler(store).run_once(robot_id, runner, now=datetime(2026, 6, 16, 10, 0, 0))
detail = store.get_task_detail(task_id)
detail["runtime_context"] = redact_context(detail["runtime_context"])
return {
    "runner_result": result["runner_result"],
    "scheduler_result": result,
    "task_id": task_id,
    "task_detail": detail,
}
```

The `main(argv)` function should print this dictionary as JSON when `--mode wecom-bind-service` is selected and return `0`.

- [ ] **Step 5: Run flow and dry-run tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_flow_steps tests.test_platform_dryrun_smoke -v
```

Expected: all tests pass.

## Task 6: Full Verification and Documentation Check

**Files:**
- Modify: `docs/jdy_wework_bind_full_flow_runbook.md` only if implementation reveals a mismatch in the runbook.
- Do not modify: `RPA.py`

- [ ] **Step 1: Run full test suite**

Run:

```bash
conda run -n RPA_GROUP python -m unittest discover -s tests -v
```

Expected:

```text
Ran 80+ tests
OK
```

The Conda `_distutils_hack` warning may still appear. Treat it as environment noise if the command exits 0.

- [ ] **Step 2: Run service dry-run manually**

Run:

```bash
conda run -n RPA_GROUP python scripts/dev/run_platform_dryrun.py --mode wecom-bind-service --db-path .local/platform-dryrun.db
```

Expected:

```text
"status": "waiting_wecom_online_delay"
"current_step_key": "jdy_wecom_bind_service"
"auditorderid": "order-1"
"token": "***"
"encoding_aes_key": "***"
```

- [ ] **Step 3: Confirm protected files and generated files**

Run:

```bash
git status -sb
```

Expected:

```text
RPA.py is not modified
.local/platform-dryrun.db is not staged
docs/jdy_wework_bind_full_flow_runbook.md is unchanged unless a verified runbook correction was made
```

- [ ] **Step 4: Review for secret leakage**

Run:

```bash
rg -n "token-secret|aes-secret|wwrtx|Cookie|curl '" rpa_platform tests scripts docs/superpowers/plans/2026-06-16-wecom-bind-service-client.md
```

Expected:

```text
Only fake test literals token-secret/aes-secret appear in tests, dry-run fakes, or this plan.
No real Cookie, cURL, sid, vst, monitor, kitsecret, Token, or EncodingAESKey appears.
```

- [ ] **Step 5: Commit in small Chinese commits**

Use focused commits:

```bash
git add rpa_platform/integrations/wecom_admin_client.py tests/test_platform_wecom_admin_client.py
git commit -m "新增企微后台接口客户端"

git add rpa_platform/services tests/test_platform_wecom_bind_service.py
git commit -m "封装企微绑定接口服务"

git add rpa_platform/domain/state_machine.py rpa_platform/storage/sqlite_store.py rpa_platform/worker/wecom_bind_runner.py tests/test_platform_state_machine.py tests/test_platform_worker_scheduler.py tests/test_platform_wecom_bind_runner.py
git commit -m "接入企微绑定延迟上线状态"

git add rpa_platform/domain/default_flows.py scripts/dev/run_platform_dryrun.py tests/test_platform_flow_steps.py tests/test_platform_dryrun_smoke.py
git commit -m "补充企微绑定服务 dry-run"
```

Do not stage `.local/platform-dryrun.db`, `.env`, `config.py`, logs, screenshots, zip files, Cookie/cURL files, or unrelated pre-existing changes.

## Self-Review

- Spec coverage:
  - Correct sequence is covered by Task 2 service-order test.
  - Fake transport unit tests are covered by Tasks 1 and 2.
  - Dry-run is covered by Task 5.
  - Windows Cookie/Profile is intentionally not implemented; transports are injected and real login-state validation is left for the Windows phase.
  - Windows 企业微信客户端 RPA is explicitly out of scope.
  - `RPA.py` is explicitly protected.
- Placeholder scan:
  - No unresolved placeholder markers are present.
  - No unfinished work markers are present.
  - No step says only "add tests" without concrete test code.
- Type consistency:
  - `JdyWecomBindInput`, `JdyWecomBindResult`, `JdyWecomBindService`, `WecomAdminClient`, `WecomBindServiceRunner`, and `WAITING_WECOM_ONLINE_DELAY` are used consistently across tasks.
  - The status string `waiting_wecom_online_delay` matches `TaskStatus.WAITING_WECOM_ONLINE_DELAY.value`.
