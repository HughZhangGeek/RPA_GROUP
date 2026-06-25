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
    deploy_id: str
    default_userid: str
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
    can_update_corp_secret: bool = False
    owner_corp_id: str = ""
    corp_name: str = ""
    existing_token: str = ""
    existing_encoding_aes_key: str = ""


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
        corp_id = plain_corp_id.strip()
        name = enterprise_name.strip()
        if corp_id:
            result = self.search_corp_deploy_list(corp_id)
            if len(result.rows) == 1:
                return result.rows[0]
            if len(result.rows) > 1:
                raise AmbiguousCorpDeployError("根据 CorpID 检索到多家企业，请联系管理员处理企业数据")
            raise MissingCorpDeployError("根据 CorpID 未检索到企业，请检查 CorpID 是否填写正确")

        if not name:
            raise MissingCorpDeployError("请填写 CorpID 或企业名称后重试")

        result = self.search_corp_deploy_list(name)
        exact_rows = [row for row in result.rows if row.name == name]
        if len(exact_rows) == 1:
            return exact_rows[0]
        if len(exact_rows) > 1:
            raise AmbiguousCorpDeployError("根据企业名称检索到多家企业，请补充 CorpID 后重试")
        raise MissingCorpDeployError("根据企业名称未检索到企业，请检查企业名称是否填写正确")

    def check_wework_owner(self, user_id: str, suite_id: int, suite_scenario: str) -> JdyOwnerCheckResult:
        payload = {"suite_id": suite_id, "suite_scenario": suite_scenario}
        normalized_user_id = user_id.strip()
        if normalized_user_id:
            payload["user_id"] = normalized_user_id
        data = self.transport.post_json("/api/fx_sa/wxwork/get_owner", payload)
        owner = data.get("owner")
        if not isinstance(owner, dict):
            owner = {}
        corp = data.get("corp")
        if not isinstance(corp, dict):
            corp = {}
        return JdyOwnerCheckResult(
            can_bind_corp_secret=bool(data.get("can_bind_corp_secret")),
            can_update_corp_secret=bool(data.get("can_update_corp_secret")),
            owner_corp_id=str(owner.get("corp_id", "")),
            corp_name=str(corp.get("name", "")),
            existing_token=str(corp.get("token", "")),
            existing_encoding_aes_key=str(corp.get("encoding_aes_key", "")),
        )

    def install_corp_deploy(self, request: JdyInstallRequest) -> JdyInstallResult:
        payload = {
            "corp_id": request.corp_id,
            "corp_name": request.corp_name,
            "token": request.token,
            "encoding_aes_key": request.encoding_aes_key,
            "suite_id": request.suite_id,
            "suite_scenario": request.suite_scenario,
        }
        tenant_id = request.tenant_id.strip()
        if tenant_id:
            payload["tenant_id"] = tenant_id
            payload["user_id"] = tenant_id
        data = self.transport.post_json("/api/fx_sa/wxwork/install_corp_deploy", payload)
        return JdyInstallResult(
            tenant_id=str(data.get("tenant_id", "")),
            owner_id=str(data.get("owner_id", "")),
        )

    @staticmethod
    def _parse_corp_row(row: Dict[str, Any]) -> JdyCorpDeploy:
        deploy_id = str(row.get("_id", ""))
        tenant_id = str(row.get("tenant_id", ""))
        return JdyCorpDeploy(
            deploy_id=deploy_id,
            default_userid=tenant_id,
            corp_id=str(row.get("corp_id", "")),
            name=str(row.get("name", "")),
            tenant_id=tenant_id,
            suite_name=str(row.get("suite_name", "")),
            integrate_suite_name=str(row.get("integrate_suite_name", "")),
            suite_id=int(row.get("suite_id") or 0),
            suite_scenario=str(row.get("suite_scenario", "")),
        )
