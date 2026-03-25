# coding=utf-8
"""
database.py - SQLite 数据层
替换原有的 Redis 操作，提供任务存储和队列控制功能
"""
import sqlite3
import threading
import logging
import json
import secrets
from datetime import datetime
from typing import Optional, List, Dict, Any

from config import DB_PATH, RESUME_TOKEN_EXPIRE

# 全局写锁，防止多线程并发写冲突
_db_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接，开启 WAL 模式提升并发读性能"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库，建表（幂等操作）"""
    with _db_lock:
        conn = _get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id         TEXT PRIMARY KEY,
                    task_type       TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    customer_name   TEXT DEFAULT '',
                    owner_name      TEXT DEFAULT '',
                    group_type      TEXT DEFAULT '',
                    group_name      TEXT DEFAULT '',
                    target_group    TEXT DEFAULT '',
                    message_content TEXT DEFAULT '',
                    paas_id         TEXT DEFAULT '',
                    user_id         TEXT DEFAULT '',
                    error_msg       TEXT DEFAULT '',
                    error_type      TEXT DEFAULT '',
                    error_detail    TEXT DEFAULT '',
                    config_json     TEXT DEFAULT '',
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_status
                    ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_task_type
                    ON tasks(task_type);
                CREATE INDEX IF NOT EXISTS idx_created_at
                    ON tasks(created_at DESC);

                CREATE TABLE IF NOT EXISTS queue_state (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    expires_at TEXT
                );
            """)
            conn.commit()
            logging.info("数据库初始化完成: %s", DB_PATH)
        finally:
            conn.close()


def recover_interrupted_tasks():
    """将上次 running 状态的任务重置为 pending，服务重启后自动续跑"""
    with _db_lock:
        conn = _get_conn()
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cur = conn.execute(
                "UPDATE tasks SET status='pending', updated_at=? WHERE status='running'",
                (now,)
            )
            conn.commit()
            if cur.rowcount:
                logging.info("启动恢复：%d 个中断任务重置为 pending", cur.rowcount)
        finally:
            conn.close()


# ─────────────────────────────────────────────
# 任务 CRUD
# ─────────────────────────────────────────────

def save_task(task_id: str, task_type: str, status: str, config: dict):
    """保存新任务（替换 save_task_to_redis）"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row = {
        'task_id': task_id,
        'task_type': task_type,
        'status': status,
        'customer_name': config.get('客户名称', ''),
        'owner_name': config.get('粘贴群主姓名', ''),
        'group_type': config.get('群类型', ''),
        'group_name': config.get('粘贴群名称', ''),
        'target_group': config.get('目标群名称', ''),
        'message_content': config.get('消息内容', ''),
        'paas_id': config.get('paas_id', ''),
        'user_id': config.get('user_id', ''),
        'error_msg': '',
        'error_type': '',
        'error_detail': '',
        'config_json': json.dumps(config, ensure_ascii=False),
        'created_at': now,
        'updated_at': now,
    }
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO tasks
                    (task_id, task_type, status,
                     customer_name, owner_name, group_type, group_name,
                     target_group, message_content, paas_id, user_id,
                     error_msg, error_type, error_detail, config_json,
                     created_at, updated_at)
                VALUES
                    (:task_id, :task_type, :status,
                     :customer_name, :owner_name, :group_type, :group_name,
                     :target_group, :message_content, :paas_id, :user_id,
                     :error_msg, :error_type, :error_detail, :config_json,
                     :created_at, :updated_at)
            """, row)
            conn.commit()
        finally:
            conn.close()


def update_task_status(task_id: str, status: str,
                       error_msg: str = '',
                       error_type: str = '',
                       error_detail: str = ''):
    """更新任务状态（替换 update_task_status Redis 版）"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute("""
                UPDATE tasks
                SET status=?, error_msg=?, error_type=?, error_detail=?,
                    updated_at=?
                WHERE task_id=?
            """, (status, error_msg, error_type, error_detail, now, task_id))
            conn.commit()
        finally:
            conn.close()


def get_task_detail(task_id: str) -> Optional[Dict[str, Any]]:
    """获取单个任务详情（替换 get_task_detail Redis 版）"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_next_pending_task() -> Optional[Dict[str, Any]]:
    """取下一条待执行任务（按创建时间最早优先）"""
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT * FROM tasks
            WHERE status='pending'
            ORDER BY created_at ASC
            LIMIT 1
        """).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ─────────────────────────────────────────────
# 历史查询
# ─────────────────────────────────────────────

def get_task_history(limit: int = 50, offset: int = 0,
                     task_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取任务历史列表（替换 Redis LRANGE 版）"""
    conn = _get_conn()
    try:
        if task_type:
            rows = conn.execute("""
                SELECT * FROM tasks
                WHERE task_type=?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (task_type, limit, offset)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM tasks
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_queue_stats(task_type: Optional[str] = None) -> Dict[str, Any]:
    """获取队列统计信息（替换 Redis 版本）"""
    conn = _get_conn()
    try:
        where = "WHERE task_type=?" if task_type else ""
        params = (task_type,) if task_type else ()

        rows = conn.execute(f"""
            SELECT status, COUNT(*) as cnt
            FROM tasks {where}
            GROUP BY status
        """, params).fetchall()

        stats = {
            'pending': 0,
            'running': 0,
            'success': 0,
            'failed': 0,
            'group_not_found': 0,
            'retried': 0,
        }
        for r in rows:
            s = r['status']
            if s in stats:
                stats[s] = r['cnt']

        stats['queue_paused'] = is_queue_paused()
        stats['task_running'] = is_task_running()
        stats['queue_length'] = stats['pending']
        return stats
    finally:
        conn.close()


def get_total_count(task_type: Optional[str] = None) -> int:
    """获取任务总数"""
    conn = _get_conn()
    try:
        if task_type:
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE task_type=?", (task_type,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


# ─────────────────────────────────────────────
# 队列控制
# ─────────────────────────────────────────────

def pause_queue() -> str:
    """暂停队列，返回恢复 token"""
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    # expires_at 存 Unix 时间戳字符串，方便比较
    from datetime import timedelta
    expires_at = (now + timedelta(seconds=RESUME_TOKEN_EXPIRE)).strftime('%Y-%m-%d %H:%M:%S')

    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO queue_state (key, value, expires_at)
                VALUES ('queue_paused', '1', NULL)
            """)
            conn.execute("""
                INSERT OR REPLACE INTO queue_state (key, value, expires_at)
                VALUES ('resume_token', ?, ?)
            """, (token, expires_at))
            conn.commit()
        finally:
            conn.close()
    return token


