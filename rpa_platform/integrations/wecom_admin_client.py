import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol


class WecomAdminTransport(Protocol):
    def get_json(
        self,
        path: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def post_json(
        self,
        path: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        raise NotImplementedError


class WecomAdminError(RuntimeError):
    """Base error for WeCom developer admin API failures."""


class MissingWecomAppError(WecomAdminError):
    """Raised when no custom app matches the expected enterprise and suite."""


class AmbiguousWecomAppError(WecomAdminError):
    """Raised when more than one custom app matches the expected contract."""


class RetryableWecomOrderError(WecomAdminError):
    """Raised for transient online order failures that should be retried."""


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
    TARGET_PRIVILEGE_IDS = {310000, 310001, 310002, 310100, 10006, 10010}

    def __init__(self, transport: WecomAdminTransport):
        self.transport = transport

    def resolve_unique_custom_app(
        self,
        suiteid: int,
        enterprise_name: str,
        suite_name: str,
    ) -> WecomCustomApp:
        data = self.transport.get_json(
            "/wwopen/developer/customApp/tpl/app/list",
            {
                "lang": "zh_CN",
                "ajax": 1,
                "f": "json",
                "suiteid": str(suiteid),
                "scene": 1,
                "corp_name_keyword": enterprise_name,
                "offset": 0,
                "limit": 10,
                "random": 0,
            },
            self._headers("/sass/customApp/tpl/info", "50"),
        )
        matches = [
            row
            for row in self._extract_corpapp_rows(data)
            if str(row.get("authcorp_name", "")) == enterprise_name
            and str(row.get("name", "")) == suite_name
        ]
        if not matches:
            raise MissingWecomAppError("no custom app matched authcorp name and app name")
        if len(matches) > 1:
            raise AmbiguousWecomAppError("authcorp name and app name matched multiple custom apps")
        return self._parse_custom_app(matches[0])

    def save_development_info(self, request: WecomSaveAppRequest) -> Dict[str, Any]:
        corpapp = copy.deepcopy(dict(request.app.raw))
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
        response = self.transport.post_json(
            "/wwopen/developer/customApp/tpl/corpApp",
            {"suiteid": str(request.suiteid), "corpapp": corpapp},
            self._headers("/sass/customApp/app/create", "50"),
        )
        return self._extract_corpapp(response)

    def set_target_privileges(self, suiteid: int, app_id: str) -> List[Dict[str, Any]]:
        headers = self._headers("/sass/customApp/app/detail", "50,51")
        request_payload = {"thirdapp_id": [app_id], "suiteid": str(suiteid)}
        data = self.transport.post_json(
            "/wwopen/api/customApp/privilege/getCustomizedAppPrivilege",
            request_payload,
            headers,
        )
        patched = []
        for item in self._extract_required_privilege_list(data):
            privilege = copy.deepcopy(item)
            if int(privilege.get("id") or 0) in self.TARGET_PRIVILEGE_IDS:
                privilege["b_check"] = True
            patched.append(privilege)
        response = self.transport.post_json(
            "/wwopen/api/customApp/privilege/setCustomizedAppPrivilege",
            {
                "thirdapp_id": [app_id],
                "suiteid": str(suiteid),
                "privilege_list": patched,
            },
            headers,
        )
        return self._extract_required_privilege_list(response)

    def set_trial_rule(self, app_id: str) -> Dict[str, Any]:
        headers = self._headers("/sass/customApp/app/detail", "50,51")
        self.transport.post_json(
            "/wwopen/api/customApp/price/GetStandardPriceInfoForCA",
            {"corpappid": app_id},
            headers,
        )
        response = self.transport.post_json(
            "/wwopen/api/customApp/price/SetStandardPriceInfoForCA",
            {
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
            },
            headers,
        )
        self._validate_trial_rule_response(response)
        return response

    def set_sso_redirect_domain(
        self,
        suiteid: int,
        app_id: str,
        aes_app_id: str,
        redirect_domain: str,
    ) -> Dict[str, Any]:
        response = self.transport.post_json(
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
            self._headers("/sass/customApp/app/detail/sso", "50"),
        )
        corpapp = self._extract_corpapp(response)
        self._validate_sso_response(corpapp, aes_app_id, redirect_domain)
        return corpapp

    def create_online_order(self, suiteid: int, app_id: str) -> WecomOnlineOrder:
        data = self.transport.post_json(
            "/wwopen/developer/order/add",
            {
                "auditorder": {"suiteid": suiteid, "corpappid": app_id},
                "skipNotice": False,
            },
            self._headers("/sass/customApp/deploy/list", "51"),
        )
        return self._parse_online_order(self._extract_order(data))

    def submit_online_order(self, auditorderid: str) -> WecomOnlineOrder:
        data = self.transport.post_json(
            "/wwopen/developer/order/set",
            {"auditorder": {"auditorderid": auditorderid, "status": 5}},
            self._headers("/sass/customApp/deploy/detail", "51"),
        )
        return self._parse_online_order(self._extract_order(data))

    @staticmethod
    def _headers(page: str, perm: str) -> Dict[str, str]:
        return {"x-wecom-developer-page": page, "x-wecom-developer-perm": perm}

    @staticmethod
    def _extract_corpapp_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        nested = data.get("data")
        if isinstance(nested, dict):
            value = nested.get("corpapp")
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _extract_corpapp(data: Dict[str, Any]) -> Dict[str, Any]:
        nested = data.get("data")
        if isinstance(nested, dict):
            value = nested.get("corpapp")
            if isinstance(value, dict):
                return value
        raise WecomAdminError("WeCom admin response missing data.corpapp")

    @staticmethod
    def _extract_privilege_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        nested = data.get("data")
        if isinstance(nested, dict):
            value = nested.get("privilege_list")
            if isinstance(value, list):
                return value
        value = data.get("privilege_list")
        if isinstance(value, list):
            return value
        return []

    @staticmethod
    def _extract_required_privilege_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        value = WecomAdminClient._extract_privilege_list(data)
        if value:
            return value
        raise WecomAdminError("WeCom admin response missing data.privilege_list")

    @staticmethod
    def _extract_order(data: Dict[str, Any]) -> Dict[str, Any]:
        nested = data.get("data")
        if isinstance(nested, dict):
            value = nested.get("auditorder")
            if isinstance(value, dict):
                return value
        raise WecomAdminError("WeCom admin response missing data.auditorder")

    @staticmethod
    def _validate_trial_rule_response(data: Dict[str, Any]) -> None:
        nested = data.get("data")
        if not isinstance(nested, dict) or not nested.get("is_already_set_try_info"):
            raise WecomAdminError("WeCom trial rule response missing confirmation")
        base_price_info = nested.get("base_price_info")
        if not isinstance(base_price_info, dict):
            raise WecomAdminError("WeCom trial rule response missing base_price_info")
        try_rule_info = base_price_info.get("try_rule_info")
        if not isinstance(try_rule_info, dict):
            raise WecomAdminError("WeCom trial rule response missing try_rule_info")
        if try_rule_info.get("try_time") != 60 or try_rule_info.get("second_try_time") != 15:
            raise WecomAdminError("WeCom trial rule response did not confirm requested trial window")

    @staticmethod
    def _validate_sso_response(corpapp: Dict[str, Any], aes_app_id: str, redirect_domain: str) -> None:
        sdk_auth = corpapp.get("sdk_auth")
        if not isinstance(sdk_auth, dict):
            raise WecomAdminError("WeCom SSO response missing sdk_auth")
        if sdk_auth.get("aes_app_id") != aes_app_id:
            raise WecomAdminError("WeCom SSO response did not confirm aes_app_id")
        if sdk_auth.get("redirect_domain2") != redirect_domain:
            raise WecomAdminError("WeCom SSO response did not confirm redirect_domain2")

    @staticmethod
    def _parse_custom_app(row: Dict[str, Any]) -> WecomCustomApp:
        sdk_auth = row.get("sdk_auth")
        if not isinstance(sdk_auth, dict):
            sdk_auth = {}
        return WecomCustomApp(
            app_id=str(row.get("app_id", "")),
            authcorp_name=str(row.get("authcorp_name", "")),
            name=str(row.get("name", "")),
            logo=str(row.get("logo", "")),
            description=str(row.get("description", "")),
            customized_app_status=int(row.get("customized_app_status") or 0),
            aes_app_id=str(sdk_auth.get("aes_app_id", "")),
            raw=copy.deepcopy(row),
        )

    @staticmethod
    def _parse_online_order(row: Dict[str, Any]) -> WecomOnlineOrder:
        return WecomOnlineOrder(
            auditorderid=str(row.get("auditorderid", "")),
            corpappid=str(row.get("corpappid", "")),
            authcorp_name=str(row.get("authcorp_name", "")),
            status=int(row.get("status") or 0),
        )
