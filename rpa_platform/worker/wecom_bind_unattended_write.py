import json
import os
import stat
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rpa_platform.domain.redaction import redact_context
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient
from rpa_platform.services.wecom_bind_service import JdyWecomBindService, WecomSecretGenerator
from rpa_platform.worker.wecom_bind_real_recovery import (
    BUSINESS_UNEXECUTABLE_REASONS,
    build_bind_input_from_context,
)
from scripts.dev.check_wecom_bind_real_readonly import CookieSourceError, run_readonly_preflight
from scripts.dev.run_wecom_bind_real_write import _start_bind_with_recoverable_context


PRIVATE_WEWORK_BIND_ENTRY_ID = "5e4ba3a09c38890006fbdf71"


REPO_ROOT = Path(__file__).resolve().parents[2]


def run_unattended_wecom_bind_write(
    task_id: str,
    context: Dict[str, Any],
    jdy_client: JdyAdminClient,
    wecom_client: WecomAdminClient,
    secret_generator: WecomSecretGenerator,
    preflight_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    context_file: Optional[Path] = None,
    lock_file: Optional[Path] = None,
    now: Optional[datetime] = None,
    wait_seconds: int = 300,
    login_recovery: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context_file = context_file or default_context_file(task_id)
    lock_file = lock_file or default_lock_file()

    existing = _load_json(context_file)
    if _is_success_context(existing):
        return _already_completed_result(existing, context_file, source_context=context)

    if not _acquire_lock(lock_file, task_id):
        return {
            "mode": "unattended_write",
            "status": "blocked",
            "reason": "write_already_running",
            "detail": "another unattended wecom bind write is running",
        }

    try:
        bind_input = build_bind_input_from_context(context)
        preflight_runner = preflight_runner or run_readonly_preflight
        try:
            preflight = preflight_runner(bind_input, jdy_client=jdy_client, wecom_client=wecom_client)
        except CookieSourceError as exc:
            return {
                "mode": "unattended_write",
                "status": "blocked",
                "reason": "missing_cookie_source",
                "detail": str(exc),
                "enterprise_name": bind_input.enterprise_name,
            }

        write_preflight, preflight_metadata = _preflight_for_write(preflight)
        if login_recovery and "login_recovery" not in preflight_metadata:
            preflight_metadata["login_recovery"] = login_recovery
        if write_preflight is None:
            return _blocked_preflight_result(preflight)

        if now is None:
            now = datetime.now()
        start_result = _start_bind_with_recoverable_context(
            bind_input=bind_input,
            jdy_client=jdy_client,
            wecom_client=wecom_client,
            secret_generator=secret_generator,
            context_file=context_file,
            now=now,
        )
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        service = JdyWecomBindService(
            jdy_client=jdy_client,
            wecom_client=wecom_client,
            secret_generator=secret_generator,
        )
        submit_result = service.submit_online_order(start_result.context)
        start_result.context["wecom"]["auditorder_status"] = submit_result.context["wecom"]["auditorder_status"]
        _write_private_json(context_file, start_result.context)
        return _success_result(
            write_preflight,
            context_file,
            start_result,
            submit_result,
            preflight_metadata,
            source_context=context,
        )
    except Exception as exc:
        return {
            "mode": "unattended_write",
            "status": "failed",
            "reason": "real_write_failed",
            "detail": str(exc),
        }
    finally:
        _release_lock(lock_file)


def default_context_file(task_id: str) -> Path:
    safe_task_id = "".join(char for char in task_id if char.isalnum() or char in {"-", "_"})
    return REPO_ROOT / ".local" / ("wecom-bind-real-write-%s.json" % safe_task_id)


def default_lock_file() -> Path:
    return REPO_ROOT / ".local" / "wecom-bind-write.lock"


def _success_result(
    preflight: Dict[str, Any],
    context_file: Path,
    start_result: Any,
    submit_result: Any,
    preflight_metadata: Optional[Dict[str, Any]] = None,
    source_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = {
        "mode": "unattended_write",
        "status": submit_result.status,
        "preflight": redact_context(preflight),
        "context_file": str(context_file),
        "wecom": {
            "auditorderid": start_result.context["wecom"].get("auditorderid", ""),
            "auditorder_status": submit_result.context["wecom"].get("auditorder_status"),
        },
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
    result.update(_jdy_writeback_fields(start_result.context, source_context or {}))
    for key, value in (preflight_metadata or {}).items():
        result[key] = redact_context(value)
    return result


def _preflight_for_write(preflight: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    status = preflight.get("status")
    if status in {"ok", "review"}:
        return preflight, {}
    if status in {"ready_for_real_bind", "manual_confirm_required"} and isinstance(preflight.get("preflight"), dict):
        metadata = {}
        if "login_recovery" in preflight:
            metadata["login_recovery"] = preflight["login_recovery"]
        return dict(preflight["preflight"]), metadata
    return None, {}


def _blocked_preflight_result(preflight: Dict[str, Any]) -> Dict[str, Any]:
    status = str(preflight.get("status") or "blocked")
    preflight_reason = str(preflight.get("reason") or "")
    if status == "blocked" and preflight_reason in BUSINESS_UNEXECUTABLE_REASONS:
        return {
            "mode": "unattended_write",
            "status": "business_unexecutable",
            "reason": preflight_reason,
            "preflight": redact_context(preflight),
        }
    result = {
        "mode": "unattended_write",
        "status": status if status in {"waiting_login", "login_recovery_notify_exhausted"} else "blocked",
        "reason": "preflight_not_ok",
        "preflight": redact_context(preflight),
    }
    if preflight.get("reason"):
        result["preflight_reason"] = preflight.get("reason")
    for key in (
        "detail",
        "manual_action",
        "expires_at",
        "notify_attempts",
        "remaining_notify_attempts",
        "next_action",
        "retry_after",
    ):
        if key in preflight:
            result[key] = redact_context(preflight[key])
    return result


def _already_completed_result(
    existing: Dict[str, Any],
    context_file: Path,
    source_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    wecom = existing.get("wecom") if isinstance(existing.get("wecom"), dict) else {}
    result = {
        "mode": "unattended_write",
        "status": "already_completed",
        "reason": "context_already_has_successful_auditorder",
        "context_file": str(context_file),
        "wecom": {
            "auditorderid": str(wecom.get("auditorderid", "")),
            "auditorder_status": wecom.get("auditorder_status"),
        },
        "context": redact_context(existing),
    }
    result.update(_jdy_writeback_fields(existing, source_context or {}))
    return result


def _jdy_writeback_fields(context: Dict[str, Any], source_context: Dict[str, Any]) -> Dict[str, str]:
    jdy = context.get("jdy") if isinstance(context.get("jdy"), dict) else {}
    wecom = context.get("wecom") if isinstance(context.get("wecom"), dict) else {}
    result = {
        "secret_corp_id": str(jdy.get("corp_secret_id") or ""),
        "home_url": str(wecom.get("homeurl") or ""),
        "webhook_url": str(wecom.get("callbackurl") or ""),
    }
    if _source_entry_id(source_context) == PRIVATE_WEWORK_BIND_ENTRY_ID:
        result["wx_token"] = str(wecom.get("token") or "")
        result["wx_key"] = str(wecom.get("encoding_aes_key") or "")
    return result


def _source_entry_id(context: Dict[str, Any]) -> str:
    for key in ("source_entry_id", "source_form_id", "entry_id", "form_id"):
        value = context.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _is_success_context(value: Dict[str, Any]) -> bool:
    wecom = value.get("wecom") if isinstance(value.get("wecom"), dict) else {}
    return wecom.get("auditorder_status") == 5


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_private_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except PermissionError:
        pass


def _acquire_lock(path: Path, task_id: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(task_id)
    return True


def _release_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
