# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

RPA 群聊自动化管理系统 - 基于 FastAPI + Celery + PyAutoGUI 的企业微信/钉钉群聊自动化工具。主要功能是自动化创建外部群，并具备风控监听和自动恢复机制。

## 启动命令

**前置条件：确保 Redis 服务运行中**

```bash
# 启动 FastAPI Web 服务器（终端1）
uvicorn RPA:app --host 0.0.0.0 --port 8000

# 启动 Celery Worker（终端2）
# 重要：必须使用 -P solo 保证任务串行执行
celery -A RPA:celery_app worker --loglevel=info -P solo
```

**诊断命令**
```bash
# 检查队列状态
python check_queue_status.py

# 检查 Celery worker
celery -A RPA:celery_app inspect active

# 清空 Redis 队列数据
redis-cli FLUSHDB
# 或只清空 RPA 相关数据
redis-cli KEYS "rpa:*" | xargs redis-cli DEL
redis-cli DEL celery
```

## 核心架构

### 主文件 RPA.py

1. **API 认证** (32-33行) - Header 认证方式：`X-API-Key: eLKuNm0lwf6yohsgPOWq1GV3obPCP6Il`

2. **服务器配置** (47-49行)
   - `SERVER_HOST` - 服务器外部访问 IP（用于生成恢复链接）
   - `SERVER_PORT` - 服务端口（默认 8000）

3. **自定义异常类** (77-87行)
   - `QueuePausedException` - 队列暂停异常，触发任务重试
   - `WorkflowException` - 工作流异常，包含 `error_type` 和 `error_detail` 属性

4. **风控监听系统** (39-714行)
   - 后台线程持续检测 `./file/pictures/error.png`
   - 检测到风控时：截图保存 → 暂停队列 → 发送企微机器人告警 → 生成恢复链接
   - 恢复链接使用 `SERVER_HOST` 配置，确保外部可访问

5. **队列状态管理** (51-62行)
   - Redis 键：`rpa:queue_paused`、`rpa:resume_token`、`rpa:task_running`、`rpa:task_history`、`rpa:task:{id}`
   - 跨进程状态共享
   - 任务历史保留最近 500 条，详情保留 3 天

6. **任务状态流转**
   - `pending` - 等待执行
   - `running` - 执行中
   - `success` - 成功完成
   - `failed` - 执行失败
   - `retried` - 已重试（原任务被重试后的状态）

7. **动作执行系统** (193-207行)
   - `ACTION_MAP` 支持12种操作：左击图片、右击图片、左击坐标、粘贴、输入、快捷键、等待、激活企业微信、激活钉钉、滚动屏幕等
   - 图像识别置信度阈值：0.9
   - 图片识别失败时会尝试两次（间隔2秒）

8. **工作流执行** (794-933行)
   - 读取 Excel 配置执行操作序列
   - 动态参数替换：Excel 的 option 列与 `group_config` 键匹配时自动替换值

9. **失败告警机制** (832-922行)
   - 任务失败时按顺序发送：
     1. **立即截图** - 在任何操作之前截取当前屏幕
     2. **Markdown 消息** - 详细错误信息（客户名称、失败位置、操作类型、异常等）
     3. **Text 消息** - @ 技术支持（因 Markdown 不支持 `mentioned_mobile_list`）
     4. **图片消息** - 发送异常页面截图
   - @ 的手机号来自 `group_config.get('技术支持手机号')`

10. **任务重复执行防护** (951-955行)
    - 任务开始时检查状态，若为 `success` 或 `retried` 则跳过执行
    - 防止队列恢复后历史任务重复执行

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/start-automation` | POST | 提交自动化任务（需 API Key） |
| `/tasks/{task_id}` | GET | 查询 Celery 任务状态 |
| `/resume-queue` | GET | 恢复暂停的队列（需 token） |
| `/queue-monitor` | GET | 队列监控页面（Web UI） |
| `/api/queue/stats` | GET | 获取队列统计信息 |
| `/api/queue/resume` | POST | 强制恢复队列（管理员，无需 token） |
| `/api/queue/history` | GET | 获取任务历史列表 |
| `/api/queue/task/{task_id}` | GET | 获取单个任务详情 |
| `/api/queue/task/{task_id}/retry` | POST | 重试失败任务 |

### 队列监控页面功能

访问 `/queue-monitor` 可查看：
- 队列状态统计（队列状态、任务执行中、等待中、成功、失败、队列长度）
- 任务历史列表（客户名称、群主、群名称、群类型、状态、时间、操作说明、异常类型、错误信息）
- 群主筛选功能
- 恢复队列按钮（队列暂停时显示）
- 重试按钮（满足以下条件时可用）：
  - 状态为 `failed` + 操作说明为"点击'+'创建群" + 异常类型为 `ImageNotFoundException` 或 `TimeoutError`
  - 或状态为 `pending` + 错误信息为"队列暂停，等待恢复"
  - 状态为 `retried` 时不可重试（防止重复重试）

### 配置文件

- `./file/excel/cmd.xlsx` - 操作指令配置（sheet: 企微建群、钉钉建群）
- `./file/pictures/wxwork/` - 企微界面元素截图
- `./file/pictures/error.png` - 风控检测图片

### 日志文件

- `rpa.log` - 主日志（滚动，最大10MB，5个备份）
- `failed_tasks.log` - 失败任务记录（JSON格式）

## 关键配置常量

```python
# 服务器配置
SERVER_HOST = '129.211.63.22'  # 服务器外部 IP（用于恢复链接）
SERVER_PORT = 8000             # 服务端口

# 图像识别配置
CONFIDENCE = 0.9               # 图像识别置信度
CLICK_INTERVAL = 0.2           # 点击间隔(秒)
RETRY_TIMEOUT = 10             # 图像搜索超时(秒)

# 风控监听配置
MONITOR_INTERVAL = 1           # 风控检测间隔(秒)
RESUME_TOKEN_EXPIRE = 3600     # 恢复令牌有效期(秒)

# 任务队列配置
TASK_RETRY_DELAY = 5           # 队列暂停时任务重试延迟(秒)
TASK_HISTORY_MAX = 500         # 保留最近500条历史记录
TASK_DETAIL_EXPIRE = 259200    # 任务详情保留3天(秒)
```

## Redis 数据结构

| Key | 类型 | 说明 |
|-----|------|------|
| `rpa:queue_paused` | String | 队列暂停标志 |
| `rpa:resume_token` | String | 恢复令牌 |
| `rpa:task_running` | String | 任务执行状态 |
| `rpa:task_history` | List | 任务ID列表 |
| `rpa:task:{task_id}` | Hash | 任务详情 |

任务详情 Hash 字段：
- `task_id`, `customer_name`, `owner_name`, `group_type`, `group_name`
- `status` (pending/running/success/failed/retried)
- `created_at`, `updated_at`
- `error_msg`, `error_type`, `error_detail`
- `config_json` - 原始请求配置（用于重试）

## 注意事项

- Celery Worker **必须**使用 `-P solo` 参数，确保任务串行执行防止竞态条件
- 截图必须与目标显示分辨率匹配
- 图像识别失败时，可尝试将 `CONFIDENCE` 降低到 0.8
- 修改 `SERVER_HOST` 后需重启服务才能生效

## 测试文件

- `test_wecom_alert.py` - 企微告警消息单元测试（mock 模式，不发送真实请求）
- `test_real_send.py` - 真实发送测试（会发送实际消息到企微群）