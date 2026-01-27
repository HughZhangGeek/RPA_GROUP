# RPA 群聊自动化管理系统

基于 FastAPI + Celery + PyAutoGUI 实现的跨平台群聊自动化管理工具，支持企业微信/钉钉自动建群和群发消息操作。

## 特性

- **RESTful API** - 通过 HTTP API 触发自动化流程
- **安全鉴权** - 基于 API Key 的安全认证机制
- **灵活配置** - Excel 指令集配置，支持多模板动态切换
- **智能操作** - 图像识别点击、坐标点击、快捷键、窗口激活等
- **异步队列** - Celery 分布式任务队列支持
- **风控监控** - 实时监听风控图片，自动暂停并告警
- **完善日志** - 轮转日志记录，任务状态追踪
- **自动恢复** - 风控处理后可通过链接恢复队列执行
- **任务重试** - 支持失败任务一键重试
- **队列监控** - Web 监控页面实时查看任务状态（支持 Tab 切换）
- **群发消息** - 批量向多个群发送消息，自动跳过不存在的群

## 系统架构

```
┌─────────────┐      HTTP      ┌──────────────┐
│   API 调用   │ ────────────> │  FastAPI     │
└─────────────┘                │  (Web 服务)   │
                               └──────┬───────┘
                                      │ 提交任务
                                      ↓
                               ┌──────────────┐
                               │   Redis      │
                               │  (消息队列)   │
                               └──────┬───────┘
                                      │ 消费任务
                                      ↓
                               ┌──────────────┐
                               │   Celery     │
                               │  (任务执行器)  │
                               └──────┬───────┘
                                      │ 执行
                                      ↓
                               ┌──────────────┐
                               │  PyAutoGUI   │
                               │  (UI 自动化)  │
                               └──────────────┘
```

## 快速开始

### 环境要求

- Python 3.8+
- Redis Server
- Windows 系统（需安装企业微信/钉钉客户端）

### 安装步骤

1. 克隆项目

```bash
git clone https://github.com/HughZhangGeek/RPA_GROUP.git
cd RPA_GROUP
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 启动 Redis 服务

```bash
# Windows: 下载并运行 Redis
# Linux/Mac:
redis-server
```

4. 配置服务器地址

编辑 `RPA.py`，修改服务器配置（用于生成外部可访问的恢复链接）：

```python
# 服务器配置（用于生成外部可访问的链接）
SERVER_HOST = '你的服务器IP'  # 修改为实际 IP 地址
SERVER_PORT = 8000
```

5. 准备配置文件

- 编辑 `./file/excel/cmd.xlsx` 配置指令集
- 准备目标图片到 `./file/pictures/` 目录

6. 启动服务

在**两个独立的终端**中分别运行：

```bash
# 终端 1: 启动 FastAPI Web 服务
uvicorn RPA:app --host 0.0.0.0 --port 8000

