from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol


WECOM_ALLOWED_DOMAINS = ["open.work.weixin.qq.com"]


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


@dataclass(frozen=True)
class BrowserUseTaskRequest:
    task_template: str
    prompt: str
    allowed_domains: List[str]
    browser_profile: str
    use_cloud: bool = False

    def __post_init__(self) -> None:
        if self.use_cloud:
            raise ValueError("Browser Use Cloud is not allowed for WeCom automation")
        if self.allowed_domains != WECOM_ALLOWED_DOMAINS:
            raise ValueError("WeCom browser automation must be scoped to open.work.weixin.qq.com")
        if not self.browser_profile:
            raise ValueError("browser_profile is required")


class BrowserUseRunner(Protocol):
    def run_task(self, request: BrowserUseTaskRequest) -> Dict[str, Any]:
        raise NotImplementedError


class BrowserUseWecomRpa:
    def __init__(self, runner: BrowserUseRunner, browser_profile: str):
        self.runner = runner
        self.browser_profile = browser_profile

    def configure_custom_app(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        request = BrowserUseTaskRequest(
            task_template="wecom_configure_app_v1",
            prompt=_render_configure_app_prompt(task, context),
            allowed_domains=WECOM_ALLOWED_DOMAINS,
            browser_profile=self.browser_profile,
        )
        return self.runner.run_task(request)

    def submit_review(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        request = BrowserUseTaskRequest(
            task_template="wecom_submit_review_v1",
            prompt=_render_submit_review_prompt(task, context),
            allowed_domains=WECOM_ALLOWED_DOMAINS,
            browser_profile=self.browser_profile,
        )
        return self.runner.run_task(request)

    def check_review_status(self, task: Dict[str, Any], context: Dict[str, Any]) -> WecomReviewStatus:
        request = BrowserUseTaskRequest(
            task_template="wecom_check_review_status_v1",
            prompt=_render_check_review_status_prompt(task, context),
            allowed_domains=WECOM_ALLOWED_DOMAINS,
            browser_profile=self.browser_profile,
        )
        result = self.runner.run_task(request)
        return WecomReviewStatus(result.get("review_status") or WecomReviewStatus.UNKNOWN.value)

    def submit_online(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        request = BrowserUseTaskRequest(
            task_template="wecom_submit_online_v1",
            prompt=_render_submit_online_prompt(task, context),
            allowed_domains=WECOM_ALLOWED_DOMAINS,
            browser_profile=self.browser_profile,
        )
        return self.runner.run_task(request)


class FakeBrowserUseRunner:
    def __init__(self, results: Optional[List[Dict[str, Any]]] = None):
        self.results = list(results or [])
        self.requests: List[BrowserUseTaskRequest] = []

    def run_task(self, request: BrowserUseTaskRequest) -> Dict[str, Any]:
        self.requests.append(request)
        if self.results:
            return dict(self.results.pop(0))
        return {"review_status": WecomReviewStatus.UNKNOWN.value}


class FakeWecomRpa:
    def __init__(
        self,
        configure_result: Optional[Dict[str, Any]] = None,
        review_statuses: Optional[List[WecomReviewStatus]] = None,
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


def _render_configure_app_prompt(task: Dict[str, Any], context: Dict[str, Any]) -> str:
    jdy = context.get("jdy", {})
    wecom = context.get("wecom", {})
    enterprise_name = task.get("enterprise_name", "")
    suite_name = jdy.get("suite_name", "简道云")
    template_id = jdy.get("wecom_template_id", "")
    return "\n".join(
        [
            "你正在操作已登录的企业微信开发者后台。",
            "ONLY 在 open.work.weixin.qq.com 域名内操作。",
            "NEVER 使用 Browser Use Cloud。",
            "NEVER 修改与本任务无关的应用、企业、权限项。",
            "如果页面要求重新登录、扫码、验证码或企业匹配不唯一，立即停止并返回 manual_required。",
            "目标：为企业「%s」配置模板「%s」的代开发应用。" % (enterprise_name, suite_name),
            "模板 ID：%s。" % template_id,
            "应用主页：%s。" % wecom.get("homeurl", ""),
            "可信域名：%s。" % wecom.get("redirect_domain", ""),
            "回调 URL：%s。" % wecom.get("callbackurl", ""),
            "开启试用 60 天，并开启限时额外试用 7 天。",
            "完成后返回 JSON：status、page_state、token、encoding_aes_key、review_status。",
        ]
    )


def _render_submit_review_prompt(task: Dict[str, Any], context: Dict[str, Any]) -> str:
    return _render_wecom_step_prompt(
        task,
        "确认当前企业的代开发应用配置无误后，点击提交审核；不要执行最终上线。",
    )


def _render_check_review_status_prompt(task: Dict[str, Any], context: Dict[str, Any]) -> str:
    return _render_wecom_step_prompt(
        task,
        "查看代开发应用审核详情页，返回当前审核状态，只读取状态，不修改配置。",
    )


def _render_submit_online_prompt(task: Dict[str, Any], context: Dict[str, Any]) -> str:
    return _render_wecom_step_prompt(
        task,
        "仅当页面状态为待上线时，点击右侧提交上线，并返回上线提交结果。",
    )


def _render_wecom_step_prompt(task: Dict[str, Any], instruction: str) -> str:
    return "\n".join(
        [
            "你正在操作已登录的企业微信开发者后台。",
            "ONLY 在 open.work.weixin.qq.com 域名内操作。",
            "NEVER 使用 Browser Use Cloud。",
            "如果页面要求重新登录、扫码、验证码或企业匹配不唯一，立即停止并返回 manual_required。",
            "企业名称：%s。" % task.get("enterprise_name", ""),
            instruction,
            "完成后返回 JSON，不要输出额外说明。",
        ]
    )
