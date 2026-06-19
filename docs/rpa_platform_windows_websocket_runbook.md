# RPA 平台 Windows WebSocket 部署 Runbook

状态：2026-06-18 草案
适用范围：Windows RPA 执行服务反连 jdycsm 控制面
非目标：不部署旧 `RPA.py`，不开放 Windows 入站业务接口，不把 Cookie 或密钥明文上传到 jdycsm

## 1. 部署结论

第一版部署采用控制面和执行面分离：

```text
外部业务系统
-> jdycsm HTTP API
-> jdycsm 任务入库与调度
-> WebSocket 下发到 Windows worker
-> Windows 本地执行 RPA / 接口 runner
-> WebSocket 回传进度和结果
```

Windows 不暴露公网 HTTP 服务。所有业务入口统一到 jdycsm，Windows 只主动建立 WebSocket 出站连接。

## 2. 前置条件

### 2.1 jdycsm 控制面

- 能提供 HTTPS/WSS 入口。
- 有任务表、worker 连接表、worker heartbeat 表或等价存储。
- 有机器级 token 配置能力。
- 日志系统能按 `task_id`、`machine_id`、`robot_id` 检索。
- 外部业务 API 能生成稳定 `idempotency_key`。

### 2.2 Windows 执行面

- Windows Server 已安装 Python 环境和项目依赖。
- 浏览器 Profile 固定，不随服务重启删除。
- 管理员已扫码登录简道云后台和企微开发者后台。
- 本地有稳定数据目录，例如：

```text
C:/rpa_group/
  config/
  data/
  logs/
  artifacts/
  browser-profiles/
```

- 出站网络允许访问 jdycsm WSS 地址、简道云后台、企微开发者后台。

## 3. 目录和配置

建议 Windows 本地配置：

```text
C:/rpa_group/config/machine.json
C:/rpa_group/config/worker.env
C:/rpa_group/data/platform-worker.db
C:/rpa_group/logs/worker.log
C:/rpa_group/artifacts/
C:/rpa_group/browser-profiles/wecom-admin/
```

`machine.json` 示例：

```json
{
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "created_at": "2026-06-17T10:00:00+08:00"
}
```

`worker.env` 示例：

```ini
RPA_WS_URL=wss://jdycsm.example.com/rpa/ws/worker
RPA_MACHINE_TOKEN=replace-with-machine-token
RPA_ROBOT_ID=windows-rpa-01
RPA_DB_PATH=C:/rpa_group/data/platform-worker.db
RPA_BROWSER_PROFILE=C:/rpa_group/browser-profiles/wecom-admin
RPA_ARTIFACT_DIR=C:/rpa_group/artifacts
RPA_LOG_PATH=C:/rpa_group/logs/worker.log
RPA_CAPABILITIES=wecom_bind_service,browser_profile
```

敏感配置不得提交到 Git。

### 3.1 CSM_C360 控制面模拟 worker 配置

当前 CSM_C360 公网控制面使用独立的最小 worker 协议，worker 侧优先使用环境变量启动，不需要修改旧 `RPA.py`：

```powershell
$env:C360_BASE_URL="https://jdycsm.sre.jdydevelop.com/csm-c360-api"
$env:RPA_WORKER_TOKEN="<只在本机环境变量中配置>"
$env:RPA_WORKER_ID="win-sim-001"
$env:RPA_WORKER_SIMULATE="true"
$env:RPA_WORKER_CAPABILITIES="wecom_bind_service,diagnostics,runtime_health_check"
python -m rpa_platform.worker.c360_worker --once
```

worker 会从 `C360_BASE_URL` 推导 WebSocket 地址：

```text
wss://jdycsm.sre.jdydevelop.com/csm-c360-api/v1/rpa/workers/ws
```

本地控制面可使用：

```powershell
$env:C360_BASE_URL="http://127.0.0.1:3601"
```

推导结果为：

```text
ws://127.0.0.1:3601/v1/rpa/workers/ws
```

缺少 `RPA_WORKER_TOKEN` 时，入口会返回 blocked/error 并退出；输出不得包含 token、Cookie、headers、Authorization 或浏览器登录态。