# 终端 2: 启动 Celery Worker
celery -A RPA:celery_app worker --loglevel=info -P solo
```

## API 文档

### 1. 提交建群任务

**端点**: `POST /start-automation`

**请求头**:
```http
X-API-Key: eLKuNm0lwf6yohsgPOWq1GV3obPCP6Il
Content-Type: application/json
```

**请求体**:
```json
{
  "group_config": {
    "客户名称": "测试客户",
    "群类型": "企微群",
    "粘贴群成员": "外部群专员 测试成员1 测试成员2",
    "粘贴群名称": "企业微信自动建群测试",
    "粘贴群描述": "群聊",
    "粘贴@后的名字": "sales",
    "技术支持手机号": "18812345678"
  }
}
```

**响应示例**:
```json
{
  "status": "任务已提交",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "monitor": "/tasks/550e8400-e29b-41d4-a716-446655440000"
}
```

### 2. 提交群发消息任务

**端点**: `POST /send-message`

**请求头**:
```http
X-API-Key: eLKuNm0lwf6yohsgPOWq1GV3obPCP6Il
Content-Type: application/json
```

**请求体**:
```json
{
  "group_configs": [
    {
      "客户名称": "客户A",
      "paas_id": "paas_001",
      "user_id": "user_001",
      "群类型": "企微群",
      "目标群名称": "项目沟通群",
      "消息内容": "大家好，这是通知消息"
    },
    {
      "客户名称": "客户B",
      "paas_id": "paas_002",
      "user_id": "user_002",
      "群类型": "企微群",
      "目标群名称": "售后服务群",
      "消息内容": "这是另一条消息"
    }
  ]
}
```

**响应示例**:
```json
{
  "status": "任务已提交",
  "total": 2,
  "tasks": [
    {"task_id": "xxx-1", "target_group": "项目沟通群"},
    {"task_id": "xxx-2", "target_group": "售后服务群"}
  ]
}
```

**群发消息特性**:
- 支持批量发送到多个群
- 群不存在时自动跳过，记录状态为 `group_not_found`
- 单个群失败不影响其他群的发送
- 失败不发送企微告警，仅记录状态
- `paas_id` 和 `user_id` 用于关联外部系统

### 3. 查询任务状态

**端点**: `GET /tasks/{task_id}`

**响应示例**:
```json
{
  "status": "SUCCESS",
  "result": null
}
```

**状态说明**:
- `PENDING`: 任务等待执行
- `STARTED`: 任务开始执行
- `SUCCESS`: 任务成功完成
- `FAILURE`: 任务执行失败
- `RETRY`: 任务重试中

### 3. 恢复暂停队列

**端点**: `GET /resume-queue?token={token}`

**参数**:
- `token`: 从风控告警消息中获取的恢复令牌

**响应示例**:
```json
{
  "status": "success",
  "message": "队列已成功恢复，后续任务将继续执行"
}
```

### 4. 队列监控页面

**端点**: `GET /queue-monitor`

访问该端点可打开 Web 监控界面，功能包括：
- **Tab 切换** - 建群任务 / 群发消息 分开展示
- **统计卡片** - 队列状态、任务执行中、等待中、成功、失败、群不存在（仅群发消息）、队列长度
- **恢复队列按钮** - 队列暂停时显示，可强制恢复队列
- **任务历史列表** - 根据任务类型显示不同列
- **筛选功能** - 建群按群主筛选，群发消息按客户筛选
- **重试按钮** - 失败任务可一键重试
- **自动刷新** - 默认每 5 秒自动刷新数据

### 5. 队列监控 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/queue/stats` | GET | 获取队列统计信息（支持 `task_type` 参数） |
| `/api/queue/resume` | POST | 强制恢复队列（管理员，无需 token） |
| `/api/queue/history` | GET | 获取任务历史（支持 `limit`/`offset`/`task_type` 参数） |
| `/api/queue/task/{task_id}` | GET | 获取单个任务详情 |
| `/api/queue/task/{task_id}/retry` | POST | 重试失败任务 |

**task_type 参数值**:
- `create_group` - 建群任务
- `send_message` - 群发消息任务
- 不传 - 返回所有任务

## 任务状态说明

| 状态 | 说明 |
|------|------|
| `pending` | 等待执行 |
| `running` | 执行中 |
| `success` | 成功完成 |
| `failed` | 执行失败 |
| `retried` | 已重试（原任务状态，表示已生成新任务） |
| `group_not_found` | 群不存在（仅群发消息任务） |

## 配置说明

### Excel 指令文件格式

文件路径: `./file/excel/cmd.xlsx`

**Sheet 名称**:
- `企微建群` - 企业微信建群流程
- `钉钉建群` - 钉钉建群流程
- `企微发消息` - 企业微信群发消息流程
- `钉钉发消息` - 钉钉群发消息流程

**列结构**:
| 列名 | 说明 | 示例 |
|------|------|------|
| option | 操作类型 | 左击图片、粘贴、快捷键 |
| value | 操作参数 | /images/button.png、文本内容 |
| detail | 操作说明（可选） | 点击创建群聊按钮 |

### 支持的操作类型

| 操作类型 | value 示例 | 说明 |
|---------|-----------|------|
| 左击图片 | ./file/pictures/button.png | 识别图片并左键点击 |
| 右击图片 | ./file/pictures/menu.png | 识别图片并右键点击 |
| 左击坐标 | 100,200 | 点击屏幕坐标 (x,y) |
| 快捷键 | ctrl+v | 执行组合键 |
| 粘贴 | 文本内容 | 复制到剪贴板并粘贴 |
| 输入 | 文本内容 | 逐字输入文本 |
| 等待 | 2 | 等待指定秒数 |
| 检查图片是否存在 | ./file/pictures/confirm.png | 返回布尔值 |
| 检查群是否存在 | (无需value) | 群发消息专用，检测群不存在图片 |
| 激活企业微信 | C:/WXWork.lnk | 激活窗口或启动快捷方式 |
| 激活钉钉 | C:/DingTalk.lnk | 激活窗口或启动快捷方式 |
| 滚动屏幕 | down | 模拟 Page Down 按键 |

### 动态配置替换

在 Excel 中使用 `option` 列作为占位符，系统会自动从请求体中提取对应值：

#### 建群任务示例

**Excel 配置**:
```
option: 粘贴群名称
value: (留空)
```

**API 请求**:
```json
{
  "group_config": {
    "粘贴群名称": "实际的群名称"
  }
}
```

系统将自动执行粘贴操作，内容为 "实际的群名称"。

#### 群发消息任务示例

