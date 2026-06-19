# RPA 企微登录态恢复自动化交接

## 生命周期

- 状态：阶段性完成
- 当前阶段：企微服务商后台登录态恢复只读闭环已实现并完成 Windows 验证
- 最近更新：2026-06-19
- 仓库：`/Users/hugh/jdycsm_project/RPA_GROUP`
- Windows Server 路径：`C:\rpa_work\RPA_GROUP`
- 分支：`feat/windows-websocket-worker`

## 当前已完成进度

### 1. CSM_C360 控制面到 Windows worker 长连接已跑通

RPA_GROUP worker 侧已经新增 CSM_C360 长连接模拟入口，并推送到 GitHub：

- `0042113 feat: 新增 CSM_C360 worker 模拟长连接入口`
- `bb4469c fix: 对齐 CSM_C360 worker 鉴权头`

Windows Server 已成功拉取代码并导入模块：

```text
c360 worker module ok
```

CSM_C360 公网 WSS 模拟派发已经验证：

```text
task_id=562509e6c42f45509c6fc3f577dd5b34
status=succeeded
worker_id=win-server-001
result_json={"handler": "wecom_bind_service", "simulated": true}
```

### 2. 真实只读预检已验证到企微登录态失效边界

针对客户：

```text
enterprise_name=江苏凯棠工程项目管理有限公司
plain_corp_id=ww4fc007a22672730b
requested_user_id=69c888c9ff5bda0e12474dc7
```

只读预检结果：

```text
JDY CorpID 唯一命中：凯棠管理
owner_state=can_bind_corp_secret
status=blocked
reason=wecom_session_expired
detail=WeCom admin session expired: outsession
```

说明：

- JDY cookie 有效。
- CorpID 可唯一命中。
- owner 具备绑定能力。
- 当前阻塞点是企微开发者后台登录态失效。

### 3. CorpID 唯一命中时名称不一致不再直接阻断

已调整只读预检规则并推送：

- `1b2a879 fix: 允许 CorpID 唯一命中时名称不一致走复核`

现在 `plain_corp_id` 唯一命中后，企业名与 JDY 返回名不一致会继续预检；若其他检查通过，返回：

```text
status=review
reason=jdy_corp_name_mismatch
```

### 4. 企微服务商后台登录态恢复闭环已实现并验证

本阶段新增并推送了企微服务商后台登录态恢复骨架：

- `9719b73 docs: 补充企微登录态恢复自动化交接`
- `ba9a64d feat: 实现企微登录态恢复骨架`
- `e1ec60b test: 兼容 Windows 文件权限断言`
- `ff2e126 fix: 支持企微登录二维码 iframe 捕获`
- `b260c42 fix: 跳过企微登录二维码占位小图`
- `e410878 fix: 调整企微服务商登录恢复通知文案`

Windows Server 已完成端到端只读验证：

```text
QR_CAPTURED <WECOM_QR_ARTIFACT_DIR>/wecom-login-qr-*.png
QR_NOTIFIED
COOKIE_REFRESHED True
COOKIE_FILE_EXISTS True
COOKIE_FILE_SIZE > 0
LOGIN_STATUS restored
REASON readonly_api_ok
```

验证结论：

- 二维码 artifact 可在 `.local/wecom-login-qr` 生成。
- 企微群机器人可收到 markdown/text/image 通知。
- 管理员扫码后可从固定 browser profile 导出企微后台 Cookie。
- Cookie 可写入 `WECOM_ADMIN_COOKIE_FILE`。
- 企微服务商后台只读接口验证返回 `readonly_api_ok`。
- 第一版恢复后只进入 `ready_for_real_bind` / `manual_confirm_required` 等待后续确认，不默认真实绑定写入。

## 本阶段目标与完成情况

实现“企微后台登录态恢复自动化”的第一版闭环：

1. CSM_C360 接收 `wecom_bind_service` 请求。状态：已具备 worker 长连接和任务 handler 骨架。
2. Windows worker 执行真实只读预检。状态：已具备只读预检和登录态恢复衔接。
3. 如果预检遇到 `wecom_session_expired / outsession`：
   - worker 自动打开企微服务商后台登录页；
   - 截取或提取登录二维码；
   - 通过企微群机器人发送二维码和任务上下文；
   - 任务进入 `waiting_login` 或等价等待状态。
   状态：已实现并通过手动闭环验证。