### 3.2 企微后台登录态恢复配置

第一版登录态恢复只做只读预检、二维码通知和状态推进，不默认执行真实写入绑定。真实 webhook、Cookie、二维码图片都只保存在 Windows 本机，不提交到 Git，也不写入文档或日志。

建议在 Windows 本机环境变量或 `worker.env` 中配置：

```ini
WECOM_LOGIN_RECOVERY_ENABLED=true
WECOM_QR_NOTIFY_ENABLED=true
WECOM_QR_NOTIFY_WEBHOOK_URL=<只在 Windows 本机安全配置中填写>
WECOM_QR_NOTIFY_MODE=image
WECOM_QR_NOTIFY_MENTION_MOBILES=<管理员手机号，多个用英文逗号分隔，可为空>
WECOM_QR_TTL_SECONDS=120
WECOM_QR_MAX_NOTIFY_TIMES=3
WECOM_QR_ARTIFACT_DIR=C:/rpa_work/RPA_GROUP/.local/wecom-login-qr
WECOM_ADMIN_COOKIE_FILE=C:/rpa_work/RPA_GROUP/.local/wecom-admin.cookie
WECOM_BROWSER_PROFILE_DIR=C:/rpa_work/RPA_GROUP/.local/wecom-bind-browser-profile
WECOM_LOGIN_RECOVERY_NODE_WORK_DIR=C:/rpa_work/RPA_GROUP/.local/playwright-wecom-login-recovery
WECOM_LOGIN_URL=https://open.work.weixin.qq.com/wwopen/developers/tools
WECOM_QR_SELECTOR=canvas, img[src*='qr'], img[src*='qrcode'], img[src*='login'], [class*='qr'] canvas, [class*='qr'] img, [class*='qrcode'] img, [class*='login'] img
WECOM_BROWSER_CHANNEL=chrome
```

运行边界：

- `WECOM_QR_ARTIFACT_DIR` 只存短期二维码 artifact，过期后应由本机清理任务删除。
- `WECOM_ADMIN_COOKIE_FILE` 只保存企微后台 Cookie，不进入任务结果、日志或 PR。
- `WECOM_BROWSER_PROFILE_DIR` 必须由运行 worker 的同一 Windows 用户创建和使用，不能混用 RDP 管理员和服务用户。
- `WECOM_LOGIN_RECOVERY_NODE_WORK_DIR` 用于安装/缓存 Playwright Node 包和临时脚本，必须放在 `.local` 或 Windows 本机运行目录下。
- 二维码通过配置好的企微运维群机器人发送，不发给业务提交人。
- 管理员扫码后，worker 以企微后台只读接口返回有效 JSON 作为登录态恢复依据；二维码消失或页面跳转只作为辅助信号。
- 登录恢复后重新执行只读预检；结果最多进入 `ready_for_real_bind` 或 `manual_confirm_required`，后续真实写入仍需独立确认开关。

第一版实现链路：

```text
readonly preflight 返回 wecom_session_expired
-> Playwright 使用 WECOM_BROWSER_PROFILE_DIR 打开 WECOM_LOGIN_URL
-> 在主页面和可见 iframe 中查找 WECOM_QR_SELECTOR 命中的二维码
-> 截取二维码到 WECOM_QR_ARTIFACT_DIR
-> 发送企微机器人 markdown/text/image 通知
-> Node/Playwright 后台进程保持登录页存活到 TTL
-> 每轮轮询从同一 browser profile 导出最新企微 Cookie 到 WECOM_ADMIN_COOKIE_FILE
-> 企微只读接口 GET /wwopen/developer/customApp/tpl/app/list 验证登录态恢复
-> 恢复后重跑 readonly preflight
```

企微登录页当前会把真实二维码放在 `.wwLogin_qrcode_iframe` iframe 内；provider 会先查主页面，再扫描子 frame，并跳过尺寸过小的 loading/占位图片。如果 Playwright 仍无法识别二维码元素，应先在 Windows 本机打开企微登录页确认 DOM，再通过 `WECOM_QR_SELECTOR` 调整选择器。不要把页面 HTML、截图原图、Cookie 或 webhook 贴到聊天、PR 或文档。

