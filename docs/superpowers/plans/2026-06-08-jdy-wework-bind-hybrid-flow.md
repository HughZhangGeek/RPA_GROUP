# 简道云企微绑定混合流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable hybrid flow where Jiandaoyun admin binding uses internal APIs and WeCom developer-console work runs through local/self-hosted `browser-use` browser automation.

**Architecture:** Keep old `RPA.py` untouched. Add a small integration client for Jiandaoyun admin APIs, a persistent task runtime context in the new SQLite platform, and a runner action layer that combines deterministic Jiandaoyun API steps with WeCom browser-use adapter steps. WeCom submit APIs stay documentation-only for now; the first implementation drives WeCom pages through a local browser-use adapter and uses API calls only on `dc.jdydevelop.com`.

**Tech Stack:** FastAPI existing app shell, SQLiteStore, unittest, injected HTTP/browser-use fakes for tests. The control plane may remain on the current Python environment; the browser worker can use Python 3.11+ if required by `browser-use`.

---

## Current Boundaries

- Repository: `/Users/hugh/jdycsm_project/RPA_GROUP`
- Branch: `feature/rpa-platform-foundation`
- Do not modify `RPA.py`.
- Do not deploy or restart services.
- Do not commit `.env`, `config.py`, logs, databases, screenshots, or zip packages.
- Commit messages, PR title, and PR body must be Chinese unless explicitly asked otherwise.
- Research doc to keep aligned: `docs/jdy_wework_bind_api_research.md`

## File Structure

- Create `rpa_platform/integrations/__init__.py`
  - Package marker for external/internal service clients.
- Create `rpa_platform/integrations/jdy_admin_client.py`
  - Typed Jiandaoyun admin client with injected transport, response normalization, unique-record resolution, and safe error classes.
- Create `rpa_platform/worker/wecom_rpa.py`
  - Interface, fake implementation, and browser-use backed adapter boundary for WeCom browser automation. Browser Use Cloud is out of scope for the first implementation.
- Create `rpa_platform/worker/hybrid_runner.py`
  - Step runner that reads the published flow snapshot, uses runtime context, executes Jiandaoyun API actions and WeCom browser-use adapter actions, and updates task status.
- Modify `rpa_platform/storage/sqlite_store.py`
  - Add `runtime_context_json` to tasks and helpers to read/merge context.
  - Add helper for setting `current_step_key`.
- Modify `rpa_platform/domain/flow_steps.py`
  - Add action allowlist for the hybrid flow, while preserving existing generic validation behavior.
- Test files:
  - Create `tests/test_platform_jdy_admin_client.py`
  - Create `tests/test_platform_task_context.py`
  - Create `tests/test_platform_hybrid_runner.py`
  - Modify `tests/test_platform_flow_steps.py`

## Flow Contract

First runnable flow version should use these step keys and actions:

```python
HYBRID_FLOW_STEPS = [
    {"key": "jdy_resolve_corp", "name": "简道云查找绑定企业", "action": "jdy_resolve_corp"},
    {"key": "derive_wecom_urls", "name": "生成企微配置 URL", "action": "derive_wecom_urls"},
    {"key": "wecom_configure_app", "name": "企微页面配置代开发应用", "action": "wecom_configure_app"},
    {"key": "jdy_check_owner", "name": "简道云校验绑定 User_ID", "action": "jdy_check_owner"},
    {"key": "jdy_install_bind", "name": "简道云提交企业微信绑定", "action": "jdy_install_bind"},
    {"key": "wecom_submit_review", "name": "企微提交上线进入审核", "action": "wecom_submit_review"},
    {"key": "wecom_wait_review", "name": "等待企微审核通过", "action": "wecom_wait_review"},
    {"key": "wecom_submit_online", "name": "企微待上线后提交上线", "action": "wecom_submit_online"},
]
```

Runtime context keys:

```python
{
    "jdy": {
        "corp_secret_id": "wpx...masked in logs only",
        "corp_name": "安徽云速付",
        "tenant_id": "source user_id or existing row tenant_id",
        "suite_id": 1,
        "suite_scenario": "main",
        "suite_name": "简道云",
        "integrate_suite_name": "简道云"
    },
    "wecom": {
        "homeurl": "https://wxwork.jiandaoyun.com/wxwork/{corp_secret_id}/dashboard",
        "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/{corp_secret_id}/service",
        "redirect_domain": "wxwork.jiandaoyun.com",
        "token": "secret, never log raw",
        "encoding_aes_key": "secret, never log raw",
        "review_status": "审核中|待上线|已上线"
    }
}
```

## Task 1: Jiandaoyun Admin Client

**Files:**
- Create: `rpa_platform/integrations/__init__.py`
- Create: `rpa_platform/integrations/jdy_admin_client.py`
- Create: `tests/test_platform_jdy_admin_client.py`

- [ ] **Step 1: Create failing tests for search, unique resolution, owner check, install bind**

Write `tests/test_platform_jdy_admin_client.py`:

