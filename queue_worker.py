# coding=utf-8
"""
queue_worker.py - 后台队列 Worker 线程
替换 Celery，串行取出 pending 任务并执行
"""
import threading
import logging
import time
from typing import Optional

from config import TASK_RETRY_DELAY

# 后台线程引用（用于判断是否已启动）
_worker_thread: Optional[threading.Thread] = None


def start_worker():
    """启动队列 Worker 后台线程（只启动一次）"""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        logging.info("队列 Worker 已在运行，跳过重复启动")
        return
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="QueueWorker",
        daemon=True
    )
    _worker_thread.start()
    logging.info("队列 Worker 线程已启动")


def _worker_loop():
    """
    Worker 主循环
    - 串行执行，同一时间只处理一个任务
    - 队列暂停时等待，恢复后继续
    - 无任务时每秒检查一次
    """
    # 延迟导入，避免循环依赖
    from database import (
        get_next_pending_task, update_task_status, is_queue_paused
    )
    # execute_workflow / execute_send_message_workflow / WorkflowException
    # 在 RPA 模块中定义，通过函数注入方式调用
    import importlib

    logging.info("队列 Worker 开始监听任务...")

    while True:
        try:
            # 队列暂停时等待
            if is_queue_paused():
                time.sleep(TASK_RETRY_DELAY)
                continue

            task = get_next_pending_task()
            if not task:
                time.sleep(1)
                continue

            task_id = task['task_id']
            task_type = task['task_type']

            # 防止已完成的任务重复执行（双重保险）
            current_status = task.get('status')
            if current_status in ('success', 'retried', 'group_not_found'):
                logging.info("任务 %s 状态已为 %s，跳过", task_id, current_status)
                continue

            logging.info("开始执行任务 %s（类型: %s）", task_id, task_type)
            update_task_status(task_id, 'running')

            # 动态获取 RPA 模块中的执行函数（避免循环导入）
            rpa = importlib.import_module('RPA')
            WorkflowException = rpa.WorkflowException

            if task_type == 'create_group':
                _run_create_group(task, rpa, WorkflowException, update_task_status)
            elif task_type == 'send_message':
                _run_send_message(task, rpa, WorkflowException, update_task_status)
            else:
                logging.error("未知任务类型: %s，标记为 failed", task_type)
                update_task_status(task_id, 'failed',
                                   error_msg=f'未知任务类型: {task_type}',
                                   error_type='UnknownTaskType')

        except Exception as e:
            logging.error("队列 Worker 异常: %s", str(e), exc_info=True)
            time.sleep(1)


def _run_create_group(task: dict, rpa, WorkflowException, update_task_status_fn):
    """执行建群任务"""
    import json
    task_id = task['task_id']
    try:
        config = json.loads(task.get('config_json', '{}'))
        rpa.execute_workflow(config)
        update_task_status_fn(task_id, 'success')
        logging.info("建群任务 %s 执行成功", task_id)
    except WorkflowException as e:
        update_task_status_fn(
            task_id, 'failed',
            error_msg=str(e),
            error_type=e.error_type,
            error_detail=e.error_detail
        )
        logging.error("建群任务 %s 失败（WorkflowException）: %s", task_id, str(e))
    except Exception as e:
        update_task_status_fn(
            task_id, 'failed',
            error_msg=str(e),
            error_type=type(e).__name__
        )
        logging.error("建群任务 %s 异常: %s", task_id, str(e), exc_info=True)


def _run_send_message(task: dict, rpa, WorkflowException, update_task_status_fn):
    """执行发消息任务"""
    import json
    task_id = task['task_id']
    try:
        config = json.loads(task.get('config_json', '{}'))
        result = rpa.execute_send_message_workflow(config)
        if result == 'group_not_found':
            update_task_status_fn(task_id, 'group_not_found', error_msg='群不存在')
            logging.info("发消息任务 %s：群不存在", task_id)
        else:
            update_task_status_fn(task_id, 'success')
            logging.info("发消息任务 %s 执行成功", task_id)
    except WorkflowException as e:
        update_task_status_fn(
            task_id, 'failed',
            error_msg=str(e),
            error_type=e.error_type,
            error_detail=e.error_detail
        )
        # 发消息失败不中断队列，仅记录日志
        logging.error("发消息任务 %s 失败（WorkflowException）: %s", task_id, str(e))
    except Exception as e:
        update_task_status_fn(
            task_id, 'failed',
            error_msg=str(e),
            error_type=type(e).__name__
        )
        logging.error("发消息任务 %s 异常: %s", task_id, str(e), exc_info=True)