## 4. 首次部署步骤

### 4.1 jdycsm 侧准备

1. 创建 `machine_id` 和机器级 token。
2. 配置允许的 `robot_id` 和能力列表。
3. 开启 WebSocket worker endpoint。
4. 配置外部业务 API：只接收 HTTP 请求，不直连 Windows。
5. 确认任务表对 `idempotency_key` 有唯一约束。
6. 确认 WebSocket 断线时任务不会丢失。

### 4.2 Windows 侧准备

1. 拉取 `RPA_GROUP` 仓库到 Windows 固定目录。
2. 创建 Python 虚拟环境并安装依赖。
3. 创建 `C:/rpa_group/config/worker.env`。
4. 如果 `machine.json` 不存在，本地生成 UUID 并持久化。
5. 创建固定浏览器 Profile 目录。
6. 人工打开浏览器扫码登录简道云后台和企微开发者后台。
7. 使用只读登录态检查确认登录有效。
8. 启动 worker 服务，观察 register 和 heartbeat。

## 5. 服务启动方式

第一版可以先用命令行启动，稳定后再注册为 Windows 服务。

命令行示例：

```powershell
cd C:\path\to\RPA_GROUP
.\.venv\Scripts\Activate.ps1
python -m rpa_platform.worker.websocket_worker --env C:\rpa_group\config\worker.env
```

Windows 服务建议后续使用 NSSM 或 Windows Task Scheduler。服务必须支持：

- 开机自启。
- 失败自动重启。
- 标准输出写入日志文件。
- 重启后保留本地 DB、Profile 和 artifacts。

### 5.1 Windows 交互桌面要求

第一版如果执行浏览器可视化自动化、企业微信客户端自动化或 PyAutoGUI，不建议直接作为 Session 0 Windows Service 运行。Session 0 不能稳定访问登录用户的桌面，容易出现看不到窗口、截图黑屏、点击无效、浏览器 Profile 不一致等问题。

推荐顺序：

1. 先在登录用户桌面用 PowerShell 命令行运行 worker。
2. 再用 Windows Task Scheduler 配置为该用户登录后启动。
3. 确认 RDP 断开后仍能保持桌面、分辨率和登录态，再考虑 NSSM 服务化。

固定项：

- 分辨率：1920x1080 或业务截图匹配的固定分辨率。
- 缩放：100%。
- 电源：禁止睡眠，禁止自动锁屏。
- 浏览器 Profile：由运行 worker 的同一 Windows 用户创建和使用。
- RDP：测试断开连接后的截图、点击、浏览器请求是否仍可执行。

## 6. 验证步骤

### 6.1 只读连通性验证

1. Windows 启动 worker。
2. jdycsm worker 列表看到 `windows-rpa-01` 在线。
3. heartbeat 每 15 秒更新。
4. 登录态摘要显示 `jdy_admin=ok`、`wecom_admin=ok` 或明确的 `unknown`。
5. 不发送真实业务写入任务。

### 6.2 fake runner 验证

在本地或测试环境使用现有 dry-run 路径：

```bash
python scripts/dev/run_platform_dryrun.py --prepare-only
python scripts/dev/run_platform_worker_once.py
```

预期：

- `TaskScheduler.run_once()` 能 claim 一条任务。
- runner 能写入 task step。
- robot 从 `busy` 回到 `idle`。
- 输出不包含 Cookie、Token、EncodingAESKey 或 kitsecret 明文。

### 6.3 WebSocket 派发验证

1. jdycsm 创建测试任务，payload 使用 `zh_test` 或测试客户。
2. 任务状态从 `pending` 到 `dispatched`。
3. Windows 回传 `task.ack`。
4. Windows 回传 `task.progress`。
5. 任务进入 `success` 或可解释的等待态。
6. jdycsm 日志可按 `task_id` 串起完整链路。

### 6.3.1 CSM_C360 公网 WSS 模拟端到端验证

本阶段只验证模拟 handler，不执行真实企微绑定、不写简道云、不打开浏览器。验证步骤：