**Excel 配置** (Sheet: 企微发消息/钉钉发消息):
| option | value | detail |
|--------|-------|--------|
| 目标群名称 | (留空) | 粘贴目标群名称进行搜索 |
| 检查群是否存在 | (留空) | 检测群不存在图片 |
| 消息内容 | (留空) | 粘贴要发送的消息 |

**API 请求**:
```json
{
  "group_configs": [
    {
      "目标群名称": "项目沟通群",
      "消息内容": "大家好，这是通知消息"
    }
  ]
}
```

系统会自动将 `目标群名称` 和 `消息内容` 的值替换到对应的粘贴操作中。

**特殊操作说明**:
- `检查群是否存在`: 此操作会检测 `group_not_found.png` 图片是否出现，若出现则判定群不存在，自动按 ESC 退出并跳过该群

## 失败告警机制

当任务执行失败时，系统会按顺序发送以下企业微信消息：

### 1. 立即截图
在任何操作之前，立即截取当前屏幕并保存到 `./file/pictures/error_shots/`

### 2. Markdown 详情消息
包含完整的错误上下文信息：
- 客户名称、失败位置、操作类型
- 操作说明、操作参数、异常类型
- 发生时间

### 3. Text 消息 @ 技术支持
由于企业微信 Markdown 消息不支持 `mentioned_mobile_list`，额外发送一条 Text 消息：
- 格式：`{客户名称}在「{操作说明}」过程中遇到问题，请对应技术支持及时处理`
- 自动 @ `group_config` 中的 `技术支持手机号`

### 4. 异常页面截图
发送第一步截取的屏幕截图到企微群，便于技术人员快速定位问题

## 风控监控机制

### 工作原理

系统会持续监听屏幕上是否出现风控图片（`./file/pictures/error.png`），检测到后自动执行：

1. **截图保存** - 保存风控截图到 `./file/pictures/error_shots/`
2. **暂停队列** - 停止后续任务执行，生成恢复令牌
3. **企微告警** - 发送截图和恢复链接到企业微信群
4. **等待恢复** - 管理员处理风控后点击链接或通过监控页面恢复队列

### 恢复流程

**方式一：通过链接恢复**
1. 收到企业微信告警消息
2. 手动处理风控问题（扫码验证等）
3. 点击告警消息中的恢复链接
4. 系统自动恢复任务队列执行

**方式二：通过监控页面恢复**
1. 访问 `/queue-monitor` 监控页面
2. 点击"恢复队列"按钮
3. 系统立即恢复任务队列执行

### 配置参数

```python
SERVER_HOST = '129.211.63.22'              # 服务器 IP（用于恢复链接）
SERVER_PORT = 8000                          # 服务端口
ERROR_IMAGE_PATH = './file/pictures/error.png'  # 风控图片路径
MONITOR_INTERVAL = 1                        # 监听间隔（秒）
RESUME_TOKEN_EXPIRE = 3600                  # 恢复令牌有效期（秒）
TASK_RETRY_DELAY = 5                        # 队列暂停时任务重试延迟（秒）
```

## 项目结构

```
RPA_GROUP/
├── RPA.py                      # 主程序文件
├── ReadMe.md                   # 项目文档
├── CLAUDE.md                   # Claude Code 开发指南
├── requirements.txt            # 依赖列表
├── rpa.log                     # 运行日志
├── failed_tasks.log            # 失败任务日志
├── templates/
│   └── queue_monitor.html     # 监控页面模板
├── file/
│   ├── excel/
│   │   └── cmd.xlsx           # 指令配置文件
│   └── pictures/
│       ├── error.png          # 风控监听图片
│       ├── group_not_found.png # 群不存在检测图片
│       ├── error_shots/       # 风控截图目录
│       └── wxwork/            # 企业微信相关图片
└── uvicorn.log                # Web 服务日志
```

## 注意事项

### 1. 安全配置

- 修改默认 API Key（RPA.py:32）
- 生产环境关闭 reload 模式
- 配置 Redis 访问密码

### 2. 服务器配置

- 修改 `SERVER_HOST` 为服务器实际 IP 地址
- 确保防火墙开放 8000 端口
- 修改配置后需重启服务

### 3. 图像识别

- 屏幕分辨率需与截图图片一致
- 调整 `CONFIDENCE`（RPA.py:187）平衡识别精度/速度
- 企业微信/钉钉版本需与操作逻辑匹配
- 图片识别失败时会自动重试一次（间隔 2 秒）

### 4. 性能调优

- 修改 `CLICK_INTERVAL` 调整操作速度
- 修改 `RETRY_TIMEOUT` 调整图片查找超时
- Celery worker 并发数建议设置为 1（串行执行）

### 5. 调试建议

- 查看 `rpa.log` 了解详细执行日志
- 使用 `failed_tasks.log` 追踪失败任务
- 监控 Celery worker 输出排查任务异常
- 访问 `/queue-monitor` 实时查看任务状态

