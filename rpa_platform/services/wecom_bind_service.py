from dataclasses import dataclass
from datetime import datetime, timedelta
import secrets
import string
from typing import Any, Dict, List, Optional, Protocol

from rpa_platform.integrations.jdy_admin_client import (
    JdyAdminClient,
    JdyAdminError,
    JdyInstallRequest,
    OwnerCannotBindError,
)
from rpa_platform.domain.redaction import mask_identifier
from rpa_platform.integrations.wecom_admin_client import (
    AmbiguousWecomAppError,
    MissingWecomAppError,
    WecomAdminClient,
    WecomAdminError,
    WecomCustomApp,
    WecomSaveAppRequest,
)


class WecomSecretGenerator(Protocol):
    def generate(self) -> Dict[str, str]:
        raise NotImplementedError


class RandomWecomSecretGenerator:
    def generate(self) -> Dict[str, str]:
        alphabet = string.ascii_letters + string.digits
        return {
            "token": "".join(secrets.choice(alphabet) for _ in range(32)),
            "encoding_aes_key": "".join(secrets.choice(alphabet) for _ in range(43)),
        }


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
    enterprise_short_name: str = ""


@dataclass(frozen=True)
class JdyWecomBindResult:
    status: str
    context: Dict[str, Any]
    next_check_at: Optional[datetime] = None


@dataclass(frozen=True)
class WecomLookupCandidate:
    source: str
    name: str


@dataclass(frozen=True)
class WecomAppResolution:
    app: WecomCustomApp
    candidates: List[WecomLookupCandidate]
    matched_sources: List[str]
    conflict_summary: List[Dict[str, str]]


class WecomAppCandidateLookupError(WecomAdminError):
    def __init__(
        self,
        reason: str,
        candidates: List[WecomLookupCandidate],
        matched_sources: Optional[List[str]] = None,
        conflict_summary: Optional[List[Dict[str, str]]] = None,
        detail: str = "",
    ):
        self.reason = reason
        self.candidates = list(candidates)
        self.matched_sources = list(matched_sources or [])
        self.conflict_summary = list(conflict_summary or [])
        super().__init__(detail or reason)


def build_wecom_lookup_candidates(
    request: JdyWecomBindInput,
    corp_name: str,
) -> List[WecomLookupCandidate]:
    candidates: List[WecomLookupCandidate] = []
    seen = set()
    for source, name in (
        ("jdy_corp_name", corp_name),
        ("incoming_enterprise_name", request.enterprise_name),
        ("enterprise_short_name", request.enterprise_short_name),
    ):
        clean_name = str(name or "").strip()
        if not clean_name or clean_name in seen:
            continue
        seen.add(clean_name)
        candidates.append(WecomLookupCandidate(source=source, name=clean_name))
    return candidates


def resolve_wecom_app_for_bind(
    wecom_client: WecomAdminClient,
    request: JdyWecomBindInput,
    corp_name: str,
) -> WecomAppResolution:
    candidates = build_wecom_lookup_candidates(request, corp_name)
    matches: List[tuple[WecomLookupCandidate, WecomCustomApp]] = []
    for candidate in candidates:
        try:
            app = wecom_client.resolve_unique_custom_app(
                suiteid=request.wecom_suiteid,
                enterprise_name=candidate.name,
                suite_name=request.suite_name,
            )
        except MissingWecomAppError:
            continue
        except AmbiguousWecomAppError as exc:
            raise WecomAppCandidateLookupError(
                reason="wecom_app_ambiguous",
                candidates=candidates,
                matched_sources=[candidate.source],
                detail=str(exc),
            ) from exc
        matches.append((candidate, app))

    if not matches:
        raise WecomAppCandidateLookupError(
            reason="wecom_app_not_found",
            candidates=candidates,
            detail="no candidate enterprise name matched a unique WeCom custom app",
        )

    app_ids = {app.app_id for _candidate, app in matches}
    conflict_summary = [
        {
            "source": candidate.source,
            "name": candidate.name,
            "app_id": mask_identifier(app.app_id),
            "authcorp_name": app.authcorp_name,
        }
        for candidate, app in matches
    ]
    if len(app_ids) > 1:
        raise WecomAppCandidateLookupError(
            reason="wecom_app_lookup_conflict",
            candidates=candidates,
            matched_sources=[candidate.source for candidate, _app in matches],
            conflict_summary=conflict_summary,
            detail="candidate enterprise names matched different WeCom custom apps",
        )

    return WecomAppResolution(
        app=matches[0][1],
        candidates=candidates,
        matched_sources=[candidate.source for candidate, _app in matches],
        conflict_summary=conflict_summary,
    )