1. 在 Windows 或本地 shell 中设置 `C360_BASE_URL`、`RPA_WORKER_TOKEN`、`RPA_WORKER_ID` 和 `RPA_WORKER_SIMULATE=true`。
2. 启动：

```powershell
python -m rpa_platform.worker.c360_worker --once
```

3. 预期 worker 首包发送：

```json
{
  "type": "worker.hello",
  "worker_id": "win-sim-001",
  "capabilities": ["wecom_bind_service", "diagnostics", "runtime_health_check"],
  "simulate": true
}
```

4. 控制面返回 `worker.accepted` 后，创建 `wecom_bind_service` 模拟任务。
5. worker 收到 `task.dispatch` 后依次回传：

```text
task.accepted -> task.progress -> task.completed
```

6. `task.completed` 的模拟结果应包含：

```json
{"simulated": true, "handler": "wecom_bind_service"}
```

7. 通过控制面任务查询确认 `status=succeeded`、`result_json.simulated=true`、`worker_id` 等于当前 worker。

如果没有可用 token 或公网 WSS 不通，不要把 token 粘贴到聊天、文档、日志或 PR；保留本地 fake transport 测试结果和阻塞原因即可。

### 6.3.2 企微登录态恢复骨架验证

本阶段只验证登录态恢复骨架，不真实写简道云、不执行企微绑定写入。

本地测试命令：

```bash
python -m pytest \
  tests/test_platform_wecom_bot.py \
  tests/test_platform_wecom_login_recovery.py \
  tests/test_platform_wecom_bind_recovery_handler.py \
  tests/test_platform_c360_worker_runtime.py
```

预期：

- 企微机器人 markdown、text、image payload 构造成功，payload 和返回值不包含 webhook key。
- `outsession`、登录页、401/403 被识别为登录态失效。
- 有效企微只读 JSON 被识别为登录态已恢复。
- 遇到 `wecom_session_expired` 时，worker 使用固定 browser profile 截取二维码、发送二维码通知，并进入 `waiting_login`/`manual_action_required`。
- 轮询期间后台 Playwright 进程保持登录页存活；编排结束后关闭该进程。
- 每轮轮询先刷新 `WECOM_ADMIN_COOKIE_FILE`，再使用企微只读接口验证服务端登录态。
- 登录恢复后自动重跑只读预检；`ok` 映射为 `ready_for_real_bind`，`review` 映射为 `manual_confirm_required`。
- 输出不包含真实 CorpID、Cookie、Token、Webhook 或二维码原始内容。

### 6.4 断线恢复验证

1. 下发一条 fake 任务。
2. 在 running 中断开 Windows worker 网络或停止进程。
3. jdycsm 将任务置为 `worker_offline` 或 `waiting_worker`。
4. 重启 worker。
5. worker.register 上报 `current_task` 或本地最近任务结果。
6. jdycsm reconcile 后不重复执行真实写入。

### 6.5 Windows 调试验证

只读诊断模式不会连接 WebSocket、不会 claim 新任务、不会执行真实写入，只读取 `worker.env`、生成或复用本地 `machine.json`，并在标准输出打印脱敏 JSON。

可复制命令：

```powershell
cd C:\path\to\RPA_GROUP
.\.venv\Scripts\Activate.ps1
python -m rpa_platform.worker.websocket_worker --env C:\rpa_group\config\worker.env --diagnose
```

预期：

1. 命令返回 JSON。
2. JSON 包含 `diagnostic_id`、`machine_id`、`robot_id`、`windows`、`worker`、`network`、`local_refs`。
3. `network.wss_connected=false`，因为本地诊断不建立 WebSocket。
4. `local_refs` 只包含本地路径提示，不包含日志正文、截图原图或 SQLite 内容。
5. 输出不包含机器 token、Cookie、EncodingAESKey、kitsecret、请求头或浏览器登录态明文。

## 7. Windows 调试手册

### 7.1 调试入口

本地只读诊断入口：

```powershell
python -m rpa_platform.worker.websocket_worker --env C:\rpa_group\config\worker.env --diagnose
```

