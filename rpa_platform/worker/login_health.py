from dataclasses import dataclass
from typing import Dict, List

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.storage.sqlite_store import SQLiteStore


@dataclass(frozen=True)
class LoginCheckResult:
    healthy: bool
    message: str


@dataclass(frozen=True)
class TaskLoginCheckOutcome:
    status: TaskStatus
    missing_targets: List[str]


class StaticLoginProbe:
    """Deterministic probe used until the Playwright implementation is added."""

    def __init__(self, results: Dict[str, LoginCheckResult]):
        self.results = results

    def check(self, target: str, entry_url: str, robot: dict, task: dict) -> LoginCheckResult:
        return self.results.get(target, LoginCheckResult(False, "missing static login result"))


class LoginHealthChecker:
    def __init__(self, store: SQLiteStore, probe: StaticLoginProbe):
        self.store = store
        self.probe = probe

    def check_task_login(self, task_id: str, robot_id: str) -> TaskLoginCheckOutcome:
        task = self.store.get_task(task_id)
        robot = self.store.get_robot(robot_id)
        capabilities = self.store.get_robot_capabilities(robot_id)
        entry_urls = capabilities.get("entry_urls", {})

        probe_results = {}
        missing_targets = []
        for target in ("jdy", "wecom"):
            result = self.probe.check(target, entry_urls.get(target, ""), robot, task)
            probe_results[target] = {
                "healthy": result.healthy,
                "message": result.message,
                "entry_url": entry_urls.get(target, ""),
            }
            if not result.healthy:
                missing_targets.append(target)

        if missing_targets:
            self.store.append_task_step(
                task_id=task_id,
                step_key="login_check",
                step_name="检查后台登录态",
                status="failed",
                output_data={"targets": probe_results, "missing_targets": missing_targets},
            )
            self.store.set_task_status(task_id, TaskStatus.WAITING_LOGIN, assigned_robot_id=None)
            self.store.update_robot_status(robot_id, "idle")
            return TaskLoginCheckOutcome(TaskStatus.WAITING_LOGIN, missing_targets)

        self.store.append_task_step(
            task_id=task_id,
            step_key="login_check",
            step_name="检查后台登录态",
            status="success",
            output_data={"targets": probe_results},
        )
        self.store.set_task_status(task_id, TaskStatus.RUNNING, assigned_robot_id=robot_id)
        return TaskLoginCheckOutcome(TaskStatus.RUNNING, [])
