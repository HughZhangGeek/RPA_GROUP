# RPA_GROUP 部署指南

## 快速开始

### 1. 环境要求

- **操作系统**: Windows 10/11（需要图形界面）
- **Python**: 3.8+ (推荐使用 Conda)
- **屏幕分辨率**: 与截图采集时一致（重要！）
- **企业微信/钉钉**: 已安装并登录

### 2. 安装步骤

#### 方式一：使用 Conda（推荐）

```bash
# 1. 创建 Conda 环境
conda env create -f environment.yml

# 2. 激活环境
conda activate RPA_GROUP

# 3. 验证安装
python -c "import fastapi, pyautogui; print('环境配置成功')"
```

#### 方式二：使用 pip

```bash
# 1. 创建虚拟环境（可选）
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 2. 安装依赖
pip install -r requirements.txt

# 3. 验证安装
python -c "import fastapi, pyautogui; print('环境配置成功')"
```

### 3. 配置文件

#### 创建 .env 文件

复制 `.env.example` 并重命名为 `.env`，填写以下配置：

```ini
# API 认证密钥（自定义，用于接口鉴权）
API_KEY=your_secret_api_key_here

# 企业微信机器人 Webhook（用于告警通知）
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx

# 服务器配置
SERVER_HOST=127.0.0.1  # 外部访问地址（用于生成恢复链接）
SERVER_PORT=8000

# 队列配置
RESUME_TOKEN_EXPIRE=3600  # 恢复令牌有效期（秒）
TASK_RETRY_DELAY=5        # 队列暂停时轮询间隔（秒）
MONITOR_INTERVAL=1        # 风控检测间隔（秒）

# 数据库配置
DB_PATH=./rpa.db
```

#### 创建 config.py 文件

复制 `config.py.example` 并重命名为 `config.py`（或直接使用提供的模板）。

### 4. 启动服务

#### Windows 用户（推荐）

双击 `start.bat` 即可启动服务。

#### 手动启动

```bash
# 激活环境
conda activate RPA_GROUP

# 启动服务
uvicorn RPA:app --host 0.0.0.0 --port 8000
```

服务启动后访问：
- API 文档: http://127.0.0.1:8000/docs
- 队列监控: http://127.0.0.1:8000/queue-monitor

### 5. 验证部署

```bash
# 检查服务状态
curl http://127.0.0.1:8000/api/queue/stats

# 查看队列监控页面
# 浏览器打开: http://127.0.0.1:8000/queue-monitor
```

## 配置说明

### 图片资源配置

项目使用图像识别技术，需要确保以下图片与目标屏幕匹配：

```
file/pictures/
├── error.png                    # 风控检测图片
├── group_not_found.png          # 群不存在检测图片
└── wxwork/                      # 企业微信 UI 元素
    ├── add_icon.png
    ├── cant_modify_group_name.png
    ├── group_manage.png
    ├── more_icon.png
    ├── qr_code.png
    ├── send_confirm.png
    ├── send_qr_code_to_chat.png
    ├── set_group_name.png
    └── transfer_owner.png
```

**重要提示**：
- 截图必须与目标显示器分辨率一致
- 如果识别失败，可在 `config.py` 中降低 `CONFIDENCE` 值（0.9 → 0.8）

### 工作流配置

编辑 `file/excel/cmd.xlsx`，包含以下 sheet：
- **企微建群**: 企业微信建群流程
- **钉钉建群**: 钉钉建群流程
- **企微发消息**: 企业微信发消息流程
- **钉钉发消息**: 钉钉发消息流程

## API 使用

### 认证方式

所有 API 请求需要在 Header 中携带 API Key：

```http
X-API-Key: your_secret_api_key_here
```

### 主要接口

#### 1. 提交建群任务

```http
POST /start-automation
Content-Type: application/json
X-API-Key: your_secret_api_key_here

{
  "customer_name": "客户名称",
  "owner_name": "群主姓名",
  "group_type": "企微群",
  "group_name": "测试群",
  "技术支持手机号": "13800138000"
}
```

#### 2. 提交群发消息任务

```http
POST /send-message
Content-Type: application/json
X-API-Key: your_secret_api_key_here

{
  "customer_name": "客户名称",
  "target_group": "目标群名称",
  "message_content": "消息内容",
  "group_type": "企微群",
  "paas_id": "123",
  "user_id": "456"
}
```

#### 3. 查看队列状态

```http
GET /api/queue/stats?task_type=create_group
```

#### 4. 查看任务历史

