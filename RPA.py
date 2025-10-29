# coding=utf-8
import logging
from logging.handlers import RotatingFileHandler
import os
import time
from typing import Optional, List
import threading
import base64
import hashlib
from datetime import datetime
import secrets
import traceback

import keyboard
import pandas as pd
import pyautogui
import pygetwindow as gw
import pyperclip
import uvicorn
import requests
import json
import redis
from celery import Celery
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel


# from functools import lru_cache

# API鉴权配置
API_KEYS = "eLKuNm0lwf6yohsgPOWq1GV3obPCP6Il"
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# 在配置区添加常量
# WECOM_WEBHOOK_URL = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=83a3f024-568b-4570-ac12-8d94e08be18b'
WECOM_WEBHOOK_URL = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=168a74ba-ec52-42dd-bb42-12dcc79a7652'

# 风控监听配置
ERROR_IMAGE_PATH = './file/pictures/error.png'  # 风控图片路径
ERROR_SHOTS_DIR = './file/pictures/error_shots'  # 截图保存目录
FAILED_TASKS_LOG = 'failed_tasks.log'  # 失败任务日志文件
MONITOR_INTERVAL = 1  # 监听间隔（秒）
RESUME_TOKEN_EXPIRE = 3600  # 恢复token过期时间（秒），默认1小时
TASK_RETRY_DELAY = 30  # 队列暂停时任务重试延迟（秒）

# Redis连接（用于跨进程状态共享）
redis_client = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)
QUEUE_PAUSED_KEY = 'rpa:queue_paused'  # Redis中的暂停标志key
RESUME_TOKEN_KEY = 'rpa:resume_token'  # Redis中的恢复token key
TASK_RUNNING_KEY = 'rpa:task_running'  # Redis中的任务执行状态key

# 全局状态管理（仅用于FastAPI进程内部）
queue_lock = threading.Lock()  # 队列状态锁


def set_task_running(is_running: bool):
    """设置任务执行状态到Redis"""
    if is_running:
        redis_client.set(TASK_RUNNING_KEY, '1')
    else:
        redis_client.delete(TASK_RUNNING_KEY)


def is_task_running() -> bool:
    """从Redis检查是否有任务在执行"""
    return redis_client.get(TASK_RUNNING_KEY) == '1'
# 自定义异常
class QueuePausedException(Exception):
    """队列暂停异常，用于触发任务重试"""
    pass


async def validate_api_key(api_key: str = Depends(api_key_header)):
    """API密钥验证依赖项"""
    if not api_key or api_key not in API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
            headers={"WWW-Authenticate": "APIKey"},
        )


# FastAPI实例
app = FastAPI()


@app.on_event("startup")
async def startup_event():
    """FastAPI启动时执行"""
    # 启动风控监听线程（守护线程）
    monitor_thread = threading.Thread(target=monitor_risk_control_image, daemon=True)
    monitor_thread.start()
    logging.info("风控监听线程已在FastAPI启动时启动")


# Celery配置（需安装Redis）
celery_app = Celery('tasks', broker='redis://127.0.0.1:6379/0')
celery_app.conf.worker_concurrency = 1  # 关键：强制串行执行

# 固定Excel配置
EXCEL_PATH = "./file/excel/cmd.xlsx"  # 固定路径


class GroupConfigRequest(BaseModel):
    group_config: dict  # 动态传入的配置


