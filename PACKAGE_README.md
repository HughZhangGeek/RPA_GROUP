# RPA_GROUP 发布包说明

## 包含内容

本 zip 包包含 RPA_GROUP 项目的完整源码和配置文件，可直接部署使用。

### 📦 文件清单

```
RPA_GROUP/
├── 📄 核心代码
│   ├── RPA.py                      # 主应用程序（FastAPI + RPA 逻辑）
│   ├── database.py                 # SQLite 数据层
│   ├── queue_worker.py             # 后台队列 Worker
│   ├── check_queue_status.py       # 队列状态检查工具
│   └── migrate_redis_to_sqlite.py  # 数据迁移脚本
│
├── 📋 配置模板
│   ├── .env.example                # 环境变量配置模板
│   ├── config.py.example           # Python 配置模板
│   └── .gitignore                  # Git 忽略规则
│
├── 📦 依赖文件
│   ├── requirements.txt            # pip 依赖列表
│   └── environment.yml             # Conda 环境配置
│
├── 📖 文档
│   ├── ReadMe.md                   # 项目说明文档
│   ├── CLAUDE.md                   # Claude Code 项目指南
│   ├── DEPLOYMENT.md               # 部署指南（重要！）
│   └── 优化.md                     # 优化记录
│
├── 🚀 启动脚本
│   ├── start.bat                   # Windows 启动脚本
│   └── start_linux.sh              # Linux/Mac 启动脚本
│
├── 🧪 测试文件
│   ├── test_send_message.http      # HTTP 接口测试
│   └── 恢复队列.http               # 队列恢复测试
│
├── 🎨 模板
│   └── templates/
│       └── queue_monitor.html      # 队列监控 Web UI
│
└── 📁 资源文件
    └── file/
        ├── excel/
        │   └── cmd.xlsx            # 操作指令配置
        └── pictures/
            ├── error.png           # 风控检测图片
            └── wxwork/             # 企业微信 UI 元素截图
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

## 🚀 快速部署（3 步）

### 1️⃣ 解压文件

```bash
unzip RPA_GROUP_v1.0_*.zip
cd RPA_GROUP
```

### 2️⃣ 创建配置文件

```bash
# 复制配置模板
cp .env.example .env
cp config.py.example config.py

# 编辑 .env 文件，填写以下必需配置：
# - API_KEY: 自定义 API 密钥
# - WECOM_WEBHOOK_URL: 企业微信机器人 Webhook
# - SERVER_HOST: 服务器地址（本地开发填 127.0.0.1）
```

### 3️⃣ 安装依赖并启动

**方式一：使用 Conda（推荐）**

```bash
# 创建环境
conda env create -f environment.yml

# 激活环境
conda activate RPA_GROUP

# 启动服务（Windows 双击 start.bat，Linux/Mac 执行下面命令）
./start_linux.sh
```

**方式二：使用 pip**

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn RPA:app --host 0.0.0.0 --port 8000
```

## 📚 重要文档

| 文档 | 说明 |
|------|------|
| **DEPLOYMENT.md** | 📖 **完整部署指南**（必读！） |
| ReadMe.md | 项目功能说明 |
| CLAUDE.md | 代码架构说明 |
| 优化.md | 项目优化历史 |

## ⚠️ 注意事项

### 必须配置的文件

解压后需要手动创建以下文件（不包含在 zip 中）：

1. **`.env`** - 环境变量配置
   - 参考 `.env.example` 创建
   - 包含 API 密钥、Webhook URL 等敏感信息

2. **`config.py`** - Python 配置文件
   - 参考 `config.py.example` 创建
   - 从 `.env` 读取配置

### 环境要求

- **操作系统**: Windows 10/11（需要图形界面）
- **Python**: 3.8+
- **屏幕分辨率**: 与截图采集时一致（重要！）
- **企业微信/钉钉**: 已安装并登录

### 图片资源说明

`file/pictures/wxwork/` 目录下的截图必须与目标屏幕分辨率匹配。如果识别失败：
1. 在目标屏幕上重新截取 UI 元素
2. 或降低 `config.py` 中的 `CONFIDENCE` 值（0.9 → 0.8）

## 🔗 访问地址

服务启动后可访问：

- **API 文档**: http://127.0.0.1:8000/docs
- **队列监控**: http://127.0.0.1:8000/queue-monitor

## 🆘 故障排查

遇到问题请查看：

1. **DEPLOYMENT.md** - 完整的故障排查指南
2. **诊断命令** - 查看任务状态和日志
3. **常见问题** - 图像识别失败、队列卡住等

### 快速诊断命令

```bash
# 查看队列状态
curl http://127.0.0.1:8000/api/queue/stats

# 查看最近任务
sqlite3 rpa.db "SELECT task_id, task_type, status, customer_name, created_at FROM tasks ORDER BY created_at DESC LIMIT 20;"

# 重置卡住的任务
sqlite3 rpa.db "UPDATE tasks SET status='pending' WHERE status='running';"
```

## 📊 项目统计

- **代码行数**: 1,749 行
- **核心文件**: 6 个 Python 文件
- **依赖包**: 11 个
- **包大小**: ~138 KB

## 🔐 安全提示

1. **不要提交敏感文件到 Git**
   - `.env` 和 `config.py` 已在 `.gitignore` 中排除
   - 定期更换 API_KEY

2. **访问控制**
   - 建议仅在内网环境运行
   - 使用防火墙限制端口访问

3. **日志管理**
   - 定期清理日志文件
   - 不要在日志中记录敏感信息

## 📞 技术支持

如有问题，请查看：
- `DEPLOYMENT.md` - 完整部署指南
- `ReadMe.md` - 项目功能说明
- `CLAUDE.md` - 代码架构说明

---

**版本**: v1.0  
**更新日期**: 2026-05-09  
**Python 版本**: 3.8+  
**许可证**: 内部使用