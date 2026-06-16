import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import parse, request

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rpa_platform.domain.redaction import mask_identifier
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyAdminError, JdyCorpDeploy
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient, WecomAdminError
from rpa_platform.services.wecom_bind_service import JdyWecomBindInput


JDY_BASE_URL = "https://dc.jdydevelop.com"
WECOM_BASE_URL = "https://open.work.weixin.qq.com"


class CookieSourceError(RuntimeError):
    """Raised when a required local cookie source is missing."""


class JsonHttpError(RuntimeError):
    """Raised for HTTP or JSON transport errors without exposing Cookie headers."""


class JdyCookieTransport:
    def __init__(self, cookie: str, base_url: str = JDY_BASE_URL, timeout: int = 20):
        self.cookie = cookie
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return _request_json(
            method="POST",
            url=self.base_url + path,
            payload=payload,
            headers={
                "content-type": "application/json",
                "cookie": self.cookie,
                "origin": self.base_url,
                "referer": self.base_url + "/",
            },
            timeout=self.timeout,
        )


class WecomCookieTransport:
    def __init__(self, cookie: str, base_url: str = WECOM_BASE_URL, timeout: int = 20):
        self.cookie = cookie
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_json(
        self,
        path: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        query = parse.urlencode(params)
        url = self.base_url + path + ("?" + query if query else "")
        return _request_json(
            method="GET",
            url=url,
            payload=None,
            headers=self._headers(headers),
            timeout=self.timeout,
        )

    def post_json(
        self,
        path: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        query = parse.urlencode({"lang": "zh_CN", "ajax": 1, "f": "json", "random": 0})
        return _request_json(
            method="POST",
            url=self.base_url + path + "?" + query,
            payload=payload,
            headers=self._headers(headers),
            timeout=self.timeout,
        )

    def _headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        merged = {
            "content-type": "application/json",
            "cookie": self.cookie,
            "origin": self.base_url,
            "referer": self.base_url + "/wwopen/developers/tools",
        }
        merged.update(headers)
        return merged


def run_readonly_preflight(
    bind_input: JdyWecomBindInput,
    jdy_client: JdyAdminClient,
    wecom_client: WecomAdminClient,
) -> Dict[str, Any]:
    acceptable_names = _acceptable_enterprise_names(bind_input)
    jdy_lookup_name = bind_input.enterprise_short_name or bind_input.enterprise_name
    owner = None
    try:
        corp = jdy_client.resolve_unique_corp(bind_input.plain_corp_id, jdy_lookup_name)
    except (JdyAdminError, JsonHttpError) as exc:
        try:
            owner = jdy_client.check_wework_owner(
                bind_input.requested_user_id,
                suite_id=bind_input.suite_id,
                suite_scenario=bind_input.suite_scenario,
            )
        except (JdyAdminError, JsonHttpError) as owner_exc:
            return _failure_summary(bind_input, "jdy_corp_not_unique_or_missing", owner_exc)
        corp = _recover_corp_from_owner(bind_input, owner)
        if corp is None:
            return _failure_summary(bind_input, "jdy_corp_not_unique_or_missing", exc)

    if corp.name not in acceptable_names:
        return _summary(
            bind_input=bind_input,
            corp=corp,
            app=None,
            status="blocked",
            reason="jdy_corp_name_mismatch",
            owner_state="not_checked",
        )

    if owner is None:
        try:
            owner = jdy_client.check_wework_owner(
                bind_input.requested_user_id,
                suite_id=bind_input.suite_id,
                suite_scenario=bind_input.suite_scenario,
            )
        except (JdyAdminError, JsonHttpError) as exc:
            return _failure_summary(bind_input, "jdy_owner_check_failed", exc, corp=corp)

    owner_state = _owner_state(owner.can_bind_corp_secret, owner.can_update_corp_secret)
    if owner_state == "cannot_bind_or_update":
        return _summary(
            bind_input=bind_input,
            corp=corp,
            app=None,
            status="blocked",
            reason="owner_cannot_bind_or_update_corp_secret",
            owner_state=owner_state,
        )

    try:
        wecom_authcorp_name = bind_input.enterprise_short_name or corp.name or bind_input.enterprise_name
        app = wecom_client.resolve_unique_custom_app(
            suiteid=bind_input.wecom_suiteid,
            enterprise_name=wecom_authcorp_name,
            suite_name=bind_input.suite_name,
        )
    except (WecomAdminError, JsonHttpError) as exc:
        return _failure_summary(
            bind_input,
            "wecom_app_not_unique_or_missing",
            exc,
            corp=corp,
            owner_state=owner_state,
        )

    if not app.app_id:
        reason = "wecom_app_id_missing"
        status = "blocked"
    elif not app.aes_app_id:
        reason = "wecom_aes_app_id_missing"
        status = "blocked"
    elif owner_state == "can_update_corp_secret":
        reason = "owner_already_bound_can_update_corp_secret"
        status = "review"
    else:
        reason = "ready_for_confirm_write"
        status = "ok"

    return _summary(
        bind_input=bind_input,
        corp=corp,
        app=app,
        status=status,
        reason=reason,
        owner_state=owner_state,
    )


def build_real_clients(
    jdy_cookie_file: Optional[str] = None,
    wecom_cookie_file: Optional[str] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    jdy_cookie = _read_cookie("JDY_ADMIN_COOKIE", "JDY_ADMIN_COOKIE_FILE", jdy_cookie_file)
    wecom_cookie = _read_cookie("WECOM_ADMIN_COOKIE", "WECOM_ADMIN_COOKIE_FILE", wecom_cookie_file)
    return {
        "jdy_client": JdyAdminClient(JdyCookieTransport(jdy_cookie, timeout=timeout)),
        "wecom_client": WecomAdminClient(WecomCookieTransport(wecom_cookie, timeout=timeout)),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run real read-only preflight for Jiandaoyun-WeCom bind.")
    parser.add_argument("--enterprise-name", required=True)
    parser.add_argument("--enterprise-short-name", default="")
    parser.add_argument("--plain-corp-id", required=True)
    parser.add_argument("--requested-user-id", required=True)
    parser.add_argument("--suite-id", type=int, default=1)
    parser.add_argument("--suite-scenario", default="main")
    parser.add_argument("--wecom-suiteid", type=int, default=1009479)
    parser.add_argument("--suite-name", default="简道云")
    parser.add_argument("--jdy-cookie-file", default=None)
    parser.add_argument("--wecom-cookie-file", default=None)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--use-fake-transport-for-test",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    bind_input = JdyWecomBindInput(
        enterprise_name=args.enterprise_name,
        enterprise_short_name=args.enterprise_short_name,
        plain_corp_id=args.plain_corp_id,
        requested_user_id=args.requested_user_id,
        suite_id=args.suite_id,
        suite_scenario=args.suite_scenario,
        wecom_suiteid=args.wecom_suiteid,
        suite_name=args.suite_name,
    )

    if args.use_fake_transport_for_test:
        clients = _build_fake_clients_for_test()
    else:
        try:
            clients = build_real_clients(
                jdy_cookie_file=args.jdy_cookie_file,
                wecom_cookie_file=args.wecom_cookie_file,
                timeout=args.timeout,
            )
        except CookieSourceError as exc:
            result = _missing_cookie_summary(bind_input, exc)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 2

    result = run_readonly_preflight(bind_input, **clients)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"ok", "review"} else 2


def _request_json(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]],
    headers: Dict[str, str],
    timeout: int,
) -> Dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:
        raise JsonHttpError("%s %s failed: %s" % (method, _safe_url(url), exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsonHttpError("%s %s returned non-JSON response" % (method, _safe_url(url))) from exc
    if not isinstance(data, dict):
        raise JsonHttpError("%s %s returned non-object JSON" % (method, _safe_url(url)))
    return data


def _read_cookie(env_name: str, file_env_name: str, explicit_file: Optional[str]) -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    path = explicit_file or os.environ.get(file_env_name, "").strip()
    if not path:
        raise CookieSourceError(
            "missing cookie source: set %s or %s, or pass the matching --*-cookie-file" % (
                env_name,
                file_env_name,
            )
        )
    cookie = Path(path).read_text(encoding="utf-8").strip()
    if not cookie:
        raise CookieSourceError("cookie file is empty: %s" % path)
    return cookie


def _safe_url(url: str) -> str:
    parsed = parse.urlsplit(url)
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _owner_state(can_bind: bool, can_update: bool) -> str:
    if can_bind:
        return "can_bind_corp_secret"
    if can_update:
        return "can_update_corp_secret"
    return "cannot_bind_or_update"


def _acceptable_enterprise_names(bind_input: JdyWecomBindInput) -> List[str]:
    return [
        value
        for value in {
            bind_input.enterprise_name.strip(),
            bind_input.enterprise_short_name.strip(),
        }
        if value
    ]


def _recover_corp_from_owner(bind_input: JdyWecomBindInput, owner: Any) -> Optional[JdyCorpDeploy]:
    if not owner.can_update_corp_secret or not owner.owner_corp_id:
        return None
    corp_name = owner.corp_name or bind_input.enterprise_short_name or bind_input.enterprise_name
    if corp_name not in _acceptable_enterprise_names(bind_input):
        return None
    return JdyCorpDeploy(
        corp_id=owner.owner_corp_id,
        name=corp_name,
        tenant_id=bind_input.requested_user_id,
        suite_name=bind_input.suite_name,
        integrate_suite_name="",
        suite_id=bind_input.suite_id,
        suite_scenario=bind_input.suite_scenario,
    )


def _summary(
    bind_input: JdyWecomBindInput,
    corp: Any,
    app: Any,
    status: str,
    reason: str,
    owner_state: str,
) -> Dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "enterprise_name": bind_input.enterprise_name,
        "enterprise_short_name": bind_input.enterprise_short_name,
        "plain_corp_id": mask_identifier(bind_input.plain_corp_id),
        "jdy": {
            "corp_secret_id": mask_identifier(corp.corp_id),
            "corp_name": corp.name,
            "original_tenant_id": corp.tenant_id,
            "requested_user_id": bind_input.requested_user_id,
            "suite_id": corp.suite_id,
            "suite_scenario": corp.suite_scenario,
            "suite_name": corp.suite_name,
            "integrate_suite_name": corp.integrate_suite_name,
            "owner_state": owner_state,
        },
        "wecom": {
            "suiteid": bind_input.wecom_suiteid,
            "suite_name": bind_input.suite_name,
            "app_id": app.app_id if app else "",
            "authcorp_name": app.authcorp_name if app else "",
            "aes_app_id": mask_identifier(app.aes_app_id) if app else "",
            "customized_app_status": app.customized_app_status if app else None,
        },
    }


def _failure_summary(
    bind_input: JdyWecomBindInput,
    reason: str,
    exc: Exception,
    corp: Any = None,
    owner_state: str = "not_checked",
) -> Dict[str, Any]:
    if corp is None:
        return {
            "status": "blocked",
            "reason": reason,
            "detail": str(exc),
            "enterprise_name": bind_input.enterprise_name,
            "enterprise_short_name": bind_input.enterprise_short_name,
            "plain_corp_id": mask_identifier(bind_input.plain_corp_id),
            "jdy": {
                "corp_secret_id": "",
                "original_tenant_id": "",
                "requested_user_id": bind_input.requested_user_id,
                "owner_state": owner_state,
            },
            "wecom": {"suiteid": bind_input.wecom_suiteid, "suite_name": bind_input.suite_name},
        }
    result = _summary(bind_input, corp, None, "blocked", reason, owner_state)
    result["detail"] = str(exc)
    return result


def _missing_cookie_summary(bind_input: JdyWecomBindInput, exc: Exception) -> Dict[str, Any]:
    return {
        "status": "blocked",
        "reason": "missing_cookie_source",
        "detail": str(exc),
        "enterprise_name": bind_input.enterprise_name,
        "enterprise_short_name": bind_input.enterprise_short_name,
        "plain_corp_id": mask_identifier(bind_input.plain_corp_id),
        "jdy": {
            "requested_user_id": bind_input.requested_user_id,
            "suite_id": bind_input.suite_id,
            "suite_scenario": bind_input.suite_scenario,
        },
        "wecom": {"suiteid": bind_input.wecom_suiteid, "suite_name": bind_input.suite_name},
    }


def _build_fake_clients_for_test() -> Dict[str, Any]:
    class FakeJdyTransport:
        def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
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
                return {"can_bind_corp_secret": True}
            raise AssertionError("unexpected fake Jiandaoyun path %s" % path)

    class FakeWecomTransport:
        def get_json(
            self,
            path: str,
            params: Dict[str, Any],
            headers: Dict[str, str],
        ) -> Dict[str, Any]:
            if path == "/wwopen/developer/customApp/tpl/app/list":
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
            raise AssertionError("unexpected fake WeCom GET path %s" % path)

        def post_json(
            self,
            path: str,
            payload: Dict[str, Any],
            headers: Dict[str, str],
        ) -> Dict[str, Any]:
            raise AssertionError("fake readonly preflight must not POST to WeCom")

    return {
        "jdy_client": JdyAdminClient(FakeJdyTransport()),
        "wecom_client": WecomAdminClient(FakeWecomTransport()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