该命令只打印脱敏诊断摘要并退出。它不会启动长连接、不会派发任务、不会重放任务，也不会触发任何真实写入。

当前排障优先检查：

- `worker.env` 路径是否正确。
- `RPA_ROBOT_ID`、`RPA_DB_PATH`、`RPA_LOG_PATH`、`RPA_ARTIFACT_DIR` 是否能被诊断入口读取。
- `machine.json` 是否能生成或复用稳定 `machine_id`。
- 命令输出是否只包含脱敏摘要和本地路径提示，不泄露机器 token。

### 7.2 本地证据路径

排障时先收集这些索引，不复制敏感原文到聊天或 PR：

```text
C:/rpa_group/logs/worker.log
C:/rpa_group/data/platform-worker.db
C:/rpa_group/artifacts/<task_id>/
C:/rpa_group/config/machine.json
C:/rpa_group/config/worker.env
```

注意：

- `worker.env` 含机器 token，只允许本地查看，不提交、不粘贴。
- artifact 可能包含业务页面截图，默认不上传 jdycsm。
- SQLite 可能包含任务 payload，导出前先脱敏。

### 7.3 网络排查

检查 DNS、TCP 和 TLS 基础连通：

```powershell
Resolve-DnsName jdycsm.example.com
Test-NetConnection jdycsm.example.com -Port 443
```

如果 WebSocket 连接失败，优先看：

- `RPA_WS_URL` 是否为 `wss://`。
- 机器 token 是否和 jdycsm 登记一致。
- 公司代理、防火墙是否阻断长连接。
- 服务器证书是否被 Windows 信任。
- heartbeat 是否曾成功发出。

### 7.4 登录态排查

登录态失效时，不先重跑任务，先做只读检查：

1. 用运行 worker 的同一 Windows 用户打开固定浏览器 Profile。
2. 访问简道云后台和企微开发者后台。
3. 如需扫码，扫码后不要关闭 Profile 目录或切换用户。
4. 等待 worker heartbeat 上报登录态恢复；也可以运行 `--diagnose` 确认当前 Windows session、交互桌面状态和本地证据路径。
5. 再从 jdycsm 恢复任务。

### 7.4.1 登录二维码和通知策略

第一版沿用企微作为通知通道，但通知对象是 RPA 运维/机器人管理员，不是业务提交人。Windows worker 不直接发企微消息，也不直接把二维码推给用户；worker 只上报 `task.error status=waiting_login`、目标系统和诊断摘要，由 jdycsm 控制面统一创建人工处理单并发送通知。

企微机器人消息默认只包含：

```text
Windows RPA 登录态失效
任务：task_001
机器：windows-rpa-01
目标：企微开发者后台
处理：请远程到 Windows 机器扫码，或打开 jdycsm 人工处理页
链接：https://jdycsm.example.com/rpa/manual-actions/action_001
```

默认不发送二维码截图，原因是二维码绑定 Windows 固定浏览器 Profile 和当前登录上下文，远程到 Windows 本机扫码最稳，也避免二维码截图在群聊、日志和任务详情里扩散。

可选二期能力：

- jdycsm 支持“二维码临时转发”开关，默认关闭。
- 只允许发给白名单管理员私聊或专用安全群。
- 二维码截图只作为短 TTL artifact，不长期入库。
- 通知记录保存触发人、接收人、过期时间、处理结果。
- 二维码不得进入普通日志、PR、任务详情正文或导出报表。

### 7.5 RDP 和桌面问题

常见现象：

- 截图黑屏。
- 找不到窗口。
- 点击坐标偏移。
- RDP 断开后任务卡住。
- 浏览器 Profile 被另一个用户锁定。

处理顺序：

1. 确认 worker 是否在交互式登录用户下运行。
2. 确认分辨率和缩放没有变化。
3. 确认 Windows 没有锁屏或睡眠。
4. 确认 RDP 断开后的行为已单独验证。
5. 如果必须长期跑 UI 自动化，优先使用能保持控制台会话的远程方案，再决定是否服务化。

### 7.6 任务重放

