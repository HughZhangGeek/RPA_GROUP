from datetime import datetime
from typing import Any, Dict, Optional

from rpa_platform.storage.sqlite_store import SQLiteStore


class TaskScheduler:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def claim_next_task(
        self,
        robot_id: str,
        now: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.store.claim_next_runnable_task(robot_id, now=now)