## 常见问题

### Q1: 提示 "未找到目标图像"

**原因**: 图片路径错误或屏幕分辨率不匹配

**解决**:
- 检查图片文件是否存在
- 使用当前分辨率重新截图
- 降低 `CONFIDENCE` 值（如 0.8）

### Q2: 任务一直处于 PENDING 状态

**原因**: Celery Worker 未启动或 Redis 连接失败

**解决**:
```bash
# 检查 Redis 是否运行
redis-cli ping

# 检查 Celery Worker 是否启动
celery -A RPA:celery_app inspect active
```

### Q3: 风控监听不生效

**原因**: `error.png` 文件不存在或置信度设置过高

**解决**:
- 确保 `./file/pictures/error.png` 存在
- 截取实际风控界面的图片
- 检查日志中是否有 "风控监听线程已启动" 消息

### Q4: API 返回 401 Unauthorized

**原因**: API Key 错误或缺失

**解决**:
```bash
# 正确的请求示例
curl -X POST http://localhost:8000/start-automation \
  -H "X-API-Key: eLKuNm0lwf6yohsgPOWq1GV3obPCP6Il" \
  -H "Content-Type: application/json" \
  -d '{"group_config": {...}}'
```

### Q5: 恢复链接点击无反应

**原因**: `SERVER_HOST` 配置不正确

**解决**:
- 修改 `RPA.py` 中的 `SERVER_HOST` 为服务器实际 IP
- 确保该 IP 可以从外部访问
- 检查防火墙是否开放 8000 端口
- 重启 FastAPI 服务

### Q6: 队列恢复后任务重复执行

**原因**: 队列暂停期间积累的任务在恢复后可能重复触发

**解决**: 系统已自动处理，任务开始时会检查状态，若为 `success` 或 `retried` 则跳过执行

## 技术栈

- **Web 框架**: FastAPI 0.100+
- **任务队列**: Celery 5.3+
- **消息代理**: Redis 4.5+
- **UI 自动化**: PyAutoGUI 0.9+
- **窗口管理**: PyGetWindow 0.0.9+
- **数据处理**: Pandas 2.0+

## 开发计划

- [ ] 支持更多 IM 平台（飞书、Slack）
- [x] Web 管理界面
- [ ] 任务执行录像回放
- [ ] 分布式多机部署支持
- [ ] OCR 文字识别功能

## 许可证

MIT License

## 联系方式

- 作者: Hugh Zhang
- GitHub: [HughZhangGeek/RPA_GROUP](https://github.com/HughZhangGeek/RPA_GROUP)

## 更新日志

### v4.5 (当前版本)
- 新增群发消息功能（`POST /send-message`）
- 支持批量向多个群发送消息
- 群不存在时自动跳过，记录状态为 `group_not_found`
- 监控页面新增 Tab 切换（建群任务 / 群发消息）
- 监控页面模板外置到 `templates/queue_monitor.html`
- Redis 存储配置优化：历史记录永久保存（1GB 约可存 70 万条）
- 新增 `paas_id`、`user_id` 字段用于关联外部系统

### v4.4
- 新增服务器配置（`SERVER_HOST`/`SERVER_PORT`）：恢复链接使用可配置的外部 IP
- 新增强制恢复队列 API（`/api/queue/resume`）：监控页面可无需 token 恢复队列
- 新增任务重复执行防护：队列恢复后自动跳过已完成或已重试的任务
- 新增 `retried` 任务状态：重试后原任务标记为已重试，防止重复操作
- 优化重试按钮条件：支持 `ImageNotFoundException` 和 `TimeoutError` 两种异常类型
- 优化队列暂停重试延迟：从 30 秒缩短为 5 秒

### v4.3
- 新增异常页面截图功能：任务失败时自动截图并发送到企微群
- 失败告警流程优化：截图 → Markdown详情 → @技术支持 → 发送截图

### v4.2
- 新增队列监控页面 `/queue-monitor`
- 新增任务重试功能（支持特定条件下的一键重试）
- 新增群主筛选功能
- Redis 存储优化：保留最近 500 条记录，详情保留 3 天
- 新增 `WorkflowException` 自定义异常，携带 `error_type` 和 `error_detail`

### v4.1
- 优化失败告警通知：Markdown 详情 + Text 消息 @ 技术支持
- 新增 `技术支持手机号` 配置，失败时自动 @ 对应技术支持

### v4.0
- 新增风控监控和自动恢复机制
- 优化 Celery 任务重试逻辑
- 改进日志系统（轮转日志）
- 添加任务执行状态查询接口

### v3.0
- 添加日志组件
- 实现任务执行情况查询

### v2.0
- 基础 RPA 功能实现
- Excel 配置支持