```python
import unittest

from rpa_platform.integrations.jdy_admin_client import (
    AmbiguousCorpDeployError,
    JdyAdminClient,
    JdyAdminTransport,
    JdyCorpDeploy,
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
        transport = FakeTransport([
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
        ])
        client = JdyAdminClient(transport)

        result = client.search_corp_deploy_list("安徽云速付")

        self.assertFalse(result.has_more)
        self.assertEqual(result.rows[0].corp_id, "corp-secret")
        self.assertEqual(result.rows[0].suite_id, 1)
        self.assertEqual(transport.calls[0]["path"], "/api/fx_sa/wxwork/get_corp_deploy_list")
        self.assertEqual(transport.calls[0]["payload"]["filter"], "安徽云速付")

    def test_resolve_unique_prefers_plain_corp_id_then_name(self):
        transport = FakeTransport([
            {"has_more": False, "corp_deploy_list": []},
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
        ])
        client = JdyAdminClient(transport)

        row = client.resolve_unique_corp(plain_corp_id="ww-demo", enterprise_name="安徽云速付")

        self.assertEqual(row.name, "安徽云速付")
        self.assertEqual([call["payload"]["filter"] for call in transport.calls], ["ww-demo", "安徽云速付"])

    def test_resolve_unique_rejects_no_match_and_multiple_matches(self):
        with self.assertRaises(MissingCorpDeployError):
            JdyAdminClient(FakeTransport([
                {"has_more": False, "corp_deploy_list": []},
                {"has_more": False, "corp_deploy_list": []},
            ])).resolve_unique_corp("ww-demo", "安徽云速付")

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
        transport = FakeTransport([
            {"can_bind_corp_secret": True},
            {"tenant_id": "user-1", "owner_id": "user-1"},
        ])
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
        self.assertEqual(install.owner_id, "user-1")
        self.assertEqual(transport.calls[0]["path"], "/api/fx_sa/wxwork/get_owner")
        self.assertEqual(transport.calls[1]["path"], "/api/fx_sa/wxwork/install_corp_deploy")
        self.assertEqual(transport.calls[1]["payload"]["user_id"], "user-1")
        self.assertEqual(transport.calls[1]["payload"]["encoding_aes_key"], "aes-secret")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_jdy_admin_client -v
```

Expected: fail with `ModuleNotFoundError: No module named 'rpa_platform.integrations'`.

- [ ] **Step 3: Implement the Jiandaoyun client**

Create `rpa_platform/integrations/__init__.py`:

```python
"""Integration clients used by the new RPA platform."""
```

Create `rpa_platform/integrations/jdy_admin_client.py`:

```python
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol


class JdyAdminTransport(Protocol):
    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class JdyAdminError(RuntimeError):
    """Base error for Jiandaoyun admin API failures."""


class MissingCorpDeployError(JdyAdminError):
    """Raised when no corp deploy row can be resolved."""


class AmbiguousCorpDeployError(JdyAdminError):
    """Raised when a corp search returns more than one candidate."""


class OwnerCannotBindError(JdyAdminError):
    """Raised when get_owner says the User_ID cannot bind corp secret."""


@dataclass(frozen=True)
class JdyCorpDeploy:
    corp_id: str
    name: str
    tenant_id: str
    suite_name: str
    integrate_suite_name: str
    suite_id: int
    suite_scenario: str


@dataclass(frozen=True)
class JdyCorpDeploySearchResult:
    rows: List[JdyCorpDeploy]
    has_more: bool


@dataclass(frozen=True)
class JdyOwnerCheckResult:
    can_bind_corp_secret: bool


@dataclass(frozen=True)
class JdyInstallRequest:
    corp_id: str
    corp_name: str
    tenant_id: str
    token: str
    encoding_aes_key: str
    suite_id: int
    suite_scenario: str


@dataclass(frozen=True)
class JdyInstallResult:
    tenant_id: str
    owner_id: str


class JdyAdminClient:
    def __init__(self, transport: JdyAdminTransport):
        self.transport = transport

    def search_corp_deploy_list(self, filter_text: str, skip: int = 0, limit: int = 10) -> JdyCorpDeploySearchResult:
        data = self.transport.post_json(
            "/api/fx_sa/wxwork/get_corp_deploy_list",
            {"filter": filter_text.strip(), "skip": skip, "limit": limit},
        )
        rows = [self._parse_corp_row(row) for row in data.get("corp_deploy_list", [])]
        return JdyCorpDeploySearchResult(rows=rows, has_more=bool(data.get("has_more")))

    def resolve_unique_corp(self, plain_corp_id: str, enterprise_name: str) -> JdyCorpDeploy:
        first = self.search_corp_deploy_list(plain_corp_id)
        if len(first.rows) == 1:
            return first.rows[0]
        if len(first.rows) > 1:
            raise AmbiguousCorpDeployError("plain corp id matched multiple corp deploy rows")

        second = self.search_corp_deploy_list(enterprise_name)
        exact_rows = [row for row in second.rows if row.name == enterprise_name]
        if len(exact_rows) == 1:
            return exact_rows[0]
        if len(exact_rows) > 1:
            raise AmbiguousCorpDeployError("enterprise name matched multiple corp deploy rows")
        raise MissingCorpDeployError("no corp deploy row matched plain corp id or enterprise name")

    def check_wework_owner(self, user_id: str, suite_id: int, suite_scenario: str) -> JdyOwnerCheckResult:
        data = self.transport.post_json(
            "/api/fx_sa/wxwork/get_owner",
            {"user_id": user_id, "suite_id": suite_id, "suite_scenario": suite_scenario},
        )
        return JdyOwnerCheckResult(can_bind_corp_secret=bool(data.get("can_bind_corp_secret")))

    def install_corp_deploy(self, request: JdyInstallRequest) -> JdyInstallResult:
        payload = {
            "corp_id": request.corp_id,
            "corp_name": request.corp_name,
            "tenant_id": request.tenant_id,
            "token": request.token,
            "encoding_aes_key": request.encoding_aes_key,
            "user_id": request.tenant_id,
            "suite_id": request.suite_id,
            "suite_scenario": request.suite_scenario,
        }
        data = self.transport.post_json("/api/fx_sa/wxwork/install_corp_deploy", payload)
        return JdyInstallResult(tenant_id=str(data.get("tenant_id", "")), owner_id=str(data.get("owner_id", "")))

    @staticmethod
    def _parse_corp_row(row: Dict[str, Any]) -> JdyCorpDeploy:
        return JdyCorpDeploy(
            corp_id=str(row.get("corp_id", "")),
            name=str(row.get("name", "")),
            tenant_id=str(row.get("tenant_id", "")),
            suite_name=str(row.get("suite_name", "")),
            integrate_suite_name=str(row.get("integrate_suite_name", "")),
            suite_id=int(row.get("suite_id") or 0),
            suite_scenario=str(row.get("suite_scenario", "")),
        )
```

