import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rpa_platform.domain.default_flows import WECOM_APP_LAUNCH_FLOW_STEPS, WECOM_BIND_SERVICE_FLOW_STEPS
from rpa_platform.domain.redaction import redact_context
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyAdminTransport
from rpa_platform.integrations.wecom_admin_client import WecomAdminClient, WecomAdminTransport
from rpa_platform.services.wecom_bind_service import FixedWecomSecretGenerator, JdyWecomBindService
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.hybrid_runner import HybridFlowRunner
from rpa_platform.worker.scheduler import TaskScheduler
from rpa_platform.worker.wecom_bind_runner import WecomBindServiceRunner
from rpa_platform.worker.wecom_rpa import FakeWecomRpa


class FakeJdyAdminTransport(JdyAdminTransport):
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"path": path, "payload": dict(payload)})
        if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
            return {
                "has_more": False,
                "corp_deploy_list": [
                    {
                        "corp_id": "corp-secret-dryrun-001",
                        "name": "Mac Dry Run 客户",
                        "tenant_id": "",
                        "suite_name": "简道云",
                        "integrate_suite_name": "简道云",
                        "suite_id": 1,
                        "suite_scenario": "main",
                    }
                ],
            }
        if path == "/api/fx_sa/wxwork/get_owner":
            return {"can_bind_corp_secret": True}
        if path == "/api/fx_sa/wxwork/install_corp_deploy":
            return {"tenant_id": payload["tenant_id"], "owner_id": payload["user_id"]}
        raise ValueError("Unsupported fake Jiandaoyun admin path: %s" % path)


