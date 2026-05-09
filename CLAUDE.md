# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

RPA 群聊自动化管理系统 - 基于 FastAPI + PyAutoGUI 的企业微信/钉钉群聊自动化工具。

**核心功能**：
- **自动建群** - 自动化创建外部群
- **群发消息** - 批量向多个群发送消息
- **风控监听** - 实时监控风控并自动恢复
- **队列管理** - 任务队列暂停/恢复、重试机制
- **Web 监控** - 实时查看任务状态和历史

**技术栈**：
- **Web 框架**: FastAPI + Uvicorn
- **RPA 自动化**: PyAutoGUI + 图像识别
- **数据存储**: SQLite（替代 Redis）
- **后台任务**: 自定义 Worker 线程（替代 Celery）
- **集成**: 企业微信 Webhook 通知

## 快速开始

### Windows 用户

双击 `start.bat` 即可启动服务。

### Linux/Mac 用户

```bash
chmod +x start_linux.sh
./start_linux.sh
```

### 手动启动

```bash
# 激活 Conda 环境
conda activate RPA_GROUP

# 启动服务
uvicorn RPA:app --host 0.0.0.0 --port 8000
```

**访问地址**：
- API 文档: http://127.0.0.1:8000/docs
- 队列监控: http://127.0.0.1:8000/queue-monitor

### 诊断命令

```bash
# 查看任务历史（SQLite）
sqlite3 rpa.db "SELECT task_id, task_type, status, customer_name, created_at FROM tasks ORDER BY created_at DESC LIMIT 20;"

# 查看队列状态
sqlite3 rpa.db "SELECT * FROM queue_state;"

# 重置卡住的 running 任务
sqlite3 rpa.db "UPDATE tasks SET status='pending' WHERE status='running';"

# 检查队列状态 API
curl http://127.0.0.1:8000/api/queue/stats
```

## 核心架构

```
FastAPI 进程（单进程）
├── HTTP 服务（主线程）         ← 接收 API 请求
├── 队列 Worker（后台线程）     ← 串行执行任务
└── 风控监听（后台线程）        ← 检测 error.png
         ↕
      SQLite（rpa.db）          ← 任务存储 + 队列控制
```

### 模块说明

| 文件 | 职责 |
|------|------|
| `RPA.py` | FastAPI 应用、API 端点、RPA 核心执行逻辑 |
| `database.py` | SQLite 数据层（建表、任务 CRUD、队列控制） |
| `queue_worker.py` | 后台 Worker 线程，串行取出 pending 任务执行 |
| `config.py` | 从 `.env` 读取所有配置常量（**不入 Git**） |
| `.env` | 敏感配置（API Key、Webhook URL 等，**不入 Git**） |

### 主文件 RPA.py

1. **API 认证** - Header 认证方式：`X-API-Key`，值从 `config.py` 读取

2. **服务器配置**（在 `.env` 中修改）
   - `SERVER_HOST` - 服务器外部访问 IP（用于生成风控恢复链接）
   - `SERVER_PORT` - 服务端口（默认 8000）

3. **自定义异常类**
   - `QueuePausedException` - 队列暂停异常
   - `WorkflowException` - 工作流异常，包含 `error_type` 和 `error_detail` 属性

4. **风控监听系统**
   - 后台线程持续检测 `./file/pictures/error.png`
   - 检测到风控时：截图保存 → 暂停队列（写 SQLite）→ 发送企微机器人告警 → 生成恢复链接
   - 恢复链接使用 `SERVER_HOST` 配置，确保外部可访问

5. **队列状态管理**（存储在 SQLite `queue_state` 表）
   - `queue_paused` - 队列暂停标志
   - `resume_token` - 恢复令牌（带过期时间）
   - 任务状态通过 `tasks` 表的 `status` 字段跟踪

6. **任务状态流转**
   - `pending` - 等待执行
   - `running` - 执行中
   - `success` - 成功完成
   - `failed` - 执行失败
   - `retried` - 已重试（原任务被重试后的状态）
   - `group_not_found` - 群不存在（仅群发消息任务）

7. **动作执行系统**
   - `ACTION_MAP` 支持12种操作：左击图片、右击图片、左击坐标、粘贴、输入、快捷键、等待、激活企业微信、激活钉钉、滚动屏幕等
   - 图像识别置信度阈值：0.9（可在 config.py 调整）
   - 图片识别失败时会尝试两次（间隔2秒）

8. **工作流执行**
   - `execute_workflow()` - 建群工作流，读取 Excel "企微建群"/"钉钉建群" sheet
   - `execute_send_message_workflow()` - 发消息工作流，读取 Excel "企微发消息"/"钉钉发消息" sheet
   - 动态参数替换：Excel 的 option 列与配置键匹配时自动替换值

9. **失败告警机制**（仅建群任务）
   - 任务失败时按顺序发送：
     1. **立即截图** - 在任何操作之前截取当前屏幕
     2. **Markdown 消息** - 详细错误信息（客户名称、失败位置、操作类型、异常等）
     3. **Text 消息** - @ 技术支持（因 Markdown 不支持 `mentioned_mobile_list`）
     4. **图片消息** - 发送异常页面截图
   - @ 的手机号来自 `group_config.get('技术支持手机号')`
   - **注意**：群发消息任务失败不发送告警，仅记录状态