4. 管理员扫码后，worker 自动判断登录态是否恢复。状态：已通过只读接口 `readonly_api_ok` 验证。
5. 登录恢复后，worker 自动重新跑只读预检。状态：已在编排骨架中实现。
6. 预检达到 `ok` 或 `review` 后，任务进入下一状态。状态：已映射为 `ready_for_real_bind` / `manual_confirm_required`。

第一版不要求真实绑定写入全自动执行；真实写入仍应保留显式确认或独立开关。

## 二维码通知理解

用户已确认：

- 二维码后续通过企微群机器人发送。
- 通知逻辑可复用旧 `RPA.py` 的企微机器人消息思路。
- 后续要做成可配置能力。

这里的“复用旧 `RPA.py` 逻辑”应理解为复用通知模式和消息格式，不应把新平台代码直接 import 或耦合旧线上 `RPA.py`。

旧 `RPA.py` 中可参考的能力：

- 截图转 base64 + md5，用于企微机器人 image 消息。
- 企微机器人支持 markdown、text、image 消息。
- 失败告警按说明、@、截图三步发送。

新实现建议放在 `rpa_platform/` 下的新模块，例如：

```text
rpa_platform/notifications/wecom_bot.py
rpa_platform/worker/wecom_login_recovery.py
```

## 如何判断用户已经扫码登录

不要以“二维码是否被扫码”作为最终判断，因为 worker 很难可靠拿到扫码事件本身，且二维码页面状态可能受前端实现影响。

正确判断标准应是：扫码后企微后台会话是否已经能通过只读接口。

推荐判定链路：

1. worker 打开企微开发者后台登录页并发送二维码。
2. worker 进入轮询，周期性检查登录态，最长等待配置的 TTL。
3. 每轮先从浏览器 Profile 或 cookie 源读取最新企微 cookie。
4. 使用最新 cookie 调用只读接口，例如当前预检已使用的：

```text
GET /wwopen/developer/customApp/tpl/app/list
```

5. 如果返回 `outsession`、登录页、401/403 或无法解析为预期 JSON，则仍视为未登录。
6. 如果接口返回有效 JSON，且能按 suiteid / 企业名查到目标代开发应用，则判定登录恢复成功。
7. 登录恢复成功后更新 `.local/wecom-admin.cookie` 或等价本地 cookie 源，再自动重新跑只读预检。

辅助判断可以包括：

- 页面 URL 从扫码登录页跳转到开发者后台页面。
- 页面中二维码元素消失。
- 页面出现已登录用户或开发者后台特征元素。

但这些只能作为辅助信号，最终仍以只读接口成功为准。

## 配置预期

第一版配置建议全部通过环境变量或 worker 本地配置文件，不写死在代码中：

```ini
WECOM_LOGIN_RECOVERY_ENABLED=true
WECOM_QR_NOTIFY_ENABLED=true
WECOM_QR_NOTIFY_WEBHOOK_URL=<从 Windows 本机安全配置读取，不提交到 Git>
WECOM_QR_NOTIFY_MODE=image
WECOM_QR_NOTIFY_MENTION_MOBILES=<可为空，或配置白名单管理员手机号>
WECOM_QR_TTL_SECONDS=120
WECOM_QR_MAX_NOTIFY_TIMES=3
WECOM_QR_ARTIFACT_DIR=.local/wecom-login-qr
WECOM_ADMIN_COOKIE_FILE=.local/wecom-admin.cookie
```

后续可扩展为：

- 按 task_type 配置是否允许二维码通知。
- 按 worker_id 配置通知群。
- 控制面配置通知策略，worker 只执行采集和上报。

## 安全边界

- 二维码只发到配置好的企微运维群机器人，不发给普通业务提交人。
- webhook URL、cookie、token 不进入 Git、日志、PR 或任务详情正文。
- 二维码图片必须有短 TTL，过期清理。
- 二维码通知必须有次数上限，避免无限刷屏。
- 控制面只记录状态、任务 ID、worker ID、通知时间、过期时间，不保存长期二维码原图。
- worker 发送的诊断信息必须脱敏。
- 登录恢复后仍先跑只读预检，不直接执行真实写入。