class FakeServiceJdyAdminTransport(JdyAdminTransport):
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"path": path, "payload": dict(payload)})
        if path == "/api/fx_sa/wxwork/get_corp_deploy_list":
            return {
                "has_more": False,
                "corp_deploy_list": [
                    {
                        "corp_id": "corp-secret",
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
        if path == "/api/fx_sa/wxwork/install_corp_deploy":
            return {"tenant_id": payload["tenant_id"], "owner_id": "user-1"}
        raise ValueError("Unsupported fake Jiandaoyun service path: %s" % path)


class FakeServiceWecomAdminTransport(WecomAdminTransport):
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def get_json(
        self,
        path: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        self.calls.append({"method": "GET", "path": path, "params": dict(params), "headers": dict(headers)})
        if path == "/wwopen/developer/customApp/tpl/app/list":
            return {
                "data": {
                    "corpapp": [
                        {
                            "app_id": "app-1",
                            "authcorp_name": "上海测试客户",
                            "name": "简道云",
                            "logo": "logo-url",
                            "description": "desc",
                            "customized_app_status": 0,
                            "sdk_auth": {"aes_app_id": "aes-app-1"},
                        }
                    ]
                }
            }
        raise ValueError("Unsupported fake WeCom service GET path: %s" % path)

    def post_json(
        self,
        path: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        self.calls.append({"method": "POST", "path": path, "payload": dict(payload), "headers": dict(headers)})
        if path == "/wwopen/developer/customApp/tpl/corpApp":
            return {"data": {"corpapp": payload["corpapp"]}}
        if path == "/wwopen/api/customApp/privilege/getCustomizedAppPrivilege":
            return {
                "data": {
                    "privilege_list": [
                        {"id": 310000, "b_check": False},
                        {"id": 310001, "b_check": False},
                        {"id": 310002, "b_check": False},
                        {"id": 310100, "b_check": False},
                        {"id": 10006, "b_check": False},
                        {"id": 10010, "b_check": False},
                        {"id": 42, "b_check": False},
                    ]
                }
            }
        if path == "/wwopen/api/customApp/privilege/setCustomizedAppPrivilege":
            return {"data": {"privilege_list": payload["privilege_list"]}}
        if path == "/wwopen/api/customApp/price/GetStandardPriceInfoForCA":
            return {"data": {"base_price_info": {}}}
        if path == "/wwopen/api/customApp/price/SetStandardPriceInfoForCA":
            return {"data": {"is_already_set_try_info": True, "base_price_info": payload["base_price_info"]}}
        if path == "/wwopen/developer/order/add":
            return {
                "data": {
                    "auditorder": {
                        "auditorderid": "order-1",
                        "corpappid": "app-1",
                        "authcorp_name": "上海测试客户",
                        "status": 1,
                    }
                }
            }
        if path == "/wwopen/developer/order/set":
            return {
                "data": {
                    "auditorder": {
                        "auditorderid": payload["auditorder"]["auditorderid"],
                        "corpappid": "app-1",
                        "authcorp_name": "上海测试客户",
                        "status": 5,
                    }
                }
            }
        raise ValueError("Unsupported fake WeCom service POST path: %s" % path)


def default_dryrun_db_path() -> Path:
    return REPO_ROOT / ".local" / "platform-dryrun.db"


def prepare_dryrun(db_path: Optional[str] = None, reset: bool = False) -> Dict[str, Any]:
    if db_path is None:
        db_path = str(default_dryrun_db_path())
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if reset:
        _remove_sqlite_files(db_file)

    store = SQLiteStore(str(db_file))
    store.init_schema()

    team_id = store.create_team("Mac dry-run 团队", notification_enabled=False)
    flow_id = store.create_flow_template(team_id, "企微代开发应用上线 dry-run", "Mac 本地 fake 链路")
    flow_version_id = store.create_flow_version(
        flow_id,
        steps=WECOM_APP_LAUNCH_FLOW_STEPS,
        created_by="dry-run",
    )
    store.publish_flow_version(flow_id, flow_version_id)
    robot_id = store.register_robot(
        name="mac-dryrun-robot",
        host="mac-local",
        browser_profile_path="/tmp/rpa-platform-dryrun-browser-profile",
        capabilities={"wecom": True, "browser_use": "fake"},
    )

    task_result = store.create_task_from_published_flow(
        team_id=team_id,
        flow_template_id=flow_id,
        enterprise_name="Mac Dry Run 客户",
        corp_id="ww-dryrun-corp",
        source_user_id="dryrun-user-001",
        idempotency_key="wecom_app_launch:ww-dryrun-corp:dryrun-user-001",
        payload={
            "user_id": "dryrun-user-001",
            "企业客户名称": "Mac Dry Run 客户",
            "企业微信明文 CorpID": "ww-dryrun-corp",
        },
    )

    return {
        "db_path": str(db_file),
        "team_id": team_id,
        "flow_template_id": flow_id,
        "flow_version_id": flow_version_id,
        "robot_id": robot_id,
        "task_id": task_result.task_id,
        "created": task_result.created,
        "task_detail": _redact_task_detail(store.get_task_detail(task_result.task_id)),
    }


def run_worker_once(
    db_path: Optional[str] = None,
    robot_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if db_path is None:
        db_path = str(default_dryrun_db_path())
    store = SQLiteStore(str(db_path))
    robot_id = _select_robot_id(store, robot_id)
    transport = FakeJdyAdminTransport()
    runner = HybridFlowRunner(
        store=store,
        jdy_client=JdyAdminClient(transport),
        wecom_rpa=FakeWecomRpa(),
    )
    scheduler_result = TaskScheduler(store).run_once(
        robot_id,
        runner,
        now=now or datetime(2026, 6, 15, 10, 0, 0),
    )
    task_id = scheduler_result.get("task_id")
    return {
        "db_path": str(db_path),
        "robot_id": robot_id,
        "scheduler_result": scheduler_result,
        "runner_result": scheduler_result.get("runner_result"),
        "jdy_admin_calls": _redact_jdy_calls(transport.calls),
        "task_detail": _redact_task_detail(store.get_task_detail(task_id)) if task_id else None,
    }


def run_dryrun(db_path: Optional[str] = None, reset: bool = True) -> Dict[str, Any]:
    prepared = prepare_dryrun(db_path=db_path, reset=reset)
    worker_result = run_worker_once(
        db_path=prepared["db_path"],
        robot_id=prepared["robot_id"],
        now=datetime(2026, 6, 15, 10, 0, 0),
    )
    result = dict(prepared)
    result.update(worker_result)
    result.update(
        {
            "team_id": prepared["team_id"],
            "flow_template_id": prepared["flow_template_id"],
            "flow_version_id": prepared["flow_version_id"],
            "task_id": prepared["task_id"],
            "created": prepared["created"],
        }
    )
    return result


def _prepare_wecom_bind_service_dryrun(db_path: Optional[str] = None, reset: bool = False) -> Dict[str, Any]:
    if db_path is None:
        db_path = str(default_dryrun_db_path())
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if reset:
        _remove_sqlite_files(db_file)

    store = SQLiteStore(str(db_file))
    store.init_schema()

    team_id = store.create_team("企微绑定接口服务 dry-run 团队", notification_enabled=False)
    flow_id = store.create_flow_template(team_id, "企微绑定接口服务 dry-run", "Mac 本地 fake service 链路")
    flow_version_id = store.create_flow_version(
        flow_id,
        steps=WECOM_BIND_SERVICE_FLOW_STEPS,
        created_by="dry-run",
    )
    store.publish_flow_version(flow_id, flow_version_id)
    robot_id = store.register_robot(
        name="mac-service-dryrun-robot",
        host="mac-local",
        browser_profile_path="/tmp/rpa-platform-service-dryrun-browser-profile",
        capabilities={"wecom_bind_service": True},
    )

    task_result = store.create_task_from_published_flow(
        team_id=team_id,
        flow_template_id=flow_id,
        enterprise_name="上海测试客户",
        corp_id="ww001",
        source_user_id="user-1",
        idempotency_key="wecom_bind_service:ww001:user-1",
        payload={
            "user_id": "user-1",
            "企业客户名称": "上海测试客户",
            "企业微信明文 CorpID": "ww001",
        },
    )

    return {
        "db_path": str(db_file),
        "team_id": team_id,
        "flow_template_id": flow_id,
        "flow_version_id": flow_version_id,
        "robot_id": robot_id,
        "task_id": task_result.task_id,
        "created": task_result.created,
        "task_detail": _redact_task_detail(store.get_task_detail(task_result.task_id)),
    }


def run_wecom_bind_service_dryrun(db_path: Optional[str] = None, reset: bool = True) -> Dict[str, Any]:
    prepared = _prepare_wecom_bind_service_dryrun(db_path=db_path, reset=reset)
    store = SQLiteStore(prepared["db_path"])
    runner = WecomBindServiceRunner(
        store=store,
        service=JdyWecomBindService(
            jdy_client=JdyAdminClient(FakeServiceJdyAdminTransport()),
            wecom_client=WecomAdminClient(FakeServiceWecomAdminTransport()),
            secret_generator=FixedWecomSecretGenerator(token="token-secret", encoding_aes_key="aes-secret"),
        ),
    )
    scheduler_result = TaskScheduler(store).run_once(
        prepared["robot_id"],
        runner,
        now=datetime(2026, 6, 16, 10, 0, 0),
    )
    task_id = scheduler_result.get("task_id") or prepared["task_id"]
    result = dict(prepared)
    result.update(
        {
            "scheduler_result": scheduler_result,
            "runner_result": scheduler_result.get("runner_result"),
            "task_detail": _redact_task_detail(store.get_task_detail(task_id)),
        }
    )
    return result


def _remove_sqlite_files(db_file: Path) -> None:
    for path in (db_file, Path(str(db_file) + "-wal"), Path(str(db_file) + "-shm")):
        if path.exists():
            path.unlink()


def _select_robot_id(store: SQLiteStore, robot_id: Optional[str]) -> str:
    if robot_id:
        return robot_id
    with store._connect() as conn:
        row = conn.execute(
            "SELECT id FROM robots ORDER BY created_at ASC, id ASC LIMIT 1"
        ).fetchone()
    if row is None:
        raise RuntimeError("No dry-run robot found. Run run_platform_dryrun.py --prepare-only first.")
    return row["id"]


def _redact_task_detail(detail: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(detail)
    redacted["payload"] = redact_context(redacted.get("payload", {}))
    redacted["runtime_context"] = redact_context(redacted.get("runtime_context", {}))
    redacted["steps"] = [_redact_step(step) for step in redacted.get("steps", [])]
    redacted["manual_actions"] = redact_context(redacted.get("manual_actions", []))
    redacted.pop("payload_json", None)
    redacted.pop("runtime_context_json", None)
    redacted.pop("flow_version_snapshot_json", None)
    return redacted


def _redact_step(step: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(step)
    for key in ("input_json", "output_json"):
        redacted[key] = _redact_json_text(redacted.get(key, "{}"))
    return redacted


def _redact_json_text(value: str) -> str:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return value
    return json.dumps(redact_context(parsed), ensure_ascii=False)


def _redact_jdy_calls(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "path": call["path"],
            "payload": redact_context(call.get("payload", {})),
        }
        for call in calls
    ]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RPA platform fake hybrid flow locally.")
    parser.add_argument(
        "--mode",
        choices=["hybrid", "wecom-bind-service"],
        default="hybrid",
        help="Dry-run mode. Defaults to hybrid.",
    )
    parser.add_argument("--db-path", default=None, help="SQLite path. Defaults to .local/platform-dryrun.db.")
    parser.add_argument("--keep-existing", action="store_true", help="Do not reset the dry-run SQLite files first.")
    parser.add_argument("--prepare-only", action="store_true", help="Initialize the dry-run DB without running worker once.")
    args = parser.parse_args(argv)

    if args.mode == "wecom-bind-service":
        if args.prepare_only:
            result = _prepare_wecom_bind_service_dryrun(db_path=args.db_path, reset=not args.keep_existing)
        else:
            result = run_wecom_bind_service_dryrun(db_path=args.db_path, reset=not args.keep_existing)
    elif args.prepare_only:
        result = prepare_dryrun(db_path=args.db_path, reset=not args.keep_existing)
    else:
        result = run_dryrun(db_path=args.db_path, reset=not args.keep_existing)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
