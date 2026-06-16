import argparse
import json
import stat
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rpa_platform.domain.redaction import redact_context
from rpa_platform.integrations.jdy_admin_client import (
    JdyAdminClient,
    JdyAdminError,
    JdyCorpDeploy,
    JdyInstallRequest,
    OwnerCannotBindError,
)
from rpa_platform.integrations.wecom_admin_client import (
    WecomAdminClient,
    WecomAdminError,
    WecomSaveAppRequest,
)
from rpa_platform.services.wecom_bind_service import JdyWecomBindInput, JdyWecomBindService
from scripts.dev.check_wecom_bind_real_readonly import (
    JdyCookieTransport,
    WecomCookieTransport,
    build_real_clients,
    run_readonly_preflight,
)
from scripts.dev.run_platform_dryrun import FakeServiceJdyAdminTransport, FakeServiceWecomAdminTransport
from rpa_platform.services.wecom_bind_service import (
    FixedWecomSecretGenerator,
    JdyWecomBindResult,
    RandomWecomSecretGenerator,
)


def default_context_file() -> Path:
    return REPO_ROOT / ".local" / "wecom-bind-real-write-context.json"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run real Jiandaoyun-WeCom bind write flow.")
    parser.add_argument("--enterprise-name", required=True)
    parser.add_argument("--enterprise-short-name", default="")
    parser.add_argument("--plain-corp-id", required=True)
    parser.add_argument("--requested-user-id", required=True)
    parser.add_argument("--suite-id", type=int, default=1)
    parser.add_argument("--suite-scenario", default="main")
    parser.add_argument("--wecom-suiteid", type=int, default=1009479)
    parser.add_argument("--suite-name", default="简道云")
    parser.add_argument("--jdy-cookie-file", default=".local/jdy-admin.cookie")
    parser.add_argument("--wecom-cookie-file", default=".local/wecom-admin.cookie")
    parser.add_argument("--context-file", default=str(default_context_file()))
    parser.add_argument("--wait-seconds", type=int, default=300)
    parser.add_argument("--confirm-write", action="store_true")
    parser.add_argument("--use-fake-transport-for-test", action="store_true", help=argparse.SUPPRESS)
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

    if not args.confirm_write:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "missing_confirm_write",
                    "enterprise_name": args.enterprise_name,
                    "enterprise_short_name": args.enterprise_short_name,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    if args.use_fake_transport_for_test:
        jdy_client = JdyAdminClient(FakeServiceJdyAdminTransport())
        wecom_client = WecomAdminClient(FakeServiceWecomAdminTransport())
        secret_generator = FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret")
    else:
        clients = build_real_clients(
            jdy_cookie_file=args.jdy_cookie_file,
            wecom_cookie_file=args.wecom_cookie_file,
        )
        jdy_client = clients["jdy_client"]
        wecom_client = clients["wecom_client"]
        secret_generator = RandomWecomSecretGenerator()

    preflight = run_readonly_preflight(bind_input, jdy_client=jdy_client, wecom_client=wecom_client)
    if preflight.get("status") not in {"ok", "review"}:
        print(
            json.dumps(
                {"status": "blocked", "reason": "preflight_not_ok", "preflight": preflight},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    service = JdyWecomBindService(
        jdy_client=jdy_client,
        wecom_client=wecom_client,
        secret_generator=secret_generator,
    )
    context_file = Path(args.context_file)
    start_result = _start_bind_with_recoverable_context(
        bind_input=bind_input,
        jdy_client=jdy_client,
        wecom_client=wecom_client,
        secret_generator=secret_generator,
        context_file=context_file,
        now=datetime.now(),
    )

    if args.wait_seconds > 0:
        time.sleep(args.wait_seconds)

    submit_result = service.submit_online_order(start_result.context)
    start_result.context["wecom"]["auditorder_status"] = submit_result.context["wecom"]["auditorder_status"]
    _write_private_json(context_file, start_result.context)
    result = {
        "status": submit_result.status,
        "preflight": preflight,
        "context_file": str(context_file),
        "start_result": {
            "status": start_result.status,
            "next_check_at": start_result.next_check_at.strftime("%Y-%m-%d %H:%M:%S")
            if start_result.next_check_at
            else None,
            "context": redact_context(start_result.context),
        },
        "submit_result": {
            "status": submit_result.status,
            "context": redact_context(submit_result.context),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if submit_result.status == "success" else 2


def _start_bind_with_recoverable_context(
    bind_input: JdyWecomBindInput,
    jdy_client: JdyAdminClient,
    wecom_client: WecomAdminClient,
    secret_generator: Any,
    context_file: Path,
    now: datetime,
) -> JdyWecomBindResult:
    owner = None
    try:
        corp = jdy_client.resolve_unique_corp(
            bind_input.plain_corp_id,
            bind_input.enterprise_short_name or bind_input.enterprise_name,
        )
    except JdyAdminError:
        owner = jdy_client.check_wework_owner(
            bind_input.requested_user_id,
            suite_id=bind_input.suite_id,
            suite_scenario=bind_input.suite_scenario,
        )
        corp = _recover_corp_from_owner_for_write(bind_input, owner)
        if corp is None:
            raise
    wecom_authcorp_name = bind_input.enterprise_short_name or corp.name or bind_input.enterprise_name
    app = wecom_client.resolve_unique_custom_app(
        suiteid=bind_input.wecom_suiteid,
        enterprise_name=wecom_authcorp_name,
        suite_name=bind_input.suite_name,
    )
    if owner is None:
        owner = jdy_client.check_wework_owner(
            bind_input.requested_user_id,
            suite_id=bind_input.suite_id,
            suite_scenario=bind_input.suite_scenario,
        )
    if not owner.can_bind_corp_secret and not owner.can_update_corp_secret:
        raise OwnerCannotBindError("User_ID cannot bind or update corp secret")

    homeurl = "https://wxwork.jiandaoyun.com/wxwork/%s/dashboard" % corp.corp_id
    callbackurl = "https://wxwork.jiandaoyun.com/wxwork/corp/%s/service" % corp.corp_id
    redirect_domain = "wxwork.jiandaoyun.com"
    if owner.can_update_corp_secret and owner.existing_token and owner.existing_encoding_aes_key:
        secrets_payload = {
            "token": owner.existing_token,
            "encoding_aes_key": owner.existing_encoding_aes_key,
        }
        install_tenant_id = bind_input.requested_user_id
        install_owner_id = bind_input.requested_user_id
    else:
        secrets_payload = secret_generator.generate()
        install = jdy_client.install_corp_deploy(
            JdyInstallRequest(
                corp_id=corp.corp_id,
                corp_name=corp.name,
                tenant_id=bind_input.requested_user_id,
                token=secrets_payload["token"],
                encoding_aes_key=secrets_payload["encoding_aes_key"],
                suite_id=bind_input.suite_id,
                suite_scenario=bind_input.suite_scenario,
            )
        )
        install_tenant_id = install.tenant_id.strip()
        install_owner_id = install.owner_id.strip()
        if not install_tenant_id or not install_owner_id:
            raise JdyAdminError("install_corp_deploy returned empty tenant_id or owner_id")

    context = {
        "jdy": {
            "corp_secret_id": corp.corp_id,
            "corp_name": corp.name,
            "original_tenant_id": corp.tenant_id,
            "requested_user_id": bind_input.requested_user_id,
            "install_tenant_id": install_tenant_id,
            "install_owner_id": install_owner_id,
            "bound_user_id": install_owner_id,
            "suite_id": corp.suite_id,
            "suite_scenario": corp.suite_scenario,
            "suite_name": corp.suite_name,
            "integrate_suite_name": corp.integrate_suite_name,
        },
        "wecom": {
            "suiteid": bind_input.wecom_suiteid,
            "suite_name": bind_input.suite_name,
            "app_id": app.app_id,
            "aes_app_id": app.aes_app_id,
            "homeurl": homeurl,
            "callbackurl": callbackurl,
            "redirect_domain": redirect_domain,
            "token": secrets_payload["token"],
            "encoding_aes_key": secrets_payload["encoding_aes_key"],
            "auditorderid": "",
            "auditorder_status": None,
            "order_created_at": "",
        },
    }
    _write_private_json(context_file, context)

    save_request = WecomSaveAppRequest(
        suiteid=bind_input.wecom_suiteid,
        app=app,
        homeurl=homeurl,
        callbackurl=callbackurl,
        redirect_domain=redirect_domain,
        token=secrets_payload["token"],
        encoding_aes_key=secrets_payload["encoding_aes_key"],
    )
    _save_development_info_and_confirm(wecom_client, save_request)
    wecom_client.set_target_privileges(suiteid=bind_input.wecom_suiteid, app_id=app.app_id)
    wecom_client.set_trial_rule(app_id=app.app_id)
    wecom_client.set_sso_redirect_domain(
        suiteid=bind_input.wecom_suiteid,
        app_id=app.app_id,
        aes_app_id=app.aes_app_id,
        redirect_domain=redirect_domain,
    )
    order = wecom_client.create_online_order(suiteid=bind_input.wecom_suiteid, app_id=app.app_id)
    context["wecom"]["auditorderid"] = order.auditorderid
    context["wecom"]["auditorder_status"] = order.status
    context["wecom"]["order_created_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    _write_private_json(context_file, context)
    return JdyWecomBindResult(
        status="waiting_wecom_online_delay",
        context=context,
        next_check_at=now.replace(microsecond=0) + timedelta(minutes=5),
    )


def _recover_corp_from_owner_for_write(
    bind_input: JdyWecomBindInput,
    owner: Any,
) -> Optional[JdyCorpDeploy]:
    if not owner.can_update_corp_secret or not owner.owner_corp_id:
        return None
    acceptable_names = {
        value
        for value in {
            bind_input.enterprise_name.strip(),
            bind_input.enterprise_short_name.strip(),
        }
        if value
    }
    corp_name = owner.corp_name or bind_input.enterprise_short_name or bind_input.enterprise_name
    if corp_name not in acceptable_names:
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


def _save_development_info_and_confirm(
    wecom_client: WecomAdminClient,
    request: WecomSaveAppRequest,
) -> None:
    if _development_info_present(request.app.raw, request):
        return

    response = wecom_client.save_development_info_raw(request)
    try:
        corpapp = WecomAdminClient._extract_corpapp(response)
        if _development_info_present(corpapp, request):
            return
    except WecomAdminError:
        pass

    refreshed = wecom_client.resolve_unique_custom_app(
        suiteid=request.suiteid,
        enterprise_name=request.app.authcorp_name,
        suite_name=request.app.name,
    )
    if _development_info_present(refreshed.raw, request):
        return
    raise WecomAdminError(
        "WeCom development info save was not confirmed; response_shape=%s" % _json_shape(response)
    )


def _development_info_present(row: Dict[str, Any], request: WecomSaveAppRequest) -> bool:
    return (
        row.get("homeurl") == request.homeurl
        and row.get("callbackurl") == request.callbackurl
        and row.get("redirect_domain") == request.redirect_domain
        and bool(row.get("token"))
        and bool(row.get("aeskey"))
    )


def _json_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return ["list", len(value)]
    return type(value).__name__


def _write_private_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except PermissionError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