# 配置日志记录
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 定义格式
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 控制台输出
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 文件输出（自动轮转）
file_handler = RotatingFileHandler(
    'rpa.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# 常量配置
CONFIDENCE = 0.9  # 图像识别置信度
CLICK_INTERVAL = 0.2  # 点击间隔(秒)
RETRY_TIMEOUT = 10  # 图像查找超时(秒)
RETRY_INTERVAL = 1  # 重试间隔(秒)


# 操作映射表（扩展点：新增操作在此添加）
ACTION_MAP = {
    '左击图片': ('image', 'left', 1),
    '右击图片': ('image', 'right', 1),
    '左击坐标': ('location', 'left', 1),
    '右击坐标': ('location', 'right', 1),
    '快捷键': ('hotkey', None, None),
    '等待': ('sleep', None, None),
    '检查图片是否存在': ('check_image', None, None),
    '激活企业微信': ('activate_window', '企业微信', None),
    '激活钉钉': ('activate_window', '钉钉', None),
    '粘贴': ('paste', None, None),
    '输入': ('typewrite', None, None),
    '滚动屏幕':('scroll', None, None)
}


def enhanced_click(click_times: int, button: str, target: str, mode: str) -> bool:
    """增强版点击操作（支持图像/坐标）

    Args:
        click_times: 点击次数
        button: 鼠标按钮 (left/right)
        target: 目标值（图片路径或坐标）
        mode: 操作模式 (image/location)

    Returns:
        bool: 是否执行成功

    Raises:
        ValueError: 坐标格式错误时抛出
        TimeoutError: 图片查找超时抛出
    """
    start_time = time.time()

    if mode == 'image':
        # 带超时机制的图像查找
        while (time.time() - start_time) < RETRY_TIMEOUT:
            # position = get_image_position(target)
            position = pyautogui.locateCenterOnScreen(target, confidence=CONFIDENCE)
            if position:
                pyautogui.click(
                    x=position.x,
                    y=position.y,
                    clicks=click_times,
                    interval=CLICK_INTERVAL,
                    button=button.lower()
                )
                return True
            logging.info(f"等待目标图像 [{target}]...")
            time.sleep(RETRY_INTERVAL)
        raise TimeoutError(f"未找到目标图像 [{target}]")

    if mode == 'location':
        try:
            # 支持多种坐标格式 (x, y)/(x y)
            clean_target = target.replace(' ', '').strip()
            x, y = map(int, clean_target.split(','))
            pyautogui.click(
                x=x,
                y=y,
                clicks=click_times,
                interval=CLICK_INTERVAL,
                button=button.lower()
            )
            return True
        except (ValueError, TypeError):
            raise ValueError(f"无效坐标格式: {target} (示例: 100,200)")

    raise ValueError(f"无效操作模式: {mode}")


def check_image_exists(img_path: str) -> bool:
    """快速图像存在检查

    Args:
        img_path: 图像文件路径

    Returns:
        bool: 当图像存在时返回True
    """
    # return get_image_position(img_path) is not None
    return pyautogui.locateCenterOnScreen(img_path, confidence=CONFIDENCE) is not None


def activate_window(title: str, shortcut: str) -> bool:
    """窗口激活工具（支持模糊匹配）

    Args:
        title: 窗口标题模糊匹配
        shortcut: 备用快捷方式路径

    Returns:
        bool: 操作是否成功
    """
    try:
        # 按标题相似度排序窗口
        windows = sorted(
            gw.getWindowsWithTitle(title),
            key=lambda w: len(w.title),
            reverse=True
        )

        if windows:
            window = windows[0]
            window.activate()
            window.maximize()
            return True

        if os.path.exists(shortcut):
            os.startfile(shortcut)
            # 动态调整等待时间
            for _ in range(10):
                if gw.getWindowsWithTitle(title):
                    return True
                time.sleep(1)
            logging.warning(f"启动快捷方式后未找到窗口: {title}")
            return False

        logging.error(f"快捷方式不存在: {shortcut}")
        return False

    except gw.PyGetWindowException as e:
        logging.error(f"窗口操作异常: {str(e)}")
        return False


def execute_command(action: str, value: str) -> Optional[bool]:
    """执行单条指令

    Args:
        action: 操作类型 (来自ACTION_MAP)
        value: 操作参数值

    Returns:
        Optional[bool]: 仅检查图片时返回布尔值

    Raises:
        KeyError: 未知操作类型时抛出
    """
    action_info = ACTION_MAP.get(action)
    if not action_info:
        raise KeyError(f"未知操作类型: {action}")

    action_type, param1, param2 = action_info

    if action_type == 'image':
        enhanced_click(click_times=param2, button=param1, target=value, mode='image')
    elif action_type == 'location':
        enhanced_click(click_times=param2, button=param1, target=value, mode='location')
    elif action_type == 'hotkey':
        keyboard.press_and_release(value)
    elif action_type == 'sleep':
        logging.info(f"等待 {value} 秒...")
        time.sleep(float(value))
    elif action_type == 'check_image':
        return check_image_exists(value)
    elif action_type == 'activate_window':
        activate_window(title=param1, shortcut=value)
    elif action_type == 'paste':
        pyperclip.copy(value)
        pyautogui.hotkey('ctrl', 'v')  # 更可靠的粘贴方式
    elif action_type == 'typewrite':
        pyautogui.typewrite(value, interval=0.1)
    elif action_type == 'scroll':
        logging.info("滚动屏幕")
        scroll_page('down')
    else:
        raise ValueError(f"未实现的操作类型: {action_type}")


# @lru_cache(maxsize=50)
# def get_image_position(img_path: str):
#     """带缓存的图像定位"""
#     return pyautogui.locateCenterOnScreen(img_path, confidence=CONFIDENCE)
#

def data_update(_id: str):
    pass

def scroll_page(direction: str):
    """模拟 Page Down/Up 键"""
    if direction == "down":
        logging.info("滚动屏幕")
        pyautogui.press("pagedown")
    else:
        pyautogui.press("pageup")
    time.sleep(0.2)  # 添加延迟确保操作生效


def capture_and_encode_screenshot() -> dict:
    """
    截图并生成base64和MD5编码

    Returns:
        dict: 包含截图路径、base64编码和MD5值
    """
    try:
        # 确保截图目录存在
        os.makedirs(ERROR_SHOTS_DIR, exist_ok=True)

        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        screenshot_path = os.path.join(ERROR_SHOTS_DIR, f'error_风控_{timestamp}.png')

        # 截图
        screenshot = pyautogui.screenshot()
        screenshot.save(screenshot_path)
        logging.info(f"截图已保存: {screenshot_path}")

        # 读取文件并生成base64和MD5
        with open(screenshot_path, 'rb') as f:
            image_data = f.read()

        # 生成base64（不包含换行符）
        base64_str = base64.b64encode(image_data).decode('utf-8')

        # 生成MD5
        md5_hash = hashlib.md5(image_data).hexdigest()

        return {
            'path': screenshot_path,
            'base64': base64_str,
            'md5': md5_hash
        }

    except Exception as e:
        logging.error(f"截图处理失败: {str(e)}")
        return None


def log_failed_task(group_config: dict, error_msg: str):
    """
    记录失败任务到日志文件

    Args:
        group_config: 任务配置
        error_msg: 错误消息
    """
    try:
        with open(FAILED_TASKS_LOG, 'a', encoding='utf-8') as f:
            log_entry = {
                '时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '客户名称': group_config.get('客户名称', 'N/A'),
                '群类型': group_config.get('群类型', 'N/A'),
                '失败原因': '风控检测',
                '错误信息': error_msg
            }
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            logging.info(f"失败任务已记录到 {FAILED_TASKS_LOG}")
    except Exception as e:
        logging.error(f"记录失败任务失败: {str(e)}")


def pause_queue():
    """暂停队列并生成恢复token（存储在Redis中，带过期时间）"""
    with queue_lock:
        token = secrets.token_urlsafe(32)
        # 存储到Redis（两个进程都能访问），设置过期时间
        redis_client.setex(QUEUE_PAUSED_KEY, RESUME_TOKEN_EXPIRE, '1')
        redis_client.setex(RESUME_TOKEN_KEY, RESUME_TOKEN_EXPIRE, token)
        logging.warning(f"队列已暂停（Redis），恢复token: {token}，有效期: {RESUME_TOKEN_EXPIRE}秒")
        return token


def resume_queue(token: str) -> bool:
    """恢复队列（需要验证token，从Redis读取状态）"""
    with queue_lock:
        stored_token = redis_client.get(RESUME_TOKEN_KEY)

        # Token不存在（可能已过期）
        if not stored_token:
            logging.error("恢复token不存在或已过期")
            return False

        # Token验证成功
        if token == stored_token:
            # 清除Redis中的暂停标志和token
            redis_client.delete(QUEUE_PAUSED_KEY)
            redis_client.delete(RESUME_TOKEN_KEY)
            logging.info("队列已恢复（Redis）")
            return True
        else:
            logging.error("恢复token无效")
            return False


def is_queue_paused() -> bool:
    """检查队列是否暂停（从Redis读取）"""
    return redis_client.get(QUEUE_PAUSED_KEY) == '1'


def handle_risk_control_detection(group_config: dict = None):
    """
    处理风控检测逻辑

    Args:
        group_config: 当前任务配置（如果有任务在执行）
    """
    logging.warning("检测到风控图片！")

    # 截图并编码
    screenshot_data = capture_and_encode_screenshot()
    if not screenshot_data:
        logging.error("截图失败，无法发送告警")
        return

    # 暂停队列并获取token
    token = pause_queue()

    # 构建恢复链接
    resume_url = f"http://127.0.0.1:8000/resume-queue?token={token}"

    # 场景A：任务执行中检测到风控（从Redis读取状态）
    if is_task_running() and group_config:
        logging.info("任务执行中检测到风控，等待任务自然报错...")
        # 记录失败任务
        log_failed_task(group_config, "风控检测导致任务中断")

    # 场景B：无任务执行时检测到风控
    else:
        logging.info("队列空闲时检测到风控")

    # 发送图片消息
    send_wecom_robot_message(
        webhook_url=WECOM_WEBHOOK_URL,
        msg_type="image",
        image_base64=screenshot_data['base64'],
        image_md5=screenshot_data['md5']
    )

    # 发送Markdown告警消息（包含恢复链接）
    alert_msg = f'''# <font color="warning">风控检测告警</font>
> **检测时间:** <font color="comment">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</font>
> **任务状态:** <font color="comment">{'任务执行中' if is_task_running() else '队列空闲'}</font>
> **截图路径:** <font color="comment">{screenshot_data['path']}</font>

**处理步骤：**
1. 扫码解决企业微信风控问题
2. 点击以下链接恢复任务队列（链接有效期：{RESUME_TOKEN_EXPIRE // 60}分钟）

**恢复链接:**
[请点击恢复队列]({resume_url})

⚠️ 注意：链接将在 {RESUME_TOKEN_EXPIRE // 60} 分钟后自动失效'''

    send_wecom_robot_message(
        content=alert_msg,
        webhook_url=WECOM_WEBHOOK_URL,
        msg_type="markdown"
    )

    logging.info("风控告警已发送")


def monitor_risk_control_image():
    """
    全局监听风控图片的后台线程

    持续监听ERROR_IMAGE_PATH，检测到图片时触发处理逻辑
    """
    logging.info(f"风控监听线程已启动，监听图片: {ERROR_IMAGE_PATH}")

    # 检查风控图片文件是否存在
    if not os.path.exists(ERROR_IMAGE_PATH):
        logging.error(f"风控图片文件不存在: {ERROR_IMAGE_PATH}")
        logging.warning("风控监听线程将继续运行，但无法检测到图片（请确保文件存在）")

    while True:
        try:
            # 检测风控图片
            position = pyautogui.locateOnScreen(ERROR_IMAGE_PATH, confidence=CONFIDENCE)

            # 检测到图片
            if position:
                logging.warning("检测到风控图片！触发处理逻辑...")
                handle_risk_control_detection()

                # 处理完成后等待较长时间，避免重复检测
                time.sleep(60)
            else:
                # 未检测到，正常间隔后继续
                time.sleep(MONITOR_INTERVAL)

        except pyautogui.ImageNotFoundException:
            # 未检测到图片，这是正常情况，静默继续
            time.sleep(MONITOR_INTERVAL)

        except FileNotFoundError as e:
            logging.error(f"风控监听线程异常 - 文件不存在: {ERROR_IMAGE_PATH}")
            logging.debug(f"异常详情: {str(e)}")
            time.sleep(MONITOR_INTERVAL)

        except Exception as e:
            # 其他未预期的异常才记录错误
            logging.error(f"风控监听线程异常 - 类型: {type(e).__name__}")
            logging.error(f"异常消息: {str(e)}")
            logging.error(f"完整堆栈:\n{traceback.format_exc()}")
            time.sleep(MONITOR_INTERVAL)
# 核心执行逻辑改造

def send_wecom_robot_message(
        content: str = None,
        webhook_url: str = None,
        msg_type: str = "text",
        mentioned_list: Optional[List[str]] = None,
        mentioned_mobile_list: Optional[List[str]] = None,
        image_base64: str = None,
        image_md5: str = None
) -> bool:
    """
    发送企业微信群机器人消息

    :param content: 消息内容（文本或Markdown内容）
    :param webhook_url: 机器人Webhook地址
    :param msg_type: 消息类型（text/markdown/image）
    :param mentioned_list: 需要@的用户ID列表
    :param mentioned_mobile_list: 需要@的手机号列表
    :param image_base64: 图片的base64编码（仅image类型）
    :param image_md5: 图片的MD5值（仅image类型）
    :return: 是否发送成功
    """
    headers = {"Content-Type": "application/json"}

    # 根据消息类型构建不同的payload
    if msg_type == "markdown":
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
    elif msg_type == "image":
        payload = {
            "msgtype": "image",
            "image": {
                "base64": image_base64,
                "md5": image_md5
            }
        }
    else:  # text类型
        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": mentioned_list or [],
                "mentioned_mobile_list": mentioned_mobile_list or []
            }
        }

    try:
        response = requests.post(
            url=webhook_url,
            headers=headers,
            json=payload,
            timeout=10
        )
        response.raise_for_status()

        result = response.json()
        if result.get("errcode") != 0:
            logging.error(f"企业微信消息发送失败: {result.get('errmsg')}")
            return False

        logging.info("企业微信消息发送成功")
        return True

    except requests.exceptions.RequestException as e:
        logging.error(f"消息请求失败: {str(e)}")
        return False
    except json.JSONDecodeError:
        logging.error("响应解析失败")
        return False

