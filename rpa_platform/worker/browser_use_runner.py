import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from rpa_platform.worker.wecom_rpa import BrowserUseTaskRequest


class BrowserUseRunnerError(RuntimeError):
    """Raised when browser-use cannot return a structured task result."""


@dataclass(frozen=True)
class BrowserUseAgentTask:
    task: str
    allowed_domains: List[str]
    browser_profile: str
    use_cloud: bool
    metadata: Dict[str, Any]


class LocalBrowserUseRunner:
    """Adapter boundary for a local/self-hosted browser-use agent."""

    def __init__(self, agent_factory: Callable[[BrowserUseAgentTask], Any]):
        self.agent_factory = agent_factory

    def run_task(self, request: BrowserUseTaskRequest) -> Dict[str, Any]:
        try:
            agent_task = BrowserUseAgentTask(
                task=_build_agent_task(request),
                allowed_domains=list(request.allowed_domains),
                browser_profile=request.browser_profile,
                use_cloud=False,
                metadata={"task_template": request.task_template},
            )
            agent = self.agent_factory(agent_task)
            raw_result = _run_agent(agent)
            return _normalize_result(raw_result)
        except Exception as exc:
            return _error_result(exc)


def _build_agent_task(request: BrowserUseTaskRequest) -> str:
    return "\n".join(
        [
            request.prompt,
            "",
            "Return only a JSON object. Do not include markdown fences or extra prose.",
        ]
    )


def _run_agent(agent: Any) -> Any:
    runner = getattr(agent, "run", None)
    if callable(runner):
        return _resolve_awaitable(runner())
    if callable(agent):
        return _resolve_awaitable(agent())
    return _resolve_awaitable(agent)


def _resolve_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise BrowserUseRunnerError("Cannot wait for async browser-use result inside a running event loop")


def _normalize_result(raw_result: Any) -> Dict[str, Any]:
    result = _extract_final_result(raw_result)
    if isinstance(result, dict):
        return dict(result)
    if isinstance(result, bytes):
        result = result.decode("utf-8")
    if isinstance(result, str):
        return _parse_json_object(result)
    raise BrowserUseRunnerError("browser-use result must be a structured dict or JSON object")


def _extract_final_result(raw_result: Any) -> Any:
    final_result = getattr(raw_result, "final_result", None)
    if callable(final_result):
        return final_result()
    return raw_result


def _parse_json_object(value: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BrowserUseRunnerError("browser-use result must be a structured dict or JSON object") from exc
    if not isinstance(parsed, dict):
        raise BrowserUseRunnerError("browser-use result must be a structured dict or JSON object")
    return parsed


def _error_result(exc: Exception) -> Dict[str, Any]:
    return {
        "status": "error",
        "error_type": exc.__class__.__name__,
        "error_detail": str(exc),
    }
