import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.integrations.jdy_admin_client import JdyAdminClient, JdyInstallRequest, OwnerCannotBindError
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.wecom_rpa import WecomReviewStatus, WecomRpa


class HybridFlowRunner:
    def __init__(self, store: SQLiteStore, jdy_client: JdyAdminClient, wecom_rpa: WecomRpa):
        self.store = store
        self.jdy_client = jdy_client
        self.wecom_rpa = wecom_rpa

    def run_claimed_task(
        self,
        task_id: str,
        robot_id: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        current = TaskStatus(self.store.get_task(task_id)["status"])
        if current == TaskStatus.WAITING_WECOM_REVIEW:
            return self._check_review(task_id, robot_id, now)
        if current == TaskStatus.READY_TO_ONLINE:
            return self._submit_online(task_id, robot_id)

        self.store.set_task_status(task_id, TaskStatus.RUNNING, assigned_robot_id=robot_id)
        task = self.store.get_task(task_id)
        for step in _snapshot_steps(task):
            if not step.get("enabled", True):
                continue
            self.store.set_task_current_step(task_id, step["key"])
            action = step["action"]
            if action == "jdy_resolve_corp":
                self._jdy_resolve_corp(task_id, step)
            elif action == "derive_wecom_urls":
                self._derive_wecom_urls(task_id, step)
            elif action == "wecom_configure_app":
                pause_result = self._wecom_configure_app(task_id, robot_id, step)
                if pause_result is not None:
                    return pause_result
            elif action == "jdy_check_owner":
                self._jdy_check_owner(task_id, step)
            elif action == "jdy_install_bind":
                self._jdy_install_bind(task_id, step)
            elif action == "wecom_submit_review":
                return self._submit_review(task_id, robot_id, step, now)
            elif action in {"wecom_wait_review", "wecom_submit_online"}:
                continue
            else:
                raise ValueError("Unsupported hybrid action: %s" % action)
        self.store.set_task_status(task_id, TaskStatus.SUCCESS, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.SUCCESS.value}

    def _jdy_resolve_corp(self, task_id: str, step: Dict[str, Any]) -> None:
        task = self.store.get_task(task_id)
        row = self.jdy_client.resolve_unique_corp(task["corp_id"], task["enterprise_name"])
        output = {
            "corp_secret_id": row.corp_id,
            "corp_name": row.name,
            "tenant_id": row.tenant_id,
            "original_tenant_id": row.tenant_id,
            "suite_id": row.suite_id,
            "suite_scenario": row.suite_scenario,
            "suite_name": row.suite_name,
            "integrate_suite_name": row.integrate_suite_name,
        }
        self.store.merge_task_context(task_id, {"jdy": output})
        self.store.append_task_step(task_id, step["key"], step["name"], "success", output_data=output)

    def _derive_wecom_urls(self, task_id: str, step: Dict[str, Any]) -> None:
        context = self.store.get_task_context(task_id)
        corp_secret_id = context["jdy"]["corp_secret_id"]
        output = {
            "homeurl": "https://wxwork.jiandaoyun.com/wxwork/%s/dashboard" % corp_secret_id,
            "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/%s/service" % corp_secret_id,
            "redirect_domain": "wxwork.jiandaoyun.com",
        }
        self.store.merge_task_context(task_id, {"wecom": output})
        self.store.append_task_step(task_id, step["key"], step["name"], "success", output_data=output)

    def _wecom_configure_app(
        self,
        task_id: str,
        robot_id: str,
        step: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.wecom_rpa.configure_custom_app(task, context)
        pause_result = self._pause_for_browser_result(task_id, robot_id, step, result)
        if pause_result is not None:
            return pause_result
        output = {
            "token": result["token"],
            "encoding_aes_key": result["encoding_aes_key"],
            "review_status": result.get("review_status", "配置完成"),
        }
        self.store.merge_task_context(task_id, {"wecom": output})
        self.store.append_task_step(task_id, step["key"], step["name"], "success", output_data=output)
        return None

    def _jdy_check_owner(self, task_id: str, step: Dict[str, Any]) -> None:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.jdy_client.check_wework_owner(
            task["source_user_id"],
            suite_id=int(context["jdy"]["suite_id"]),
            suite_scenario=context["jdy"]["suite_scenario"],
        )
        if not result.can_bind_corp_secret:
            raise OwnerCannotBindError("User_ID cannot bind corp secret")
        output = {"can_bind_corp_secret": True}
        self.store.append_task_step(task_id, step["key"], step["name"], "success", output_data=output)

    def _jdy_install_bind(self, task_id: str, step: Dict[str, Any]) -> None:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.jdy_client.install_corp_deploy(
            JdyInstallRequest(
                corp_id=context["jdy"]["corp_secret_id"],
                corp_name=context["jdy"]["corp_name"],
                tenant_id=task["source_user_id"],
                token=context["wecom"]["token"],
                encoding_aes_key=context["wecom"]["encoding_aes_key"],
                suite_id=int(context["jdy"]["suite_id"]),
                suite_scenario=context["jdy"]["suite_scenario"],
            )
        )
        bound_user_id = result.owner_id or result.tenant_id
        output = {
            "original_tenant_id": context["jdy"].get("original_tenant_id", context["jdy"].get("tenant_id", "")),
            "requested_user_id": task["source_user_id"],
            "install_tenant_id": result.tenant_id,
            "install_owner_id": result.owner_id,
            "bound_user_id": bound_user_id,
        }
        self.store.merge_task_context(task_id, {"jdy": output})
        self.store.append_task_step(task_id, step["key"], step["name"], "success", output_data=output)

    def _submit_review(
        self,
        task_id: str,
        robot_id: str,
        step: Dict[str, Any],
        now: Optional[datetime],
    ) -> Dict[str, Any]:
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.wecom_rpa.submit_review(task, context)
        output = {"review_status": result.get("review_status", "审核中")}
        self.store.merge_task_context(task_id, {"wecom": output})
        self.store.append_task_step(task_id, step["key"], step["name"], "success", output_data=output)
        next_check = (now or datetime.now()) + timedelta(minutes=10)
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_REVIEW,
            next_check_at=next_check,
            assigned_robot_id=None,
        )
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.WAITING_WECOM_REVIEW.value}

    def _check_review(
        self,
        task_id: str,
        robot_id: str,
        now: Optional[datetime],
    ) -> Dict[str, Any]:
        self.store.set_task_current_step(task_id, "wecom_wait_review")
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        status = self.wecom_rpa.check_review_status(task, context)
        output = {"review_status": status.value}
        self.store.merge_task_context(task_id, {"wecom": output})
        self.store.append_task_step(task_id, "wecom_wait_review", "等待企微审核通过", "success", output_data=output)
        if status == WecomReviewStatus.READY_TO_ONLINE:
            self.store.set_task_status(task_id, TaskStatus.READY_TO_ONLINE, assigned_robot_id=None)
            self.store.update_robot_status(robot_id, "idle")
            return {"task_id": task_id, "status": TaskStatus.READY_TO_ONLINE.value}
        next_check = (now or datetime.now()) + timedelta(minutes=10)
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_REVIEW,
            next_check_at=next_check,
            assigned_robot_id=None,
        )
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.WAITING_WECOM_REVIEW.value}

    def _submit_online(self, task_id: str, robot_id: str) -> Dict[str, Any]:
        self.store.set_task_current_step(task_id, "wecom_submit_online")
        task = self.store.get_task(task_id)
        context = self.store.get_task_context(task_id)
        result = self.wecom_rpa.submit_online(task, context)
        output = {"review_status": result.get("review_status", WecomReviewStatus.ONLINE.value)}
        self.store.merge_task_context(task_id, {"wecom": output})
        self.store.append_task_step(task_id, "wecom_submit_online", "企微待上线后提交上线", "success", output_data=output)
        self.store.set_task_status(task_id, TaskStatus.SUCCESS, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.SUCCESS.value}

    def _pause_for_browser_result(
        self,
        task_id: str,
        robot_id: str,
        step: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        status = result.get("status")
        if status == "needs_login":
            return self._pause_for_manual_action(
                task_id,
                robot_id,
                step,
                TaskStatus.WAITING_LOGIN,
                "waiting_login",
                result.get("reason") or "浏览器登录态失效，需要重新登录",
                result,
            )
        if status == "manual_required":
            return self._pause_for_manual_action(
                task_id,
                robot_id,
                step,
                TaskStatus.WAITING_MANUAL_INTERVENTION,
                "waiting_manual_intervention",
                result.get("reason") or "browser-use 需要人工介入",
                result,
            )
        return None

    def _pause_for_manual_action(
        self,
        task_id: str,
        robot_id: str,
        step: Dict[str, Any],
        status: TaskStatus,
        action_type: str,
        reason: str,
        output: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.store.append_task_step(task_id, step["key"], step["name"], status.value, output_data=output)
        self.store.create_manual_action(task_id, action_type=action_type, reason=reason, candidates=[])
        self.store.set_task_status(task_id, status, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": status.value, "reason": reason}


def _snapshot_steps(task: Dict[str, Any]):
    return json.loads(task["flow_version_snapshot_json"])["steps"]