def execute_workflow(group_config: dict):
    """新版主工作流程"""

    # 检查队列是否暂停（从Redis读取，跨进程共享）
    if is_queue_paused():
        logging.warning("队列已暂停（检测到Redis标志），任务将延迟重试")
        # 抛出异常让Celery重试，而不是直接返回
        raise QueuePausedException("队列已暂停，任务将在队列恢复后自动重试")

    # 标记任务开始执行（存储到Redis，跨进程可见）
    set_task_running(True)
    logging.info("任务开始执行（已标记到Redis）")

    try:
        logging.info(group_config['群类型'])
        if group_config['群类型'] == '企微群':
            command_df = pd.read_excel(EXCEL_PATH, sheet_name='企微建群')
        else:
            command_df = pd.read_excel(EXCEL_PATH, sheet_name='钉钉建群')
        logging.info(f"成功读取本地指令文件，共{len(command_df)}条指令")

        # 遍历执行指令（增强异常捕获）
        for idx, cmd in command_df.iterrows():
            option = cmd['option']
            value = str(cmd['value'])
            detail = str(cmd.get('detail', '')) if 'detail' in cmd and pd.notna(cmd.get('detail')) else ''

            try:
                # 特殊粘贴处理逻辑
                if option in group_config:
                    actual_value = group_config[option]
                    logging.info(f"[{idx + 1}/{len(command_df)}] 执行: {option} => {actual_value}")
                    execute_command('粘贴', actual_value)
                else:
                    actual_value = value
                    logging.info(f"[{idx + 1}/{len(command_df)}] 执行: {option} => {value}")
                    execute_command(option, value)

            except Exception as e:
                # 构建详细的错误上下文
                error_context = {
                    '失败位置': f"第{idx + 1}条指令（共{len(command_df)}条）",
                    '操作类型': option,
                    '操作说明': detail,
                    '操作参数': actual_value,
                    '异常类型': type(e).__name__,
                    '错误详情': str(e),
                    '发生时间': time.strftime('%Y-%m-%d %H:%M:%S')
                }

                # 记录详细日志
                logging.error(
                    f"指令执行失败 - 位置:[{idx + 1}/{len(command_df)}] "
                    f"操作:{option} 说明:{detail} 参数:{actual_value} "
                    f"异常:{type(e).__name__} 详情:{str(e)}"
                )

                # 发送Markdown格式告警
                error_msg = f'''# <font color="warning">建群失败告警</font>
> **客户名称:** <font color="comment">{group_config.get('客户名称', 'N/A')}</font>
> **失败位置:** <font color="comment">第{idx + 1}条指令（共{len(command_df)}条）</font>
> **操作类型:** <font color="comment">{option}</font>
> **操作说明:** <font color="comment">{detail if detail else '无'}</font>
> **操作参数:** <font color="comment">{actual_value}</font>
> **异常类型:** <font color="warning">{type(e).__name__}</font>
> **发生时间:** <font color="comment">{time.strftime('%Y-%m-%d %H:%M:%S')}</font>'''

                send_wecom_robot_message(
                    content=error_msg,
                    webhook_url=WECOM_WEBHOOK_URL,
                    msg_type="markdown",
                    mentioned_mobile_list=[group_config.get('技术支持手机号'), '18852645418']
                )

                # 检查是否是风控导致的错误，如果队列已暂停则记录失败任务
                if is_queue_paused():
                    logging.warning("任务执行中检测到队列暂停（Redis风控），记录失败任务")
                    log_failed_task(group_config, str(e))

                # 重新抛出异常以终止工作流
                raise

        logging.info("工作流执行完毕")

    except FileNotFoundError:
        logging.error("指令文件不存在，路径：%s", os.path.abspath(EXCEL_PATH))
        raise

    finally:
        # 任务结束，清除执行状态（从Redis删除）
        set_task_running(False)
        logging.info("任务执行完毕（已从Redis清除执行标志）")