```http
GET /api/queue/history?task_type=send_message&limit=50
```

#### 5. 重试失败任务

```http
POST /api/queue/task/{task_id}/retry
X-API-Key: your_secret_api_key_here
```

## 故障排查

### 常见问题

#### 1. 图像识别失败

**症状**: 日志显示 "未找到图片" 或 "识别超时"

**解决方案**:
- 确认屏幕分辨率与截图一致
- 降低 `config.py` 中的 `CONFIDENCE` 值（0.9 → 0.8）
- 重新截取目标图片

#### 2. 队列卡住

**症状**: 任务一直处于 `running` 状态

**解决方案**:
```bash
# 重置卡住的任务
sqlite3 rpa.db "UPDATE tasks SET status='pending' WHERE status='running';"

# 重启服务
# 按 Ctrl+C 停止，然后重新运行 start.bat
```

#### 3. 风控检测误报

**症状**: 频繁触发风控告警

**解决方案**:
- 调整 `MONITOR_INTERVAL` 增加检测间隔
- 更新 `file/pictures/error.png` 为更精确的截图

#### 4. 企微告警未发送

**症状**: 任务失败但未收到企微通知

**解决方案**:
- 检查 `.env` 中的 `WECOM_WEBHOOK_URL` 是否正确
- 验证 Webhook 是否有效：
  ```bash
  curl -X POST "你的WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d '{"msgtype":"text","text":{"content":"测试消息"}}'
  ```

### 诊断命令

```bash
# 查看最近 20 条任务
sqlite3 rpa.db "SELECT task_id, task_type, status, customer_name, created_at FROM tasks ORDER BY created_at DESC LIMIT 20;"

# 查看队列状态
sqlite3 rpa.db "SELECT * FROM queue_state;"

# 查看失败任务详情
sqlite3 rpa.db "SELECT task_id, customer_name, error_msg, error_type FROM tasks WHERE status='failed';"

# 统计任务状态
sqlite3 rpa.db "SELECT status, COUNT(*) as count FROM tasks GROUP BY status;"

# 查看日志
tail -f rpa.log
```

## 数据库管理

### 备份数据库

```bash
# 备份
sqlite3 rpa.db ".backup rpa_backup_$(date +%Y%m%d).db"

# 恢复
sqlite3 rpa.db ".restore rpa_backup_20260509.db"
```

### 清理历史数据

```bash
# 删除 30 天前的成功任务
sqlite3 rpa.db "DELETE FROM tasks WHERE status='success' AND created_at < datetime('now', '-30 days');"

# 清理日志文件
rm rpa.log.*
```

## 性能优化

### 调整队列参数

编辑 `.env` 文件：

```ini
# 减少轮询间隔（提高响应速度，增加 CPU 占用）
TASK_RETRY_DELAY=2

# 增加轮询间隔（降低 CPU 占用，降低响应速度）
TASK_RETRY_DELAY=10
```

### 数据库优化

```bash
# 优化数据库
sqlite3 rpa.db "VACUUM;"

# 重建索引
sqlite3 rpa.db "REINDEX;"
```

## 安全建议

1. **保护敏感文件**
   - `.env` 和 `config.py` 不要提交到 Git
   - 定期更换 `API_KEY`
   - 限制 Webhook URL 的访问权限

2. **访问控制**
   - 仅在内网环境运行
   - 使用防火墙限制端口访问
   - 启用 HTTPS（生产环境）

3. **日志管理**
   - 定期清理日志文件
   - 不要在日志中记录敏感信息
   - 设置日志轮转策略

## 生产部署建议

### 使用进程管理器

#### Windows - NSSM

```bash
# 下载 NSSM: https://nssm.cc/download
nssm install RPA_GROUP "C:\path\to\conda\envs\RPA_GROUP\python.exe" "-m uvicorn RPA:app --host 0.0.0.0 --port 8000"
nssm set RPA_GROUP AppDirectory "C:\path\to\RPA_GROUP"
nssm start RPA_GROUP
```

#### Linux - systemd

```ini
[Unit]
Description=RPA Group Service
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/RPA_GROUP
Environment="PATH=/path/to/conda/envs/RPA_GROUP/bin"
ExecStart=/path/to/conda/envs/RPA_GROUP/bin/uvicorn RPA:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

### 反向代理（Nginx）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 更新日志

查看 `优化.md` 了解项目更新历史。

## 技术支持

遇到问题请查看：
1. 本文档的"故障排查"章节
2. `ReadMe.md` 了解项目详情
3. `CLAUDE.md` 了解代码架构