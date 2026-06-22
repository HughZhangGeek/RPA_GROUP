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
from rpa_platform.worker.wecom_bind_real_recovery import build_bind_input_from_context
from scripts.dev.check_wecom_bind_real_readonly import CookieSourceError, run_readonly_preflight
from scripts.dev.run_wecom_bind_real_write import _start_bind_with_recoverable_context


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
) -> Dict[str, Any]:
    context_file = context_file or default_context_file(task_id)
    lock_file = lock_file or default_lock_file()

    existing = _load_json(context_file)
    if _is_success_context(existing):
        return _already_completed_result(existing, context_file)

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

        if preflight.get("status") not in {"ok", "review"}:
            return {
                "mode": "unattended_write",
                "status": "blocked",
                "reason": "preflight_not_ok",
                "preflight": redact_context(preflight),
            }

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
        return _success_result(preflight, context_file, start_result, submit_result)
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


def _success_result(preflight: Dict[str, Any], context_file: Path, start_result: Any, submit_result: Any) -> Dict[str, Any]:
    return {
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


def _already_completed_result(existing: Dict[str, Any], context_file: Path) -> Dict[str, Any]:
    wecom = existing.get("wecom") if isinstance(existing.get("wecom"), dict) else {}
    return {
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