# Celery任务定义
@celery_app.task(name='automation_task', bind=True, max_retries=None)
def automation_task(self, group_config: dict):
    """
    RPA自动化任务

    Args:
        self: Celery任务实例（bind=True时可用）
        group_config: 任务配置

    Raises:
        QueuePausedException: 队列暂停时抛出，触发延迟重试
    """
    try:
        execute_workflow(group_config)
    except QueuePausedException as e:
        # 队列暂停，延迟重试
        logging.warning(f"队列暂停检测到，{TASK_RETRY_DELAY}秒后重试...")
        raise self.retry(exc=e, countdown=TASK_RETRY_DELAY, max_retries=None)


# API端点
@app.post("/start-automation", dependencies=[Depends(validate_api_key)])
async def start_automation(request: GroupConfigRequest):
    """
    启动自动化流程接口
    请求体示例：
    {
        "group_config": {
            "粘贴群成员": "测试成员",
            "粘贴群名称": "测试群"
        }
    }
    """
    task = automation_task.delay(request.group_config)
    return {
        "status": "任务已提交",
        "task_id": task.id,
        "monitor": f"/tasks/{task.id}"
    }

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = celery_app.AsyncResult(task_id)
    return {"status": task.status, "result": task.result}


@app.get("/resume-queue")
async def resume_queue_endpoint(token: str):
    """
    恢复暂停的队列

    Args:
        token: 恢复token（从风控告警消息中获取）

    Returns:
        成功或失败的消息
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少token参数"
        )

    # 检查token是否存在（用于区分过期和无效）
    stored_token = redis_client.get(RESUME_TOKEN_KEY)

    if not stored_token:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"恢复链接已过期（有效期：{RESUME_TOKEN_EXPIRE // 60}分钟），请联系管理员手动恢复队列"
        )

    success = resume_queue(token)

    if success:
        return {
            "status": "success",
            "message": "队列已成功恢复，后续任务将继续执行"
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token无效，请使用正确的恢复链接"
        )


if __name__ == "__main__":
    uvicorn.run(
        "RPA:app",
        host="0.0.0.0",
        port=8000,
        reload=True  # 开发模式热更新
    )