def resume_queue(token: Optional[str] = None) -> bool:
    """
    恢复队列。
    - token=None：管理员强制恢复（无需 token 验证）
    - token 有值：验证 token 后恢复
    返回 True 表示恢复成功
    """
    conn = _get_conn()
    try:
        if token is not None:
            row = conn.execute(
                "SELECT value, expires_at FROM queue_state WHERE key='resume_token'"
            ).fetchone()
            if not row:
                return False
            if row['value'] != token:
                return False
            # 检查过期
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if row['expires_at'] and now > row['expires_at']:
                return False
    finally:
        conn.close()

    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute("DELETE FROM queue_state WHERE key IN ('queue_paused','resume_token')")
            conn.commit()
        finally:
            conn.close()
    return True


def is_queue_paused() -> bool:
    """检查队列是否暂停"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM queue_state WHERE key='queue_paused'"
        ).fetchone()
        return row is not None and row['value'] == '1'
    finally:
        conn.close()


def get_resume_token() -> Optional[str]:
    """获取当前的恢复 token"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM queue_state WHERE key='resume_token'"
        ).fetchone()
        return row['value'] if row else None
    finally:
        conn.close()


def is_task_running() -> bool:
    """检查是否有任务正在执行"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='running'"
        ).fetchone()
        return row[0] > 0 if row else False
    finally:
        conn.close()
