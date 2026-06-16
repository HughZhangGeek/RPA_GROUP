from datetime import datetime
from typing import Any, Dict, Optional

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.login_health import LoginHealthChecker


class FakeRunner:
    """No-browser runner used to verify scheduler plumbing before Playwright exists."""

    def __init__(self, store: SQLiteStore, login_checker: Optional[LoginHealthChecker] = None):
        self.store = store
        self.login_checker = login_checker

    def run_claimed_task(
        self,
        task_id: str,
        robot_id: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if self.login_checker is not None:
            outcome = self.login_checker.check_task_login(task_id, robot_id)
            if outcome.status == TaskStatus.WAITING_LOGIN:
                return {
                    "task_id": task_id,
                    "robot_id": robot_id,
                    "status": "waiting_login",
                    "missing_targets": outcome.missing_targets,
                }

        self.store.set_task_status(task_id, TaskStatus.RUNNING, assigned_robot_id=robot_id)
        self.store.append_task_step(
            task_id=task_id,
            step_key="worker_stub",
            step_name="Worker 骨架占位执行",
            status="success",
            output_data={"runner": "fake", "next": "playwright_profile"},
        )
        self.store.update_robot_status(robot_id, "idle")
        return {"task_id": task_id, "robot_id": robot_id, "status": "runner_stubbed"}