任务重放属于后续规划能力，当前 worker CLI 不支持本地重放参数。该能力实现前，不要把 worker CLI 当作任务重放工具使用。

后续如实现真实写入重放，必须满足：

- jdycsm 任务状态允许重试。
- Windows 本地没有同一 `idempotency_key` 的成功记录。
- 操作人显式确认真实写入。
- 日志记录 `operator`、`reason` 和 `confirmed_at`。

## 8. 企微客户端自动建群配置与验证

### 8.1 能力边界

企微客户端自动建群能力名：

```text
wecom_client_rpa_create_group
```

该能力只处理企业微信 Windows 客户端自动建群，先不覆盖钉钉，也不复用企微绑定服务 runner。第一版固定：

- 固定 Windows 登录用户。
- 固定分辨率和缩放。
- 长期保持解锁桌面。
- RDP 断开后仍要执行，并使用现有断开脚本或控制台会话方案验证。
- 单 worker 单并发。
- 日志、截图、trace 暂时只存 Windows 本地。
- 人工通知管理员。
- 可以用真实测试群做端到端验证。

### 8.2 配置页分层

配置页面向业务同学，但不能把底层 UIA selector 直接暴露为主要编辑项。建议分两层：

业务层：

- 选择“企微自动建群”模板。
- 填写客户名称、群名称、群主、群成员。
- 选择测试群或生产群。
- 填写失败通知管理员。
- 发起测试建群。

高级层：

- 仅 RPA 管理员可见。
- 维护 UIA selector、fallback 图片、重试策略、断言、失败处理。
- 发布模板版本。
- 回滚模板版本。

### 8.3 元素拾取器

当前仓库只新增元素拾取器骨架，不要求打包 exe，也还没有真实 UIA 驱动或可运行的本地 picker CLI。骨架边界：

- `element_picker.build_selector_from_element()` 负责把 UIA 元素元数据转换成 selector。
- `uia_driver.UiaDriver` 只定义 `find_element`、`click_element`、`set_text` 协议接口。
- 后续 Windows 本地模式再接入真实 UIA 库、快捷键监听、截图索引和 WebSocket 回传。

后续 picker CLI 形态可以是：

```powershell
python -m rpa_platform.worker.element_picker --env C:\rpa_group\config\worker.env
```

推荐交互：

1. 管理员打开企微客户端。
2. jdycsm 配置页点击“开始拾取”。
3. Windows worker 进入 picker 模式。
4. 管理员把鼠标悬停到目标控件。
5. 管理员按 `Ctrl+Alt+P` 捕获当前鼠标下 UIA 元素。
6. worker 回传元素元数据和本地截图索引。
7. jdycsm 展示 selector，并提供“测试定位”按钮。

快捷键捕获比点击捕获更安全，因为点击可能触发真实建群、选人或发送动作。

### 8.4 建群模板第一版步骤

第一版模板建议固定为：

```text
激活企业微信
-> 确认主窗口可用
-> 打开发起群聊入口
-> 搜索并选择成员
-> 设置群名称
-> 确认创建
-> 校验群窗口和群名称
-> 保存本地截图/日志/诊断摘要
-> 回传结果
```

从旧 `RPA.py` 迁移时，动作映射如下：

| 旧动作 | 新动作 | 说明 |
| --- | --- | --- |
| `激活企业微信` | `activate_app` | 窗口标题和进程双重确认 |
| `左击图片` | `click_element` + `fallback_image_click` | UIA 优先，图片兜底 |
| `左击坐标` | `fallback_position_click` | 高风险兜底，必须标记 |
| `粘贴` | `set_text` / `clipboard_paste` | 输入框优先，剪贴板兜底 |
| `输入` | `set_text` | 避免逐字键入失败 |
| `快捷键` | `send_hotkey` | 保留 |
| `等待` | `wait_until` | 从固定 sleep 改为状态等待 |
| `检查图片是否存在` | `assert_element` / `assert_image` | UIA 优先 |
| `滚动屏幕` | `scroll_container` / `wheel` | 元素滚动优先 |

### 8.5 真实测试群验收

验收时使用 `zh_test` 前缀测试群：