10. **启动恢复机制**
    - 服务启动时自动将上次 `running` 状态的任务重置为 `pending`
    - Worker 线程重新取出并执行，无需人工干预

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/start-automation` | POST | 提交建群任务（需 API Key） |
| `/send-message` | POST | 提交群发消息任务（需 API Key） |
| `/resume-queue` | GET | 恢复暂停的队列（需 token） |
| `/queue-monitor` | GET | 队列监控页面（Web UI，支持 Tab 切换） |
| `/api/queue/stats` | GET | 获取队列统计信息（支持 task_type 参数） |
| `/api/queue/resume` | POST | 强制恢复队列（管理员，无需 token） |
| `/api/queue/history` | GET | 获取任务历史列表（支持 task_type 参数） |
| `/api/queue/task/{task_id}` | GET | 获取单个任务详情 |
| `/api/queue/task/{task_id}/retry` | POST | 重试失败任务 |

### 队列监控页面功能

访问 `/queue-monitor` 可查看：
- **Tab 切换** - 建群任务 / 群发消息 分开展示
- 队列状态统计（队列状态、任务执行中、等待中、成功、失败、群不存在、待执行数）
- 任务历史列表
- 筛选功能（建群按群主筛选，发消息按客户筛选）
- 恢复队列按钮（队列暂停时显示）
- 重试按钮

### 配置文件

- `.env` - 敏感配置（API Key、Webhook URL、服务器 IP 等，**不入 Git，需在服务器手动创建**）
- `config.py` - 读取 .env 的配置模块（**不入 Git**）
- `./file/excel/cmd.xlsx` - 操作指令配置
  - sheet: 企微建群、钉钉建群（建群流程）
  - sheet: 企微发消息、钉钉发消息（发消息流程）
- `./file/pictures/wxwork/` - 企微界面元素截图
- `./file/pictures/error.png` - 风控检测图片
- `./file/pictures/group_not_found.png` - 群不存在检测图片
- `templates/queue_monitor.html` - 监控页面模板

### SQLite 数据结构

**tasks 表**（任务存储）

| 字段 | 说明 |
|------|------|
| `task_id` | 任务唯一ID（uuid4） |
| `task_type` | 任务类型（create_group / send_message） |
| `status` | 任务状态（pending/running/success/failed/retried/group_not_found） |
| `customer_name` | 客户名称 |
| `owner_name` | 群主姓名（建群任务） |
| `group_type` | 群类型（企微群/钉钉群） |
| `group_name` | 群名称（建群任务） |
| `target_group` | 目标群名称（发消息任务） |
| `message_content` | 消息内容（发消息任务） |
| `paas_id` / `user_id` | 外部系统关联ID（发消息任务） |
| `error_msg` / `error_type` / `error_detail` | 错误信息 |
| `config_json` | 原始请求配置（用于重试） |
| `created_at` / `updated_at` | 时间戳 |

**queue_state 表**（队列控制）

| key | 说明 |
|-----|------|
| `queue_paused` | 队列暂停标志（value='1'） |
| `resume_token` | 恢复令牌（带 expires_at） |

### 日志文件

- `rpa.db` - SQLite 数据库，包含全部任务历史（永久保存）
- `rpa.log` - 主日志（滚动，最大10MB，5个备份）
- `failed_tasks.log` - 失败任务记录（JSON格式）
- `./file/pictures/error_shots/` - 风控截图（时间戳命名）

## 关键配置常量

所有常量在 `.env` 中配置，通过 `config.py` 读取：

```ini
API_KEY=...                  # API 鉴权 Key
WECOM_WEBHOOK_URL=...        # 企微机器人 Webhook
SERVER_HOST=129.211.63.22   # 服务器外网 IP（用于恢复链接）
SERVER_PORT=8000
RESUME_TOKEN_EXPIRE=3600    # 恢复令牌有效期(秒)
DB_PATH=./rpa.db            # SQLite 数据库路径
TASK_RETRY_DELAY=5          # 队列暂停时轮询间隔(秒)
MONITOR_INTERVAL=1          # 风控检测间隔(秒)
```

图像识别相关常量在 `config.py` 中硬编码：
```python
CONFIDENCE = 0.9     # 图像识别置信度（识别失败时可调低至 0.8）
CLICK_INTERVAL = 0.2
RETRY_TIMEOUT = 10
```

## 注意事项

- 服务器上必须手动创建 `.env` 和 `config.py`，这两个文件不入 Git
- 截图必须与目标显示分辨率匹配
- 图像识别失败时，可尝试将 `CONFIDENCE` 降低到 0.8
- 修改 `.env` 后需重启服务才能生效
- 群发消息任务失败不发送企微告警，仅记录状态到 SQLite
- Worker 线程是单线程串行执行，同一时间只处理一个任务

## 测试文件

- `test_wecom_alert.py` - 企微告警消息单元测试（mock 模式，不发送真实请求）
- `test_real_send.py` - 真实发送测试（会发送实际消息到企微群）
- `test_send_message.http` - HTTP 接口测试文件