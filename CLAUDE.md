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

2. **风控监听系统** (40-535行)
   - 后台线程持续检测 `./file/pictures/error.png`
   - 检测到风控时：截图保存 → 暂停队列 → 发送企微机器人告警 → 生成恢复链接

3. **队列状态管理** (47-67行)
   - Redis 键：`rpa:queue_paused`、`rpa:resume_token`、`rpa:task_running`
   - 跨进程状态共享

4. **动作执行系统** (137-305行)
   - `ACTION_MAP` 支持14种操作：左击图片、右击图片、左击坐标、粘贴、输入、快捷键、等待、激活企业微信、激活钉钉等
   - 图像识别置信度阈值：0.9

5. **工作流执行** (611-714行)
   - 读取 Excel 配置执行操作序列
   - 动态参数替换：Excel 的 option 列与 `group_config` 键匹配时自动替换值

6. **失败告警机制** (668-695行)
   - 任务失败时发送两条消息：
     1. **Markdown 消息** - 详细错误信息（客户名称、失败位置、操作类型、异常等）
     2. **Text 消息** - @ 技术支持（因 Markdown 不支持 `mentioned_mobile_list`）
   - Text 消息格式：`{客户名称}在「{操作说明}」过程中遇到问题，请对应技术支持及时处理`
   - @ 的手机号来自 `group_config.get('技术支持手机号')`

### API 端点

- `POST /start-automation` - 提交自动化任务
- `GET /tasks/{task_id}` - 查询任务状态
- `GET /resume-queue?token={token}` - 恢复暂停的队列

### 配置文件

- `./file/excel/cmd.xlsx` - 操作指令配置（sheet: 企微建群、钉钉建群）
- `./file/pictures/wxwork/` - 企微界面元素截图
- `./file/pictures/error.png` - 风控检测图片

### 日志文件

- `rpa.log` - 主日志（滚动，最大10MB，5个备份）
- `failed_tasks.log` - 失败任务记录（JSON格式）

## 关键配置常量

```python
CONFIDENCE = 0.9           # 图像识别置信度
CLICK_INTERVAL = 0.2       # 点击间隔(秒)
RETRY_TIMEOUT = 10         # 图像搜索超时(秒)
MONITOR_INTERVAL = 1       # 风控检测间隔(秒)
RESUME_TOKEN_EXPIRE = 3600 # 恢复令牌有效期(秒)
```

## 注意事项

- Celery Worker **必须**使用 `-P solo` 参数，确保任务串行执行防止竞态条件
- 截图必须与目标显示分辨率匹配
- 图像识别失败时，可尝试将 `CONFIDENCE` 降低到 0.8

## 测试文件

- `test_wecom_alert.py` - 企微告警消息单元测试（mock 模式，不发送真实请求）
- `test_real_send.py` - 真实发送测试（会发送实际消息到企微群）
