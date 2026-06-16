from datetime import datetime
from typing import Any, Dict, Optional, Protocol

from rpa_platform.storage.sqlite_store import SQLiteStore


class ClaimedTaskRunner(Protocol):
    def run_claimed_task(
        self,
        task_id: str,
        robot_id: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class TaskScheduler:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def claim_next_task(
        self,
        robot_id: str,
        now: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.store.claim_next_runnable_task(robot_id, now=now)

    def run_once(
        self,
        robot_id: str,
        runner: ClaimedTaskRunner,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        claimed = self.claim_next_task(robot_id, now=now)
        if claimed is None:
            return {"claimed": False, "robot_id": robot_id}
        runner_result = runner.run_claimed_task(claimed["id"], robot_id, now=now)
        return {
            "claimed": True,
            "robot_id": robot_id,
            "task_id": claimed["id"],
            "runner_result": runner_result,
        }
