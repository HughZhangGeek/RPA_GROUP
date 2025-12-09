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
```

## 核心架构

### 主文件 RPA.py

1. **API 认证** (32-81行) - Header 认证方式：`X-API-Key: eLKuNm0lwf6yohsgPOWq1GV3obPCP6Il`

2. **自定义异常类** (72-83行)
   - `QueuePausedException` - 队列暂停异常，触发任务重试
   - `WorkflowException` - 工作流异常，包含 `error_type` 和 `error_detail` 属性

3. **风控监听系统** (40-710行)
   - 后台线程持续检测 `./file/pictures/error.png`
   - 检测到风控时：截图保存 → 暂停队列 → 发送企微机器人告警 → 生成恢复链接

4. **队列状态管理** (47-67行)
   - Redis 键：`rpa:queue_paused`、`rpa:resume_token`、`rpa:task_running`、`rpa:task_history`、`rpa:task:{id}`
   - 跨进程状态共享
   - 任务历史保留最近 500 条，详情保留 3 天

5. **动作执行系统** (189-364行)
   - `ACTION_MAP` 支持12种操作：左击图片、右击图片、左击坐标、粘贴、输入、快捷键、等待、激活企业微信、激活钉钉、滚动屏幕等
   - 图像识别置信度阈值：0.9
   - 图片识别失败时会尝试两次（间隔2秒）

6. **工作流执行** (790-929行)
   - 读取 Excel 配置执行操作序列
   - 动态参数替换：Excel 的 option 列与 `group_config` 键匹配时自动替换值

7. **失败告警机制** (828-918行)
   - 任务失败时按顺序发送三条消息：
     1. **立即截图** - 在任何操作之前截取当前屏幕
     2. **Markdown 消息** - 详细错误信息（客户名称、失败位置、操作类型、异常等）
     3. **Text 消息** - @ 技术支持（因 Markdown 不支持 `mentioned_mobile_list`）
     4. **图片消息** - 发送异常页面截图
   - @ 的手机号来自 `group_config.get('技术支持手机号')`

### API 端点

- `POST /start-automation` - 提交自动化任务
- `GET /tasks/{task_id}` - 查询任务状态
- `GET /resume-queue?token={token}` - 恢复暂停的队列
- `GET /queue-monitor` - 队列监控页面（Web UI）
- `GET /api/queue/stats` - 获取队列统计信息
- `GET /api/queue/history` - 获取任务历史列表
- `GET /api/queue/task/{task_id}` - 获取单个任务详情
- `POST /api/queue/task/{task_id}/retry` - 重试失败任务

### 队列监控页面功能

访问 `/queue-monitor` 可查看：
- 队列状态统计（队列状态、任务执行中、等待中、成功、失败、队列长度）
- 任务历史列表（客户名称、群主、群名称、群类型、状态、时间、操作说明、异常类型、错误信息）
- 群主筛选功能
- 重试按钮（仅在特定条件下可用：状态失败 + 操作说明为"点击'+'创建群" + 异常类型为 ImageNotFoundException）

### 配置文件

- `./file/excel/cmd.xlsx` - 操作指令配置（sheet: 企微建群、钉钉建群）
- `./file/pictures/wxwork/` - 企微界面元素截图
- `./file/pictures/error.png` - 风控检测图片

### 日志文件

- `rpa.log` - 主日志（滚动，最大10MB，5个备份）
- `failed_tasks.log` - 失败任务记录（JSON格式）

## 关键配置常量

```python
CONFIDENCE = 0.9             # 图像识别置信度
CLICK_INTERVAL = 0.2         # 点击间隔(秒)
RETRY_TIMEOUT = 10           # 图像搜索超时(秒)
MONITOR_INTERVAL = 1         # 风控检测间隔(秒)
RESUME_TOKEN_EXPIRE = 3600   # 恢复令牌有效期(秒)
TASK_HISTORY_MAX = 500       # 保留最近500条历史记录
TASK_DETAIL_EXPIRE = 259200  # 任务详情保留3天(秒)
```

## Redis 数据结构

- `rpa:queue_paused` - 队列暂停标志
- `rpa:resume_token` - 恢复令牌
- `rpa:task_running` - 任务执行状态
- `rpa:task_history` - 任务ID列表（List）
- `rpa:task:{task_id}` - 任务详情（Hash），包含字段：
  - `task_id`, `customer_name`, `owner_name`, `group_type`, `group_name`
  - `status`, `created_at`, `updated_at`
  - `error_msg`, `error_type`, `error_detail`
  - `config_json` - 原始请求配置（用于重试）

## 注意事项

- Celery Worker **必须**使用 `-P solo` 参数，确保任务串行执行防止竞态条件
- 截图必须与目标显示分辨率匹配
- 图像识别失败时，可尝试将 `CONFIDENCE` 降低到 0.8

## 测试文件

- `test_wecom_alert.py` - 企微告警消息单元测试（mock 模式，不发送真实请求）
- `test_real_send.py` - 真实发送测试（会发送实际消息到企微群）
