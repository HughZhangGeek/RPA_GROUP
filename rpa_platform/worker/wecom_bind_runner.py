from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.integrations.wecom_admin_client import RetryableWecomOrderError
from rpa_platform.services.wecom_bind_service import JdyWecomBindInput, JdyWecomBindService
from rpa_platform.storage.sqlite_store import SQLiteStore


class WecomBindServiceRunner:
    def __init__(self, store: SQLiteStore, service: JdyWecomBindService):
        self.store = store
        self.service = service

    def run_claimed_task(
        self,
        task_id: str,
        robot_id: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        current_time = now or datetime.now()
        current_status = TaskStatus(self.store.get_task(task_id)["status"])
        if current_status == TaskStatus.WAITING_WECOM_ONLINE_DELAY or self._is_claimed_online_delay(task_id, current_status):
            try:
                return self._submit_online(task_id, robot_id, current_time)
            except Exception as exc:
                self._record_failure(task_id, robot_id, "wecom_submit_online_order", "企微提交上线订单", exc)
                raise

        self.store.set_task_status(task_id, TaskStatus.RUNNING, assigned_robot_id=robot_id)
        self.store.set_task_current_step(task_id, "jdy_wecom_bind_service")
        task = self.store.get_task(task_id)
        try:
            result = self.service.start_bind(
                JdyWecomBindInput(
                    enterprise_name=task["enterprise_name"],
                    plain_corp_id=task["corp_id"],
                    requested_user_id=task["source_user_id"],
                    suite_id=1,
                    suite_scenario="main",
                    wecom_suiteid=1009479,
                    suite_name="简道云",
                ),
                now=current_time,
            )
        except Exception as exc:
            self._record_failure(task_id, robot_id, "jdy_wecom_bind_service", "企微绑定接口服务", exc)
            raise
        self.store.merge_task_context(task_id, result.context)
        self.store.append_task_step(
            task_id,
            "jdy_wecom_bind_service",
            "企微绑定接口服务",
            "success",
            output_data=_step_output_from_context(result.context),
        )
        self.store.set_task_status(
            task_id,
            TaskStatus.WAITING_WECOM_ONLINE_DELAY,
            next_check_at=result.next_check_at,
            assigned_robot_id=None,
        )
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.WAITING_WECOM_ONLINE_DELAY.value}

    def _submit_online(self, task_id: str, robot_id: str, now: datetime) -> Dict[str, Any]:
        self.store.set_task_current_step(task_id, "wecom_submit_online_order")
        try:
            result = self.service.submit_online_order(self.store.get_task_context(task_id))
        except RetryableWecomOrderError as exc:
            output = {
                "error_type": "retryable_wecom_order",
                "error_detail": str(exc),
            }
            next_check_at = now + timedelta(minutes=2)
            self.store.append_task_step(
                task_id,
                "wecom_submit_online_order",
                "企微提交上线订单",
                TaskStatus.WAITING_WECOM_ONLINE_DELAY.value,
                output_data=output,
            )
            self.store.set_task_status(
                task_id,
                TaskStatus.WAITING_WECOM_ONLINE_DELAY,
                next_check_at=next_check_at,
                assigned_robot_id=None,
            )
            self.store.update_robot_status(robot_id, "idle")
            return {"task_id": task_id, "status": TaskStatus.WAITING_WECOM_ONLINE_DELAY.value}

        self.store.merge_task_context(task_id, result.context)
        self.store.append_task_step(
            task_id,
            "wecom_submit_online_order",
            "企微提交上线订单",
            "success",
            output_data=_step_output_from_context(result.context),
        )
        self.store.set_task_status(task_id, TaskStatus.SUCCESS, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "status": TaskStatus.SUCCESS.value}

    def _is_claimed_online_delay(self, task_id: str, current_status: TaskStatus) -> bool:
        if current_status != TaskStatus.CHECKING_LOGIN:
            return False
        context = self.store.get_task_context(task_id)
        return bool(context.get("wecom", {}).get("auditorderid"))

    def _record_failure(
        self,
        task_id: str,
        robot_id: str,
        step_key: str,
        step_name: str,
        exc: Exception,
    ) -> None:
        self.store.append_task_step(
            task_id,
            step_key,
            step_name,
            "failed",
            output_data={
                "error_type": exc.__class__.__name__,
                "error_detail": str(exc),
            },
        )
        self.store.set_task_status(task_id, TaskStatus.FAILED, assigned_robot_id=None)
        self.store.update_robot_status(robot_id, "idle")


def _step_output_from_context(context: Dict[str, Any]) -> Dict[str, Any]:
    jdy = context.get("jdy", {})
    wecom = context.get("wecom", {})
    return {
        "jdy": {
            "corp_secret_id": jdy.get("corp_secret_id", ""),
            "requested_user_id": jdy.get("requested_user_id", ""),
            "install_tenant_id": jdy.get("install_tenant_id", ""),
            "install_owner_id": jdy.get("install_owner_id", ""),
            "bound_user_id": jdy.get("bound_user_id", ""),
        },
        "wecom": {
            "app_id": wecom.get("app_id", ""),
            "aes_app_id": wecom.get("aes_app_id", ""),
            "auditorderid": wecom.get("auditorderid", ""),
            "auditorder_status": wecom.get("auditorder_status", ""),
            "token": "***" if wecom.get("token") else "",
            "encoding_aes_key": "***" if wecom.get("encoding_aes_key") else "",
        },
    }
