# coding=utf-8
"""
migrate_redis_to_sqlite.py - 一次性迁移脚本
将 Redis 中的历史任务数据迁移到 SQLite

使用方法：
    python migrate_redis_to_sqlite.py

注意：迁移期间不要提交新任务，迁移完成后可删除此脚本。
"""
import json
import sys

try:
    import redis
except ImportError:
    print("未安装 redis 包，请先执行: pip install redis")
    sys.exit(1)

from database import init_db, save_task


REDIS_HOST = '127.0.0.1'
REDIS_PORT = 6379
REDIS_DB = 0

TASK_HISTORY_KEY = 'rpa:task_history'
TASK_DETAIL_PREFIX = 'rpa:task:'


def migrate():
    print("=== Redis → SQLite 迁移开始 ===")

    # 连接 Redis
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        r.ping()
        print(f"Redis 连接成功: {REDIS_HOST}:{REDIS_PORT}")
    except Exception as e:
        print(f"Redis 连接失败: {e}")
        sys.exit(1)

    # 初始化 SQLite（建表）
    init_db()
    print("SQLite 初始化完成")

    # 获取所有任务 ID
    all_ids = r.lrange(TASK_HISTORY_KEY, 0, -1)
    total = len(all_ids)
    print(f"Redis 中共有 {total} 条任务记录")

    if total == 0:
        print("没有需要迁移的数据，退出。")
        return

    success = 0
    skipped = 0
    failed = 0

    for task_id in all_ids:
        try:
            data = r.hgetall(f"{TASK_DETAIL_PREFIX}{task_id}")
            if not data:
                skipped += 1
                continue

            # 提取 config_json，还原成 dict
            config_json = data.get('config_json', '{}')
            try:
                config = json.loads(config_json)
            except json.JSONDecodeError:
                config = {}

            task_type = data.get('task_type', 'create_group')
            task_status = data.get('status', 'success')

            save_task(task_id, task_type, task_status, config)
            success += 1

            if success % 100 == 0:
                print(f"  已迁移 {success}/{total}...")

        except Exception as e:
            print(f"  迁移任务 {task_id} 失败: {e}")
            failed += 1

    print()
    print("=== 迁移完成 ===")
    print(f"  成功: {success}")
    print(f"  跳过（Redis 中无数据）: {skipped}")
    print(f"  失败: {failed}")
    print(f"  总计: {total}")


if __name__ == '__main__':
    migrate()