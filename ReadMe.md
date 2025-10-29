# RPA 群聊自动化管理系统

基于 FastAPI + Celery + PyAutoGUI 实现的跨平台群聊自动化管理工具，支持企业微信/钉钉自动建群操作。

## 特性

- **RESTful API** - 通过 HTTP API 触发自动化流程
- **安全鉴权** - 基于 API Key 的安全认证机制
- **灵活配置** - Excel 指令集配置，支持多模板动态切换
- **智能操作** - 图像识别点击、坐标点击、快捷键、窗口激活等
- **异步队列** - Celery 分布式任务队列支持
- **风控监控** - 实时监听风控图片，自动暂停并告警
- **完善日志** - 轮转日志记录，任务状态追踪
- **自动恢复** - 风控处理后可通过链接恢复队列执行

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

4. 准备配置文件

- 编辑 `./file/excel/cmd.xlsx` 配置指令集
- 准备目标图片到 `./file/pictures/` 目录

5. 启动服务

在**两个独立的终端**中分别运行：

```bash
# 终端 1: 启动 FastAPI Web 服务
uvicorn RPA:app --host 0.0.0.0 --port 8000

# 终端 2: 启动 Celery Worker
celery -A RPA:celery_app worker --loglevel=info -P solo
```

## API 文档

### 1. 提交自动化任务

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

### 2. 查询任务状态

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

## 配置说明

### Excel 指令文件格式

文件路径: `./file/excel/cmd.xlsx`

**Sheet 名称**:
- `企微建群` - 企业微信建群流程
- `钉钉建群` - 钉钉建群流程

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
| 激活企业微信 | C:/WXWork.lnk | 激活窗口或启动快捷方式 |
| 激活钉钉 | C:/DingTalk.lnk | 激活窗口或启动快捷方式 |
| 滚动屏幕 | down | 模拟 Page Down 按键 |

### 动态配置替换

在 Excel 中使用 `option` 列作为占位符，系统会自动从 `group_config` 中提取对应值：

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

## 风控监控机制

### 工作原理

系统会持续监听屏幕上是否出现风控图片（`./file/pictures/error.png`），检测到后自动执行：

1. **截图保存** - 保存风控截图到 `./file/pictures/error_shots/`
2. **暂停队列** - 停止后续任务执行，生成恢复令牌
3. **企微告警** - 发送截图和恢复链接到企业微信群
4. **等待恢复** - 管理员处理风控后点击链接恢复队列

### 恢复流程

1. 收到企业微信告警消息
2. 手动处理风控问题（扫码验证等）
3. 点击告警消息中的恢复链接
4. 系统自动恢复任务队列执行

### 配置参数

```python
ERROR_IMAGE_PATH = './file/pictures/error.png'      # 风控图片路径
MONITOR_INTERVAL = 1                                # 监听间隔（秒）
RESUME_TOKEN_EXPIRE = 3600                          # 恢复令牌有效期（秒）
```

## 项目结构

```
RPA_GROUP/
├── RPA.py                      # 主程序文件
├── ReadMe.md                   # 项目文档
├── requirements.txt            # 依赖列表
├── rpa.log                     # 运行日志
├── failed_tasks.log            # 失败任务日志
├── file/
│   ├── excel/
│   │   └── cmd.xlsx           # 指令配置文件
│   └── pictures/
│       ├── error.png          # 风控监听图片
│       ├── error_shots/       # 风控截图目录
│       └── wxwork/            # 企业微信相关图片
└── uvicorn.log                # Web 服务日志
```

## 注意事项

### 1. 安全配置

- 修改默认 API Key（RPA.py:32）
- 生产环境关闭 reload 模式
- 配置 Redis 访问密码

### 2. 路径配置

- 图片路径必须使用**相对路径**或**绝对路径**
- Excel 文件路径在 `EXCEL_PATH` 常量中配置
- 确保 `./file/pictures/error.png` 存在以启用风控监听

### 3. 图像识别

- 屏幕分辨率需与截图图片一致
- 调整 `CONFIDENCE`（RPA.py:131）平衡识别精度/速度
- 企业微信/钉钉版本需与操作逻辑匹配

### 4. 性能调优

- 修改 `CLICK_INTERVAL` 调整操作速度
- 修改 `RETRY_TIMEOUT` 调整图片查找超时
- Celery worker 并发数建议设置为 1（串行执行）

### 5. 调试建议

- 查看 `rpa.log` 了解详细执行日志
- 使用 `failed_tasks.log` 追踪失败任务
- 监控 Celery worker 输出排查任务异常

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

## 技术栈

- **Web 框架**: FastAPI 0.100+
- **任务队列**: Celery 5.3+
- **消息代理**: Redis 4.5+
- **UI 自动化**: PyAutoGUI 0.9+
- **窗口管理**: PyGetWindow 0.0.9+
- **数据处理**: Pandas 2.0+

## 开发计划

- [ ] 支持更多 IM 平台（飞书、Slack）
- [ ] Web 管理界面
- [ ] 任务执行录像回放
- [ ] 分布式多机部署支持
- [ ] OCR 文字识别功能

## 许可证

MIT License

## 联系方式

- 作者: Hugh Zhang
- GitHub: [HughZhangGeek/RPA_GROUP](https://github.com/HughZhangGeek/RPA_GROUP)

## 更新日志

### v4.0 (当前版本)
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
