import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from rpa_platform.domain.flow_steps import validate_steps
from rpa_platform.domain.redaction import redact_context
from rpa_platform.domain.state_machine import ensure_task_transition, TaskStatus


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _format_datetime(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _mask_corp_id(corp_id: str) -> str:
    if len(corp_id) < 3:
        return "***"
    return "%s***%s" % (corp_id[:3], corp_id[-3:])


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class TaskCreateResult:
    task_id: str
    created: bool


class SQLiteStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS teams (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    webhook_url TEXT DEFAULT '',
                    notification_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS flow_templates (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL REFERENCES teams(id),
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    published_version_id TEXT,
                    draft_version_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS flow_versions (
                    id TEXT PRIMARY KEY,
                    flow_template_id TEXT NOT NULL REFERENCES flow_templates(id),
                    version_no INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    published_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(flow_template_id, version_no)
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL REFERENCES teams(id),
                    flow_template_id TEXT NOT NULL REFERENCES flow_templates(id),
                    flow_version_id TEXT NOT NULL REFERENCES flow_versions(id),
                    flow_version_snapshot_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    enterprise_name TEXT NOT NULL,
                    corp_id TEXT NOT NULL,
                    source_user_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    runtime_context_json TEXT NOT NULL DEFAULT '{}',
                    current_step_key TEXT DEFAULT '',
                    next_check_at TEXT,
                    check_attempts INTEGER NOT NULL DEFAULT 0,
                    assigned_robot_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_platform_tasks_status
                    ON tasks(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_platform_tasks_next_check
                    ON tasks(next_check_at);

                CREATE TABLE IF NOT EXISTS task_steps (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    step_key TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    input_json TEXT NOT NULL DEFAULT '{}',
                    output_json TEXT NOT NULL DEFAULT '{}',
                    error_type TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    screenshot_id TEXT
                );

                CREATE TABLE IF NOT EXISTS task_artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    step_id TEXT REFERENCES task_steps(id),
                    artifact_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS robots (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    host TEXT NOT NULL,
                    browser_profile_path TEXT NOT NULL,
                    last_heartbeat_at TEXT,
                    capabilities_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS manual_actions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    selected_candidate_json TEXT,
                    handled_by TEXT,
                    handled_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_tasks_runtime_context_column(conn)

    def create_team(
        self,
        name: str,
        webhook_url: str = "",
        notification_enabled: bool = True,
    ) -> str:
        team_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO teams
                    (id, name, webhook_url, notification_enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (team_id, name, webhook_url, int(notification_enabled), now, now),
            )
        return team_id

    def create_flow_template(self, team_id: str, name: str, description: str) -> str:
        flow_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO flow_templates
                    (id, team_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (flow_id, team_id, name, description, now, now),
            )
        return flow_id

    def get_flow_template(self, flow_template_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM flow_templates WHERE id=?",
                (flow_template_id,),
            ).fetchone()
        if row is None:
            raise KeyError(flow_template_id)
        return dict(row)

    def list_flow_templates(self, team_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM flow_templates
                WHERE team_id=?
                ORDER BY created_at DESC, name ASC
                """,
                (team_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_flow_version(
        self,
        flow_template_id: str,
        steps: List[Dict[str, Any]],
        created_by: str,
    ) -> str:
        version_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            normalized_steps = validate_steps(steps)
            row = conn.execute(
                """
                SELECT COALESCE(MAX(version_no), 0) + 1 AS next_no
                FROM flow_versions
                WHERE flow_template_id=?
                """,
                (flow_template_id,),
            ).fetchone()
            version_no = int(row["next_no"])
            conn.execute(
                """
                INSERT INTO flow_versions
                    (id, flow_template_id, version_no, status, steps_json,
                     created_by, created_at, updated_at)
                VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)
                """,
                (
                    version_id,
                    flow_template_id,
                    version_no,
                    json.dumps(normalized_steps, ensure_ascii=False),
                    created_by,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE flow_templates
                SET draft_version_id=?, updated_at=?
                WHERE id=?
                """,
                (version_id, now, flow_template_id),
            )
        return version_id

    def get_flow_version(self, flow_version_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM flow_versions WHERE id=?",
                (flow_version_id,),
            ).fetchone()
        if row is None:
            raise KeyError(flow_version_id)
        return dict(row)

    def list_flow_versions(self, flow_template_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM flow_versions
                WHERE flow_template_id=?
                ORDER BY version_no DESC
                """,
                (flow_template_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def publish_flow_version(self, flow_template_id: str, flow_version_id: str) -> str:
        now = _now()
        with self._connect() as conn:
            version = conn.execute(
                """
                SELECT id FROM flow_versions
                WHERE id=? AND flow_template_id=?
                """,
                (flow_version_id, flow_template_id),
            ).fetchone()
            if version is None:
                raise ValueError("Flow version does not belong to template")
            conn.execute(
                """
                UPDATE flow_versions
                SET status='archived', updated_at=?
                WHERE flow_template_id=? AND status='published'
                """,
                (now, flow_template_id),
            )
            conn.execute(
                """
                UPDATE flow_versions
                SET status='published', published_at=?, updated_at=?
                WHERE id=?
                """,
                (now, now, flow_version_id),
            )
            conn.execute(
                """
                UPDATE flow_templates
                SET published_version_id=?, draft_version_id=NULL, updated_at=?
                WHERE id=?
                """,
                (flow_version_id, now, flow_template_id),
            )
        return flow_version_id

    def copy_flow_version(
        self,
        flow_template_id: str,
        source_version_id: str,
        created_by: str,
    ) -> str:
        source = self.get_flow_version(source_version_id)
        if source["flow_template_id"] != flow_template_id:
            raise ValueError("Flow version does not belong to template")
        return self.create_flow_version(
            flow_template_id=flow_template_id,
            steps=json.loads(source["steps_json"]),
            created_by=created_by,
        )

    def rollback_flow_version(self, flow_template_id: str, flow_version_id: str) -> str:
        return self.publish_flow_version(flow_template_id, flow_version_id)

    def create_task_from_published_flow(
        self,
        team_id: str,
        flow_template_id: str,
        enterprise_name: str,
        corp_id: str,
        source_user_id: str,
        idempotency_key: str,
        payload: Dict[str, Any],
    ) -> TaskCreateResult:
        task_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM tasks WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return TaskCreateResult(task_id=existing["id"], created=False)

            version = conn.execute(
                """
                SELECT v.id, v.version_no, v.status, v.steps_json, v.published_at
                FROM flow_templates t
                JOIN flow_versions v ON v.id=t.published_version_id
                WHERE t.id=? AND t.team_id=?
                """,
                (flow_template_id, team_id),
            ).fetchone()
            if version is None:
                raise ValueError("Flow template has no published version")

            snapshot = {
                "id": version["id"],
                "version_no": version["version_no"],
                "status": version["status"],
                "published_at": version["published_at"],
                "steps": json.loads(version["steps_json"]),
            }
            conn.execute(
                """
                INSERT INTO tasks
                    (id, team_id, flow_template_id, flow_version_id,
                     flow_version_snapshot_json, status, enterprise_name, corp_id,
                     source_user_id, idempotency_key, payload_json,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    team_id,
                    flow_template_id,
                    version["id"],
                    json.dumps(snapshot, ensure_ascii=False),
                    TaskStatus.PENDING.value,
                    enterprise_name,
                    corp_id,
                    source_user_id,
                    idempotency_key,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return TaskCreateResult(task_id=task_id, created=True)

    def get_task(self, task_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return dict(row)

    def get_task_context(self, task_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        return json.loads(task.get("runtime_context_json") or "{}")

    def merge_task_context(self, task_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT runtime_context_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            context = json.loads(row["runtime_context_json"] or "{}")
            merged = _deep_merge(context, patch)
            conn.execute(
                """
                UPDATE tasks
                SET runtime_context_json=?, updated_at=?
                WHERE id=?
                """,
                (json.dumps(merged, ensure_ascii=False), now, task_id),
            )
        return merged

    def set_task_current_step(self, task_id: str, step_key: str) -> None:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE tasks
                SET current_step_key=?, updated_at=?
                WHERE id=?
                """,
                (step_key, now, task_id),
            )
            if cur.rowcount == 0:
                raise KeyError(task_id)

    def set_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        next_check_at: Optional[Any] = None,
        check_attempts: Optional[int] = None,
        assigned_robot_id: Optional[str] = None,
    ) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status=?,
                    next_check_at=?,
                    check_attempts=COALESCE(?, check_attempts),
                    assigned_robot_id=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    TaskStatus(status).value,
                    _format_datetime(next_check_at),
                    check_attempts,
                    assigned_robot_id,
                    now,
                    task_id,
                ),
            )

    def get_task_detail(self, task_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        detail = dict(task)
        detail["corp_id_masked"] = _mask_corp_id(task["corp_id"])
        detail["flow_version_snapshot"] = json.loads(task["flow_version_snapshot_json"])
        detail["payload"] = json.loads(task["payload_json"])
        detail["runtime_context"] = redact_context(json.loads(task.get("runtime_context_json") or "{}"))
        detail["steps"] = self.list_task_steps(task_id)
        detail["artifacts"] = self.list_task_artifacts(task_id)
        detail["manual_actions"] = self.list_manual_actions(task_id)
        robot_id = task.get("assigned_robot_id")
        detail["robot"] = self.get_robot(robot_id) if robot_id else None
        return detail

    @staticmethod
    def _ensure_tasks_runtime_context_column(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "runtime_context_json" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN runtime_context_json TEXT NOT NULL DEFAULT '{}'")

    def create_task_artifact(
        self,
        task_id: str,
        step_id: Optional[str],
        artifact_type: str,
        path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        artifact_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_artifacts
                    (id, task_id, step_id, artifact_type, path, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    task_id,
                    step_id,
                    artifact_type,
                    path,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                ),
            )
        return artifact_id

    def list_task_artifacts(self, task_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_artifacts
                WHERE task_id=?
                ORDER BY created_at ASC, id ASC
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_manual_action(
        self,
        task_id: str,
        action_type: str,
        reason: str,
        candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        action_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO manual_actions
                    (id, task_id, action_type, status, reason, candidates_json,
                     created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    action_id,
                    task_id,
                    action_type,
                    reason,
                    json.dumps(candidates or [], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return action_id

    def get_manual_action(self, action_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM manual_actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise KeyError(action_id)
        return dict(row)

    def list_manual_actions(self, task_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM manual_actions
                WHERE task_id=?
                ORDER BY created_at ASC, id ASC
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def resume_task(
        self,
        task_id: str,
        handled_by: str,
        selected_candidate: Optional[Dict[str, Any]] = None,
        note: str = "",
    ) -> Dict[str, Any]:
        task = self.get_task(task_id)
        current = TaskStatus(task["status"])
        target = self._resume_target_status(current)
        ensure_task_transition(current, target)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status=?, assigned_robot_id=NULL, updated_at=?
                WHERE id=?
                """,
                (target.value, now, task_id),
            )
            conn.execute(
                """
                UPDATE manual_actions
                SET status='resolved',
                    selected_candidate_json=?,
                    handled_by=?,
                    handled_at=?,
                    updated_at=?
                WHERE task_id=? AND status='pending'
                """,
                (
                    json.dumps(selected_candidate, ensure_ascii=False) if selected_candidate else None,
                    handled_by,
                    now,
                    now,
                    task_id,
                ),
            )
        if note:
            self.append_task_step(
                task_id,
                "manual_resume",
                "管理员继续任务",
                "success",
                output_data={"handled_by": handled_by, "note": note},
            )
        return {"task_id": task_id, "status": target.value}

    @staticmethod
    def _resume_target_status(current: TaskStatus) -> TaskStatus:
        if current == TaskStatus.WAITING_LOGIN:
            return TaskStatus.CHECKING_LOGIN
        if current in (TaskStatus.WAITING_MANUAL_SELECTION, TaskStatus.WAITING_MANUAL_INTERVENTION):
            return TaskStatus.RUNNING
        if current == TaskStatus.WAITING_TEST_CONFIRMATION:
            return TaskStatus.RUNNING
        raise ValueError("Task status cannot be resumed: %s" % current.value)

    def register_robot(
        self,
        name: str,
        host: str,
        browser_profile_path: str,
        capabilities: Optional[Dict[str, Any]] = None,
    ) -> str:
        robot_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO robots
                    (id, name, status, host, browser_profile_path,
                     last_heartbeat_at, capabilities_json, created_at, updated_at)
                VALUES (?, ?, 'idle', ?, ?, ?, ?, ?, ?)
                """,
                (
                    robot_id,
                    name,
                    host,
                    browser_profile_path,
                    now,
                    json.dumps(capabilities or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return robot_id

    def get_robot(self, robot_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM robots WHERE id=?", (robot_id,)).fetchone()
        if row is None:
            raise KeyError(robot_id)
        return dict(row)

    def get_robot_capabilities(self, robot_id: str) -> Dict[str, Any]:
        robot = self.get_robot(robot_id)
        return json.loads(robot["capabilities_json"])

    def update_robot_status(self, robot_id: str, status: str) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE robots
                SET status=?, last_heartbeat_at=?, updated_at=?
                WHERE id=?
                """,
                (status, now, now, robot_id),
            )

    def claim_next_runnable_task(self, robot_id: str, now: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        now_text = _format_datetime(now) or _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            robot = conn.execute("SELECT * FROM robots WHERE id=?", (robot_id,)).fetchone()
            if robot is None:
                raise KeyError(robot_id)
            if robot["status"] != "idle":
                return None

            task = conn.execute(
                """
                SELECT * FROM tasks
                WHERE
                    status='pending'
                    OR status='ready_to_online'
                    OR status='jdy_callback_failed'
                    OR (
                        status='waiting_wecom_review'
                        AND next_check_at IS NOT NULL
                        AND next_check_at != ''
                        AND next_check_at <= ?
                    )
                    OR (
                        status='waiting_wecom_online_delay'
                        AND next_check_at IS NOT NULL
                        AND next_check_at != ''
                        AND next_check_at <= ?
                    )
                ORDER BY
                    CASE status
                        WHEN 'pending' THEN 1
                        WHEN 'ready_to_online' THEN 2
                        WHEN 'waiting_wecom_review' THEN 3
                        WHEN 'jdy_callback_failed' THEN 4
                        WHEN 'waiting_wecom_online_delay' THEN 5
                        ELSE 9
                    END,
                    created_at ASC
                LIMIT 1
                """,
                (now_text, now_text),
            ).fetchone()
            if task is None:
                return None

            increment_attempts = 1 if task["status"] in {
                TaskStatus.WAITING_WECOM_REVIEW.value,
                TaskStatus.WAITING_WECOM_ONLINE_DELAY.value,
            } else 0
            conn.execute(
                """
                UPDATE tasks
                SET status=?,
                    assigned_robot_id=?,
                    check_attempts=check_attempts + ?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    TaskStatus.CHECKING_LOGIN.value,
                    robot_id,
                    increment_attempts,
                    now_text,
                    task["id"],
                ),
            )
            conn.execute(
                """
                UPDATE robots
                SET status='busy', last_heartbeat_at=?, updated_at=?
                WHERE id=?
                """,
                (now_text, now_text, robot_id),
            )
            claimed = conn.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
        return dict(claimed)

    def append_task_step(
        self,
        task_id: str,
        step_key: str,
        step_name: str,
        status: str,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        step_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_steps
                    (id, task_id, step_key, step_name, status, attempt,
                     started_at, finished_at, input_json, output_json)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    task_id,
                    step_key,
                    step_name,
                    status,
                    now,
                    now,
                    json.dumps(input_data or {}, ensure_ascii=False),
                    json.dumps(output_data or {}, ensure_ascii=False),
                ),
            )
        return step_id

    def list_task_steps(self, task_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_steps
                WHERE task_id=?
                ORDER BY started_at ASC, id ASC
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]