## 实现拆分与当前状态

### Task 1：通知模块抽象

状态：已完成。

- 已新增独立通知模块，支持 markdown/text/image。
- 已测试 base64/md5 生成、payload 格式、webhook 不进入 payload 或返回值。
- 未 import 或修改旧 `RPA.py`。

### Task 2：企微登录态检测与二维码采集

状态：已完成。

- 已新增登录态检查器，调用只读接口判定 cookie 是否有效。
- 已新增二维码采集器，打开企微服务商后台登录页并截取二维码。
- 已支持 iframe 中二维码捕获，并跳过尺寸过小的 loading/占位图。
- 二维码只保存到本地短期 artifact 目录。

### Task 3：worker 真实预检 handler

状态：第一版骨架已完成。

- 遇到 `wecom_session_expired` 时可发送二维码通知并轮询登录态恢复。
- 当前恢复后最多进入 `ready_for_real_bind` / `manual_confirm_required`，不默认真实写入。
- 真实 worker 任务流和控制面队列策略仍建议下一阶段单独验证。

### Task 4：恢复后自动重试预检

状态：编排骨架已完成，生产队列策略待优化。

- 扫码恢复后已支持重跑只读预检。
- `ok` 映射为 `ready_for_real_bind`，`review` 映射为 `manual_confirm_required`。
- 管理员超时未扫码后的重新触发二维码策略待下一阶段设计。

### Task 5：控制面状态与可观测性

状态：待下一阶段。

- 需要明确未登录时 worker 队列是否暂停，以及恢复登录后如何继续处理积压任务。
- 需要明确 `waiting_login`、二维码通知时间、过期时间、重试次数和最后错误在 CSM_C360 的记录方式。
- 需要明确超时未扫码时如何重新触发扫码通知，避免无限刷屏。

## 不做的事

- 不修改旧线上 `RPA.py`。
- 不部署或重启旧 `RPA.py` 服务。
- 不把真实 cookie/token/webhook 写入代码或文档。
- 不默认把二维码发给业务提交人。
- 不在第一版中默认无人值守真实写入。

## 新会话启动建议

新会话第一步必须：

```bash
git status -sb
```

并保护当前已有 WIP：

```text
scripts/dev/run_wecom_bind_real_write.py
tests/test_platform_wecom_bind_real_write.py
docs/superpowers/handoff/2026-06-15-rpa-platform-mac-dryrun-next-handoff.md
docs/superpowers/handoff/2026-06-16-rpa-platform-service-boundary-handoff.md
docs/superpowers/handoff/2026-06-16-rpa-platform-wecom-bind-real-success-handoff.md
```

建议新会话从“队列暂停/恢复策略”和“超时未扫码后的重新触发策略”开始，不先碰真实写入。

已知待优化点：

- 手动 PowerShell inline 脚本可能导致中文客户名显示为 `????`；生产路径应保证 WebSocket JSON、worker env 和 Python 源文件均为 UTF-8。
- 管理员超过 `WECOM_QR_TTL_SECONDS` 未扫码时，需要定义重新通知入口、最大通知次数和任务状态。
- 未登录期间，队列应暂停还是只暂停同类企微绑定任务，需要结合 CSM_C360 控制面状态机设计。
- 登录恢复后如何自动唤醒队列并重试只读预检，需要下一阶段补端到端任务流验证。

## 相关代码文件/模块

- `rpa_platform/worker/c360_worker.py`
- `rpa_platform/worker/c360_worker_runtime.py`
- `rpa_platform/worker/wecom_login_recovery.py`
- `rpa_platform/worker/wecom_bind_recovery_handler.py`
- `rpa_platform/notifications/wecom_bot.py`
- `rpa_platform/worker/simulated_handlers.py`
- `tests/test_platform_wecom_login_recovery.py`
- `tests/test_platform_wecom_bot.py`
- `tests/test_platform_wecom_bind_recovery_handler.py`
- `scripts/dev/check_wecom_bind_real_readonly.py`
- `scripts/dev/run_wecom_bind_real_write.py`
- `RPA.py`
- `docs/rpa_platform_windows_websocket_protocol.md`
- `docs/rpa_platform_windows_websocket_runbook.md`
