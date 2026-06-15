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

    def search_corp_deploy_list(
        self,
        filter_text: str,
        skip: int = 0,
        limit: int = 10,
    ) -> JdyCorpDeploySearchResult:
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
        return JdyInstallResult(
            tenant_id=str(data.get("tenant_id", "")),
            owner_id=str(data.get("owner_id", "")),
        )

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