```text
客户名称：zh_test_上海测试客户
群名称：zh_test_上海测试客户_服务群
群成员：测试账号
```

验收标准：

- jdycsm 创建任务后，Windows worker 单并发执行。
- 企微客户端真实创建测试群。
- 任务步骤有 progress。
- 成功结果包含群名、执行机器、执行时间和 artifact 索引。
- 失败结果包含失败步骤、错误类型、本地日志路径和截图索引。
- 截图原图仍只保存在 Windows 本地。

## 9. 运维动作

### 9.1 登录态失效

现象：

```text
task.error status=waiting_login error_type=LOGIN_REQUIRED
```

处理：

1. Windows worker 上报 `task.error status=waiting_login`。
2. jdycsm 创建人工处理单，状态进入 `waiting_login`。
3. jdycsm 通过企微机器人通知 RPA 运维/机器人管理员，并附处理链接。
4. 管理员远程登录 Windows。
5. 管理员打开固定浏览器 Profile。
6. 管理员扫码登录简道云后台或企微开发者后台。
7. 管理员等待 worker heartbeat 上报登录态恢复，或运行 `--diagnose` 查看当前 Windows session、交互桌面状态和本地证据路径。
8. 在 jdycsm 点击恢复，或由控制面按 login health 自动恢复。
9. jdycsm 重新派发可恢复任务。

### 9.2 worker 离线

现象：

```text
heartbeat 超过 45 秒未更新
```

处理：

1. 检查 Windows 服务状态。
2. 检查 `C:/rpa_group/logs/worker.log`。
3. 检查出站网络和 WSS 地址。
4. 重启 worker 服务。
5. 确认 register 后 reconcile 结果。

### 9.3 任务重复风险

触发场景：

- WebSocket ack 后断线。
- jdycsm result 未落库。
- Windows 执行成功但回传失败。

处理原则：

- 先查 `idempotency_key`。
- 先查 Windows 本地执行记录。
- 不直接重新执行真实写入。
- 有成功记录时补发脱敏 result。
- 无本地记录且 jdycsm 确认可重试时，才重新派发。

## 10. 回滚

第一版不影响旧 `RPA.py`，回滚主要是停用新 worker：

1. jdycsm 禁用目标 `robot_id` 调度。
2. 停止 Windows worker 服务。
3. 保留本地 DB、Profile、日志和 artifacts。
4. jdycsm 未完成任务置为 `waiting_worker`，避免丢失。
5. 外部业务入口继续留在 jdycsm，不切回直连 Windows。

## 11. 安全要求

- Windows 只允许出站连接 jdycsm，不开放公网入站业务端口。
- 机器级 token 放在 Windows 本地配置，不提交 Git。
- Cookie、sid、vst、monitor、Token、EncodingAESKey、kitsecret 不写日志、不入库、不上传。
- 截图原图默认只存在 Windows 本地。
- jdycsm 上只保存 artifact 索引和脱敏摘要。
- 所有写入类任务必须有 `idempotency_key`。

## 12. 相关代码文件/模块

- `rpa_platform/worker/scheduler.py`：现有一次性任务执行挂点。
- `rpa_platform/worker/runner.py`：runner 协议。
- `rpa_platform/worker/wecom_bind_runner.py`：企微绑定接口服务 runner。
- `rpa_platform/worker/wecom_client_runner.py`：建议新增的企微客户端建群 runner。
- `rpa_platform/worker/uia_driver.py`：Windows UIA 元素执行适配器协议骨架，尚未接入真实驱动。
- `rpa_platform/worker/element_picker.py`：元素拾取器 selector 构造骨架，尚未提供可运行 picker CLI。
- `rpa_platform/storage/sqlite_store.py`：任务、机器人、幂等键、步骤和 artifact 存储。
- `rpa_platform/worker/diagnostics.py`：建议新增的 Windows 只读诊断摘要模块。
- `scripts/dev/run_platform_worker_once.py`：本地一次性 worker 验证。
- `scripts/dev/run_platform_dryrun.py`：本地 dry-run 数据准备和 fake runner 验证。