def wecom_lookup_summary(resolution: Optional[WecomAppResolution]) -> Dict[str, Any]:
    if resolution is None:
        return {"lookup_source": "", "lookup_sources": [], "lookup_candidates": []}
    return {
        "lookup_source": resolution.matched_sources[0] if resolution.matched_sources else "",
        "lookup_sources": list(resolution.matched_sources),
        "lookup_candidates": [
            {"source": candidate.source, "name": candidate.name}
            for candidate in resolution.candidates
        ],
    }


def wecom_lookup_error_summary(error: WecomAppCandidateLookupError) -> Dict[str, Any]:
    return {
        "lookup_source": "",
        "lookup_sources": list(error.matched_sources),
        "lookup_candidates": [
            {"source": candidate.source, "name": candidate.name}
            for candidate in error.candidates
        ],
        "lookup_conflict": list(error.conflict_summary),
    }


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

    def start_bind(self, request: JdyWecomBindInput, now: Optional[datetime] = None) -> JdyWecomBindResult:
        if now is None:
            now = datetime.now()

        corp = self.jdy_client.resolve_unique_corp(
            request.plain_corp_id,
            request.enterprise_short_name or request.enterprise_name,
        )
        wecom_resolution = resolve_wecom_app_for_bind(self.wecom_client, request, corp.name)
        app = wecom_resolution.app
        secrets_payload = self.secret_generator.generate()
        homeurl = "https://wxwork.jiandaoyun.com/wxwork/%s/dashboard" % corp.corp_id
        callbackurl = "https://wxwork.jiandaoyun.com/wxwork/corp/%s/service" % corp.corp_id
        redirect_domain = "wxwork.jiandaoyun.com"

        owner = self.jdy_client.check_wework_owner(
            request.requested_user_id,
            suite_id=request.suite_id,
            suite_scenario=request.suite_scenario,
        )
        if not owner.can_bind_corp_secret and not owner.can_update_corp_secret:
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
        install_tenant_id = install.tenant_id.strip()
        install_owner_id = install.owner_id.strip()
        if not install_tenant_id or not install_owner_id:
            raise JdyAdminError("install_corp_deploy returned empty tenant_id or owner_id")
        bound_user_id = install_owner_id

        self.wecom_client.save_development_info(
            WecomSaveAppRequest(
                suiteid=request.wecom_suiteid,
                app=app,
                homeurl=homeurl,
                callbackurl=callbackurl,
                redirect_domain=redirect_domain,
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
            redirect_domain=redirect_domain,
        )
        order = self.wecom_client.create_online_order(suiteid=request.wecom_suiteid, app_id=app.app_id)

        context = {
            "jdy": {
                "corp_secret_id": corp.corp_id,
                "corp_name": corp.name,
                "original_tenant_id": corp.tenant_id,
                "requested_user_id": request.requested_user_id,
                "install_tenant_id": install_tenant_id,
                "install_owner_id": install_owner_id,
                "bound_user_id": bound_user_id,
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
                **wecom_lookup_summary(wecom_resolution),
                "homeurl": homeurl,
                "callbackurl": callbackurl,
                "redirect_domain": redirect_domain,
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
        auditorderid = str(context["wecom"]["auditorderid"])
        order = self.wecom_client.submit_online_order(auditorderid)
        return JdyWecomBindResult(
            status="success",
            context={"wecom": {"auditorder_status": order.status}},
        )