- [ ] **Step 4: Run the client tests and verify they pass**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_jdy_admin_client -v
```

Expected: all tests in `JdyAdminClientTest` pass.

- [ ] **Step 5: Commit**

```bash
git add rpa_platform/integrations/__init__.py rpa_platform/integrations/jdy_admin_client.py tests/test_platform_jdy_admin_client.py
git commit -m "新增简道云后台绑定接口客户端"
```

## Task 2: Runtime Context Storage and Redaction

**Files:**
- Modify: `rpa_platform/storage/sqlite_store.py`
- Create: `rpa_platform/domain/redaction.py`
- Create: `tests/test_platform_task_context.py`

- [ ] **Step 1: Write failing tests for context persistence and redaction**

Create `tests/test_platform_task_context.py`:

```python
import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.redaction import redact_context
from rpa_platform.storage.sqlite_store import SQLiteStore


class TaskContextStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(self.team_id, "企微代开发应用上线", "")
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[{"key": "jdy_resolve_corp", "name": "简道云查找绑定企业", "action": "jdy_resolve_corp"}],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, version_id)
        self.task_id = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="安徽云速付",
            corp_id="ww-demo",
            source_user_id="user-1",
            idempotency_key="wecom_app_launch:ww-demo:user-1",
            payload={"user_id": "user-1", "企业客户名称": "安徽云速付", "企业微信明文 CorpID": "ww-demo"},
        ).task_id

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_merge_task_context_preserves_nested_values(self):
        self.store.merge_task_context(self.task_id, {"jdy": {"corp_secret_id": "secret-corp"}})
        self.store.merge_task_context(self.task_id, {"wecom": {"token": "token-secret"}})

        context = self.store.get_task_context(self.task_id)

        self.assertEqual(context["jdy"]["corp_secret_id"], "secret-corp")
        self.assertEqual(context["wecom"]["token"], "token-secret")

    def test_task_detail_includes_redacted_runtime_context(self):
        self.store.merge_task_context(
            self.task_id,
            {
                "jdy": {"corp_secret_id": "corp-secret-value-1234"},
                "wecom": {"token": "token-secret-value", "encoding_aes_key": "aes-secret-value"},
            },
        )

        detail = self.store.get_task_detail(self.task_id)

        self.assertEqual(detail["runtime_context"]["jdy"]["corp_secret_id"], "corp***1234")
        self.assertEqual(detail["runtime_context"]["wecom"]["token"], "***")
        self.assertEqual(detail["runtime_context"]["wecom"]["encoding_aes_key"], "***")

    def test_redact_context_masks_secret_like_fields(self):
        redacted = redact_context(
            {
                "corp_secret_id": "corp-secret-value-1234",
                "token": "token-secret",
                "encoding_aes_key": "aes-secret",
                "safe": "安徽云速付",
            }
        )

        self.assertEqual(redacted["corp_secret_id"], "corp***1234")
        self.assertEqual(redacted["token"], "***")
        self.assertEqual(redacted["encoding_aes_key"], "***")
        self.assertEqual(redacted["safe"], "安徽云速付")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run context tests and verify they fail**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_task_context -v
```

Expected: fail because `rpa_platform.domain.redaction` and context methods do not exist.

- [ ] **Step 3: Implement redaction helper**

Create `rpa_platform/domain/redaction.py`:

```python
from typing import Any, Dict


SECRET_KEYS = {"token", "aeskey", "encoding_aes_key", "encodingAesKey", "kitsecret", "cookie"}


