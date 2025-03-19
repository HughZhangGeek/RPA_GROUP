# coding=utf-8
import logging
import os
import time
from typing import Optional

import keyboard
import pandas as pd
import pyautogui
import pygetwindow as gw
import pyperclip
import uvicorn
from celery import Celery
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

# from functools import lru_cache

# API鉴权配置
API_KEYS = "eLKuNm0lwf6yohsgPOWq1GV3obPCP6Il"
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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

# Celery配置（需安装Redis）
celery_app = Celery('tasks', broker='redis://127.0.0.1:6379/0')
celery_app.conf.worker_concurrency = 1  # 关键：强制串行执行

# 固定Excel配置
EXCEL_PATH = "./file/excel/cmd.xlsx"  # 固定路径


class GroupConfigRequest(BaseModel):
    group_config: dict  # 动态传入的配置


# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

def data_update(_id):
    pass

def scroll_page(direction):
    """模拟 Page Down/Up 键"""
    if direction == "down":
        logging.info("滚动屏幕")
        pyautogui.press("pagedown")
    else:
        pyautogui.press("pageup")
    time.sleep(0.2)  # 添加延迟确保操作生效
# 核心执行逻辑改造
def execute_workflow(group_config: dict):
    """新版主工作流程"""
    try:
        logging.info(group_config['群类型'])
        if group_config['群类型'] == '企业微信群':
            command_df = pd.read_excel(EXCEL_PATH, sheet_name='企微建群')
        else:
            command_df = pd.read_excel(EXCEL_PATH, sheet_name='钉钉建群')
        logging.info(f"成功读取本地指令文件，共{len(command_df)}条指令")
        for idx, cmd in command_df.iterrows():
            option = cmd['option']
            value = str(cmd['value'])
            # 特殊粘贴处理逻辑
            if option in group_config:
                logging.info(f"[{idx + 1}/{len(command_df)}] 执行: {option} => {group_config[option]}")
                execute_command('粘贴', group_config[option])
            else:
                logging.info(f"[{idx + 1}/{len(command_df)}] 执行: {option} => {value}")
                execute_command(option, value)

    except FileNotFoundError:
        logging.error("指令文件不存在，路径：%s", os.path.abspath(EXCEL_PATH))
    except Exception as e:
        logging.error("工作流执行异常：%s", str(e))


# Celery任务定义
@celery_app.task(name='automation_task')
def automation_task(group_config: dict):
    execute_workflow(group_config)


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


if __name__ == "__main__":
    uvicorn.run(
        "RPA:app",
        host="127.0.0.1",
        port=8000,
        reload=True  # 开发模式热更新
    )