def mask_identifier(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return "%s***%s" % (value[:4], value[-4:])


def redact_context(value: Any) -> Any:
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, child in value.items():
            if key in SECRET_KEYS:
                result[key] = "***"
            elif key in {"corp_secret_id", "corp_id", "app_id", "aes_app_id"} and isinstance(child, str):
                result[key] = mask_identifier(child)
            else:
                result[key] = redact_context(child)
        return result
    if isinstance(value, list):
        return [redact_context(item) for item in value]
    return value
```

- [ ] **Step 4: Add runtime context column and helpers**

Modify `rpa_platform/storage/sqlite_store.py`:

```python
from rpa_platform.domain.redaction import redact_context
```

Add `runtime_context_json TEXT NOT NULL DEFAULT '{}'` to the `tasks` table in `init_schema`.

Immediately after `conn.executescript(...)` in `init_schema`, add a small idempotent migration for local databases created before this task:

```python
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "runtime_context_json" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN runtime_context_json TEXT NOT NULL DEFAULT '{}'")
```

Add methods to `SQLiteStore`:

```python
    def get_task_context(self, task_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        return json.loads(task.get("runtime_context_json") or "{}")

    def merge_task_context(self, task_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_task_context(task_id)
        merged = self._deep_merge(current, patch)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET runtime_context_json=?, updated_at=?
                WHERE id=?
                """,
                (json.dumps(merged, ensure_ascii=False), now, task_id),
            )
        return merged

    @staticmethod
    def _deep_merge(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(current)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = SQLiteStore._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
```

In `get_task_detail`, add:

```python
        detail["runtime_context"] = redact_context(json.loads(task.get("runtime_context_json") or "{}"))
```

- [ ] **Step 5: Run context tests and full tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_task_context -v
conda run -n RPA_GROUP python -m unittest discover -s tests -v
```

Expected: context tests pass and full suite passes. The known `_distutils_hack` warning may appear with exit code 0.

- [ ] **Step 6: Commit**

```bash
git add rpa_platform/domain/redaction.py rpa_platform/storage/sqlite_store.py tests/test_platform_task_context.py
git commit -m "新增任务运行上下文与敏感字段脱敏"
```

## Task 3: Flow Step Action Validation

**Files:**
- Modify: `rpa_platform/domain/flow_steps.py`
- Modify: `tests/test_platform_flow_steps.py`

- [ ] **Step 1: Add tests for hybrid actions**

Append to `tests/test_platform_flow_steps.py`:

```python
    def test_accepts_hybrid_jdy_wecom_actions(self):
        steps = validate_steps(
            [
                {"key": "jdy_resolve_corp", "name": "简道云查找绑定企业", "action": "jdy_resolve_corp"},
                {"key": "derive_wecom_urls", "name": "生成企微配置 URL", "action": "derive_wecom_urls"},
                {"key": "wecom_configure_app", "name": "企微页面配置代开发应用", "action": "wecom_configure_app"},
                {"key": "jdy_install_bind", "name": "简道云提交企业微信绑定", "action": "jdy_install_bind"},
                {"key": "wecom_submit_online", "name": "企微待上线后提交上线", "action": "wecom_submit_online"},
            ]
        )

        self.assertEqual([step["action"] for step in steps], [
            "jdy_resolve_corp",
            "derive_wecom_urls",
            "wecom_configure_app",
            "jdy_install_bind",
            "wecom_submit_online",
        ])

    def test_rejects_unknown_action_when_allowlist_is_enabled(self):
        with self.assertRaises(FlowStepValidationError) as ctx:
            validate_steps(
                [{"key": "bad", "name": "未知动作", "action": "unknown_action"}],
                enforce_action_allowlist=True,
            )

        self.assertIn("unknown action", str(ctx.exception))
```

- [ ] **Step 2: Run flow step tests and verify they fail**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_flow_steps -v
```

Expected: fail because `validate_steps` does not accept `enforce_action_allowlist`.

- [ ] **Step 3: Implement optional action allowlist**

Modify `rpa_platform/domain/flow_steps.py`:

```python
ALLOWED_ACTIONS = {
    "receive_webhook",
    "open_url",
    "click",
    "derive_urls",
    "jdy_resolve_corp",
    "derive_wecom_urls",
    "wecom_configure_app",
    "jdy_check_owner",
    "jdy_install_bind",
    "wecom_submit_review",
    "wecom_wait_review",
    "wecom_submit_online",
}


def validate_steps(steps: List[Dict[str, Any]], enforce_action_allowlist: bool = False) -> List[Dict[str, Any]]:
```

Inside the loop after reading `action`, add:

```python
        if enforce_action_allowlist and action not in ALLOWED_ACTIONS:
            raise FlowStepValidationError("unknown action: %s" % action)
```

Keep default `enforce_action_allowlist=False` so old tests and existing drafts keep working.

- [ ] **Step 4: Run flow step tests and full tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_flow_steps -v
conda run -n RPA_GROUP python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add rpa_platform/domain/flow_steps.py tests/test_platform_flow_steps.py
git commit -m "补充混合流程步骤动作校验"
```

## Task 4: WeCom RPA Adapter Contract

**Files:**
- Create: `rpa_platform/worker/wecom_rpa.py`
- Create: `tests/test_platform_wecom_rpa.py`

- [ ] **Step 1: Write adapter contract tests**

Create `tests/test_platform_wecom_rpa.py`:

```python
import unittest

from rpa_platform.worker.wecom_rpa import FakeWecomRpa, WecomReviewStatus


class WecomRpaTest(unittest.TestCase):
    def test_fake_rpa_returns_token_and_aeskey_for_configuration(self):
        rpa = FakeWecomRpa(
            configure_result={
                "token": "token-secret",
                "encoding_aes_key": "aes-secret",
                "review_status": "审核中",
            }
        )

        result = rpa.configure_custom_app({"enterprise_name": "安徽云速付"}, {"wecom": {}})

        self.assertEqual(result["token"], "token-secret")
        self.assertEqual(result["encoding_aes_key"], "aes-secret")
        self.assertEqual(result["review_status"], "审核中")

    def test_fake_rpa_reports_ready_to_online_and_submit_success(self):
        rpa = FakeWecomRpa(review_statuses=[WecomReviewStatus.READY_TO_ONLINE])

        status = rpa.check_review_status({"enterprise_name": "安徽云速付"}, {})
        submit = rpa.submit_online({"enterprise_name": "安徽云速付"}, {})

        self.assertEqual(status, WecomReviewStatus.READY_TO_ONLINE)
        self.assertTrue(submit["online_submitted"])
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_wecom_rpa -v
```

Expected: fail because `rpa_platform.worker.wecom_rpa` does not exist.

- [ ] **Step 3: Implement adapter interface and fake**

Create `rpa_platform/worker/wecom_rpa.py`:

```python
from enum import Enum
from typing import Any, Dict, List, Protocol


class WecomReviewStatus(str, Enum):
    REVIEWING = "审核中"
    READY_TO_ONLINE = "待上线"
    ONLINE = "已上线"
    UNKNOWN = "未知"


class WecomRpa(Protocol):
    def configure_custom_app(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def submit_review(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def check_review_status(self, task: Dict[str, Any], context: Dict[str, Any]) -> WecomReviewStatus:
        raise NotImplementedError

    def submit_online(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class FakeWecomRpa:
    def __init__(
        self,
        configure_result: Dict[str, Any] = None,
        review_statuses: List[WecomReviewStatus] = None,
    ):
        self.configure_result = configure_result or {
            "token": "fake-token",
            "encoding_aes_key": "fake-aes-key",
            "review_status": WecomReviewStatus.REVIEWING.value,
        }
        self.review_statuses = list(review_statuses or [WecomReviewStatus.REVIEWING])
        self.calls: List[Dict[str, Any]] = []

    def configure_custom_app(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"action": "configure_custom_app", "task_id": task["id"]})
        return dict(self.configure_result)

    def submit_review(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"action": "submit_review", "task_id": task["id"]})
        return {"review_status": WecomReviewStatus.REVIEWING.value}

    def check_review_status(self, task: Dict[str, Any], context: Dict[str, Any]) -> WecomReviewStatus:
        self.calls.append({"action": "check_review_status", "task_id": task.get("id")})
        if not self.review_statuses:
            return WecomReviewStatus.UNKNOWN
        return self.review_statuses.pop(0)

    def submit_online(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"action": "submit_online", "task_id": task["id"]})
        return {"online_submitted": True, "review_status": WecomReviewStatus.ONLINE.value}
```

- [ ] **Step 4: Run adapter tests and full tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_wecom_rpa -v
conda run -n RPA_GROUP python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add rpa_platform/worker/wecom_rpa.py tests/test_platform_wecom_rpa.py
git commit -m "定义企微页面 RPA 适配器契约"
```

## Task 5: Hybrid Runner Step Engine

**Files:**
- Create: `rpa_platform/worker/hybrid_runner.py`
- Create: `tests/test_platform_hybrid_runner.py`
- Modify: `rpa_platform/storage/sqlite_store.py`

- [ ] **Step 1: Write failing tests for happy path, review wait, and ready-to-online**

Create `tests/test_platform_hybrid_runner.py`:

```python
from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyAdminTransport
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.hybrid_runner import HybridFlowRunner
from rpa_platform.worker.wecom_rpa import FakeWecomRpa, WecomReviewStatus


class FakeTransport(JdyAdminTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, path, payload):
        self.calls.append({"path": path, "payload": payload})
        return self.responses.pop(0)


class HybridFlowRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(self.team_id, "企微代开发应用上线", "")
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[
                {"key": "jdy_resolve_corp", "name": "简道云查找绑定企业", "action": "jdy_resolve_corp"},
                {"key": "derive_wecom_urls", "name": "生成企微配置 URL", "action": "derive_wecom_urls"},
                {"key": "wecom_configure_app", "name": "企微页面配置代开发应用", "action": "wecom_configure_app"},
                {"key": "jdy_check_owner", "name": "简道云校验绑定 User_ID", "action": "jdy_check_owner"},
                {"key": "jdy_install_bind", "name": "简道云提交企业微信绑定", "action": "jdy_install_bind"},
                {"key": "wecom_submit_review", "name": "企微提交上线进入审核", "action": "wecom_submit_review"},
                {"key": "wecom_wait_review", "name": "等待企微审核通过", "action": "wecom_wait_review"},
                {"key": "wecom_submit_online", "name": "企微待上线后提交上线", "action": "wecom_submit_online"},
            ],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, version_id)
        self.task_id = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="安徽云速付",
            corp_id="ww-demo",
            source_user_id="user-1",
            idempotency_key="wecom_app_launch:ww-demo:user-1",
            payload={"user_id": "user-1", "企业客户名称": "安徽云速付", "企业微信明文 CorpID": "ww-demo"},
        ).task_id

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_runner_reaches_waiting_review_after_jdy_bind_and_wecom_review_submit(self):
        transport = FakeTransport([
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
            {"can_bind_corp_secret": True},
            {"tenant_id": "user-1", "owner_id": "user-1"},
        ])
        runner = HybridFlowRunner(
            store=self.store,
            jdy_client=JdyAdminClient(transport),
            wecom_rpa=FakeWecomRpa(),
        )

        result = runner.run_claimed_task(self.task_id, "robot-1")

        task = self.store.get_task(self.task_id)
        context = self.store.get_task_context(self.task_id)
        self.assertEqual(result["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(task["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(context["jdy"]["corp_secret_id"], "corp-secret")
        self.assertEqual(context["wecom"]["homeurl"], "https://wxwork.jiandaoyun.com/wxwork/corp-secret/dashboard")
        self.assertEqual(context["wecom"]["token"], "fake-token")
        self.assertEqual(transport.calls[-1]["path"], "/api/fx_sa/wxwork/install_corp_deploy")

    def test_reviewing_status_keeps_waiting_review_with_next_check(self):
        self.store.set_task_status(self.task_id, TaskStatus.WAITING_WECOM_REVIEW)
        self.store.merge_task_context(self.task_id, {"wecom": {"review_status": "审核中"}})
        runner = HybridFlowRunner(
            store=self.store,
            jdy_client=JdyAdminClient(FakeTransport([])),
            wecom_rpa=FakeWecomRpa(review_statuses=[WecomReviewStatus.REVIEWING]),
        )

        result = runner.run_claimed_task(self.task_id, "robot-1", now=datetime(2026, 6, 8, 10, 0, 0))

        task = self.store.get_task(self.task_id)
        self.assertEqual(result["status"], TaskStatus.WAITING_WECOM_REVIEW.value)
        self.assertEqual(task["next_check_at"], "2026-06-08 10:10:00")

    def test_ready_to_online_status_then_submit_online_marks_success(self):
        self.store.set_task_status(self.task_id, TaskStatus.READY_TO_ONLINE)
        runner = HybridFlowRunner(
            store=self.store,
            jdy_client=JdyAdminClient(FakeTransport([])),
            wecom_rpa=FakeWecomRpa(review_statuses=[WecomReviewStatus.READY_TO_ONLINE]),
        )

        result = runner.run_claimed_task(self.task_id, "robot-1")

        self.assertEqual(result["status"], TaskStatus.SUCCESS.value)
        self.assertEqual(self.store.get_task(self.task_id)["status"], TaskStatus.SUCCESS.value)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run hybrid runner tests and verify they fail**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_hybrid_runner -v
```

Expected: fail because `rpa_platform.worker.hybrid_runner` does not exist.

- [ ] **Step 3: Add current step helper**

Modify `rpa_platform/storage/sqlite_store.py` with:

```python
    def set_task_current_step(self, task_id: str, step_key: str) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET current_step_key=?, updated_at=?
                WHERE id=?
                """,
                (step_key, now, task_id),
            )
```

- [ ] **Step 4: Implement hybrid runner**

Create `rpa_platform/worker/hybrid_runner.py`:

```python
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyInstallRequest, OwnerCannotBindError
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.wecom_rpa import WecomReviewStatus, WecomRpa


class HybridFlowRunner:
    def __init__(self, store: SQLiteStore, jdy_client: JdyAdminClient, wecom_rpa: WecomRpa):
        self.store = store
        self.jdy_client = jdy_client
        self.wecom_rpa = wecom_rpa

    def run_claimed_task(self, task_id: str, robot_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        task = self.store.get_task(task_id)
        status = TaskStatus(task["status"])
        if status == TaskStatus.WAITING_WECOM_REVIEW:
            return self._check_review(task_id, robot_id, now)
        if status == TaskStatus.READY_TO_ONLINE:
            return self._submit_online(task_id, robot_id)

        self.store.set_task_status(task_id, TaskStatus.RUNNING, assigned_robot_id=robot_id)
        task = self.store.get_task(task_id)
        for step in self._snapshot_steps(task):
            if not step.get("enabled", True):
                continue
            self.store.set_task_current_step(task_id, step["key"])
            action = step["action"]
            if action == "jdy_resolve_corp":
                self._jdy_resolve_corp(task_id)
            elif action == "derive_wecom_urls":
                self._derive_wecom_urls(task_id)
            elif action == "wecom_configure_app":
                self._wecom_configure_app(task_id)
            elif action == "jdy_check_owner":
                self._jdy_check_owner(task_id)
            elif action == "jdy_install_bind":
                self._jdy_install_bind(task_id)
            elif action == "wecom_submit_review":
                return self._submit_review(task_id, robot_id, now)
            elif action in {"wecom_wait_review", "wecom_submit_online"}:
                continue
            else:
                raise ValueError("Unsupported hybrid action: %s" % action)

        self.store.set_task_status(task_id, TaskStatus.SUCCESS, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.SUCCESS.value}

    def _jdy_resolve_corp(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        row = self.jdy_client.resolve_unique_corp(task["corp_id"], task["enterprise_name"])
        self.store.merge_task_context(
            task_id,
            {
                "jdy": {
                    "corp_secret_id": row.corp_id,
                    "corp_name": row.name,
                    "tenant_id": row.tenant_id,
                    "suite_id": row.suite_id,
                    "suite_scenario": row.suite_scenario,
                    "suite_name": row.suite_name,
                    "integrate_suite_name": row.integrate_suite_name,
                }
            },
        )
        self.store.append_task_step(task_id, "jdy_resolve_corp", "简道云查找绑定企业", "success")

    def _derive_wecom_urls(self, task_id: str) -> None:
        context = self.store.get_task_context(task_id)
        corp_secret_id = context["jdy"]["corp_secret_id"]
        self.store.merge_task_context(
            task_id,
            {
                "wecom": {
                    "homeurl": "https://wxwork.jiandaoyun.com/wxwork/%s/dashboard" % corp_secret_id,
                    "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/%s/service" % corp_secret_id,
                    "redirect_domain": "wxwork.jiandaoyun.com",
                }
            },
        )
        self.store.append_task_step(task_id, "derive_wecom_urls", "生成企微配置 URL", "success")

    def _wecom_configure_app(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.wecom_rpa.configure_custom_app(task, context)
        self.store.merge_task_context(
            task_id,
            {
                "wecom": {
                    "token": result["token"],
                    "encoding_aes_key": result["encoding_aes_key"],
                    "review_status": result.get("review_status", "配置完成"),
                }
            },
        )
        self.store.append_task_step(task_id, "wecom_configure_app", "企微页面配置代开发应用", "success")

    def _jdy_check_owner(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.jdy_client.check_wework_owner(
            task["source_user_id"],
            suite_id=int(context["jdy"]["suite_id"]),
            suite_scenario=context["jdy"]["suite_scenario"],
        )
        if not result.can_bind_corp_secret:
            raise OwnerCannotBindError("User_ID cannot bind corp secret")
        self.store.append_task_step(task_id, "jdy_check_owner", "简道云校验绑定 User_ID", "success")

    def _jdy_install_bind(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.jdy_client.install_corp_deploy(
            JdyInstallRequest(
                corp_id=context["jdy"]["corp_secret_id"],
                corp_name=context["jdy"]["corp_name"],
                tenant_id=task["source_user_id"],
                token=context["wecom"]["token"],
                encoding_aes_key=context["wecom"]["encoding_aes_key"],
                suite_id=int(context["jdy"]["suite_id"]),
                suite_scenario=context["jdy"]["suite_scenario"],
            )
        )
        self.store.merge_task_context(task_id, {"jdy": {"install_tenant_id": result.tenant_id, "install_owner_id": result.owner_id}})
        self.store.append_task_step(task_id, "jdy_install_bind", "简道云提交企业微信绑定", "success")

    def _submit_review(self, task_id: str, robot_id: str, now: Optional[datetime]) -> Dict[str, Any]:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.wecom_rpa.submit_review(task, context)
        self.store.merge_task_context(task_id, {"wecom": {"review_status": result.get("review_status", "审核中")}})
        next_check = (now or datetime.now()) + timedelta(minutes=10)
        self.store.set_task_status(task_id, TaskStatus.WAITING_WECOM_REVIEW, next_check_at=next_check, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        self.store.append_task_step(task_id, "wecom_submit_review", "企微提交上线进入审核", "success")
        return {"task_id": task_id, "status": TaskStatus.WAITING_WECOM_REVIEW.value}

    def _check_review(self, task_id: str, robot_id: str, now: Optional[datetime]) -> Dict[str, Any]:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        status = self.wecom_rpa.check_review_status(task, context)
        self.store.merge_task_context(task_id, {"wecom": {"review_status": status.value}})
        if status == WecomReviewStatus.READY_TO_ONLINE:
            self.store.set_task_status(task_id, TaskStatus.READY_TO_ONLINE, assigned_robot_id=None)
            self.store.update_robot_status(robot_id, "idle")
            return {"task_id": task_id, "status": TaskStatus.READY_TO_ONLINE.value}
        next_check = (now or datetime.now()) + timedelta(minutes=10)
        self.store.set_task_status(task_id, TaskStatus.WAITING_WECOM_REVIEW, next_check_at=next_check, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.WAITING_WECOM_REVIEW.value}

    def _submit_online(self, task_id: str, robot_id: str) -> Dict[str, Any]:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.wecom_rpa.submit_online(task, context)
        self.store.merge_task_context(task_id, {"wecom": {"review_status": result.get("review_status", "已上线")}})
        self.store.set_task_status(task_id, TaskStatus.SUCCESS, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        self.store.append_task_step(task_id, "wecom_submit_online", "企微待上线后提交上线", "success")
        return {"task_id": task_id, "status": TaskStatus.SUCCESS.value}

    @staticmethod
    def _snapshot_steps(task: Dict[str, Any]):
        return json.loads(task["flow_version_snapshot_json"])["steps"]
```

- [ ] **Step 5: Run hybrid runner tests and full tests**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_hybrid_runner -v
conda run -n RPA_GROUP python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add rpa_platform/worker/hybrid_runner.py rpa_platform/storage/sqlite_store.py tests/test_platform_hybrid_runner.py
git commit -m "串联简道云接口与企微 RPA 混合执行器"
```

## Task 6: Flow Fixture, Docs, and Verification

**Files:**
- Create: `rpa_platform/domain/default_flows.py`
- Modify: `docs/rpa_platform_refactor_design.md`
- Modify: `docs/jdy_wework_bind_api_research.md`
- Test: `tests/test_platform_flow_steps.py`

- [ ] **Step 1: Add default flow fixture test**

Append to `tests/test_platform_flow_steps.py`:

```python
    def test_default_wecom_launch_flow_steps_validate_with_allowlist(self):
        from rpa_platform.domain.default_flows import WECOM_APP_LAUNCH_FLOW_STEPS

        steps = validate_steps(WECOM_APP_LAUNCH_FLOW_STEPS, enforce_action_allowlist=True)

        self.assertEqual(steps[0]["key"], "jdy_resolve_corp")
        self.assertEqual(steps[-1]["key"], "wecom_submit_online")
```

- [ ] **Step 2: Run flow tests and verify they fail**

Run:

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_flow_steps -v
```

Expected: fail because `rpa_platform.domain.default_flows` does not exist.

- [ ] **Step 3: Add default flow fixture**

Create `rpa_platform/domain/default_flows.py`:

```python
WECOM_APP_LAUNCH_FLOW_STEPS = [
    {"key": "jdy_resolve_corp", "name": "简道云查找绑定企业", "action": "jdy_resolve_corp", "target": "jdy"},
    {"key": "derive_wecom_urls", "name": "生成企微配置 URL", "action": "derive_wecom_urls", "target": "system"},
    {"key": "wecom_configure_app", "name": "企微页面配置代开发应用", "action": "wecom_configure_app", "target": "wecom"},
    {"key": "jdy_check_owner", "name": "简道云校验绑定 User_ID", "action": "jdy_check_owner", "target": "jdy"},
    {"key": "jdy_install_bind", "name": "简道云提交企业微信绑定", "action": "jdy_install_bind", "target": "jdy"},
    {"key": "wecom_submit_review", "name": "企微提交上线进入审核", "action": "wecom_submit_review", "target": "wecom"},
    {"key": "wecom_wait_review", "name": "等待企微审核通过", "action": "wecom_wait_review", "target": "wecom"},
    {"key": "wecom_submit_online", "name": "企微待上线后提交上线", "action": "wecom_submit_online", "target": "wecom"},
]
```

- [ ] **Step 4: Update docs**

In `docs/rpa_platform_refactor_design.md`, add a short section under the sample flow describing the final first-version boundary:

```markdown
### 5.x 第一版执行边界更新

第一版采用混合执行：

- 简道云后台企业微信绑定页使用内部接口优先，负责搜索绑定企业、读取密文企业 ID、校验 User_ID 和最终提交绑定。
- 企微开发者后台仍使用页面 RPA，负责授权企业搜索、开始代开发应用、应用试用、使用配置、回调配置、权限设置、提交审核、待上线后提交上线。
- 企微提交接口仅用于排障理解，不作为第一版自动执行入口。
```

In `docs/jdy_wework_bind_api_research.md`, keep the existing decision section. If implementation names differ from this plan, update the action names there to match `WECOM_APP_LAUNCH_FLOW_STEPS`.

- [ ] **Step 5: Run full verification**

Run:

```bash
conda run -n RPA_GROUP python -m unittest discover -s tests -v
git status -sb
```

Expected:

- All unittest cases pass.
- Known `_distutils_hack` warning may appear with exit code 0.
- `git status -sb` shows only intended new platform files and docs, no `.env`, `config.py`, logs, database, screenshots, or zip files staged.

- [ ] **Step 6: Commit**

```bash
git add rpa_platform/domain/default_flows.py docs/rpa_platform_refactor_design.md docs/jdy_wework_bind_api_research.md tests/test_platform_flow_steps.py
git commit -m "补充企微上线混合流程默认步骤与文档"
```

## Execution Notes

- Do not stage or commit root `.env`, `config.py`, `rpa.log`, `failed_tasks.log`, `rpa.db`, screenshots, or zip archives.
- Do not modify `RPA.py`.
- Do not call live `install_corp_deploy` or any WeCom submit endpoint during tests.
- Live verification should be a separate manual run after all unit tests pass and after the operator confirms current browser login state.
- If a task is already bound to a different `tenant_id`, create a `waiting_manual_selection` or `waiting_manual_intervention` manual action; do not auto-switch binding in this first implementation.
- If WeCom RPA cannot read token/aeskey, stop before `jdy_install_bind` and move to `waiting_manual_intervention`; never call Jiandaoyun final binding with empty secrets.

## Self-Review

- Spec coverage:
  - Jiandaoyun search, owner check, install bind: Task 1 and Task 5.
  - Sensitive field redaction: Task 2.
  - WeCom remains RPA: Task 4 and Task 5.
  - Review state `审核中 -> 待上线 -> 提交上线`: Task 4 and Task 5.
  - Default flow and docs: Task 6.
- Placeholder scan:
  - No unresolved placeholder markers remain.
  - All code-writing steps include concrete code blocks.
- Type consistency:
  - `JdyInstallRequest.encoding_aes_key` maps to Jiandaoyun payload `encoding_aes_key`.
  - WeCom context uses `encoding_aes_key`, while WeCom API research uses `aeskey`; the adapter normalizes to `encoding_aes_key`.
  - Existing `TaskStatus.WAITING_WECOM_REVIEW` and `TaskStatus.READY_TO_ONLINE` are reused; no new enum needed.
