# RPA 企微登录态恢复自动化交接

## 生命周期

- 状态：阶段性完成
- 当前阶段：企微服务商后台登录态恢复只读闭环已完成；CSM_C360 原始事件持久化已完成并通过 Windows worker simulation 生产复验；RPA_GROUP 真实只读 handler 本地接入已完成，待 Windows Server 执行 `RPA_WORKER_SIMULATE=false` 真机只读验证
- 最近更新：2026-06-20
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

### 5. CSM_C360 到 Windows worker 模拟派发和事件持久化已生产复验

本阶段新增并推送了三个优化提交：

- `8eb9980 feat: 优化企微登录恢复重试和队列状态`
- `08d7491 fix: 修复 Windows 预览输出编码`
- `2c214dd feat: 增加 C360 worker 脱敏日志输出`

Windows Server 在 Conda 环境 `RPA_GROUP` 中运行：

```powershell
conda activate RPA_GROUP
cd C:\rpa_work\RPA_GROUP
python -m rpa_platform.worker.c360_worker --once --verbose
```

控制面派发一条 `zh_test` 的 `wecom_bind_service` 模拟任务后，Windows PowerShell 已观察到完整生命周期。当前 Windows App 键盘输入会吞掉 `_` 等字符，实际操作时可用 PowerShell 历史 `h` / `r <编号>` 重放已验证命令，避免手输模块名：

```text
worker connecting worker_id=win-server-001 ws_url=wss://jdycsm.sre.jdydevelop.com/csm-c360-api/v1/rpa/workers/ws simulate=True
worker hello sent worker_id=win-server-001 simulate=True
worker accepted worker_id=win-server-001
task received task_id=5a4410adb49f413ea0db5d36314652cf task_type=wecom_bind_service simulate=True
task accepted task_id=5a4410adb49f413ea0db5d36314652cf
task progress task_id=5a4410adb49f413ea0db5d36314652cf status=running
task completed task_id=5a4410adb49f413ea0db5d36314652cf status=succeeded
```

CSM_C360 控制面事件查询结果：

```text
task_id=5a4410adb49f413ea0db5d36314652cf
task_type=wecom_bind_service
status=succeeded
worker_id=win-server-001
result_simulated=true
event_count=4
event_types=task.dispatch,task.accepted,task.progress,task.completed
event_order_valid=true
```

本次查询方式：

```bash
cd /Users/hugh/jdycsm_project/CSM_C360
PYTHONPATH=src:. python scripts/manual/query_rpa_task_events.py \
  --base-url https://jdycsm.sre.jdydevelop.com/csm-c360-api \
  --task-id 5a4410adb49f413ea0db5d36314652cf \
  --expect-simulated \
  --expect-event-order
```

当前 `python -m rpa_platform.worker.c360_worker --once --verbose` 仍是模拟 handler：

- 会验证 WebSocket 连接、鉴权、任务派发、accepted/progress/completed 回传、控制面任务主记录落库和事件表查询。
- 不执行真实企微绑定写入。
- 不写简道云。
- 不打开真实绑定浏览器流程。
- 不修改旧线上 `RPA.py`。

### 6. RPA_GROUP 真实只读 handler 本地接入已完成

本阶段新增 CSM_C360 worker handler factory：

```text
RPA_WORKER_SIMULATE=true
-> 保持现有 simulation 行为

RPA_WORKER_SIMULATE=false
-> diagnostics / runtime_health_check 仍走安全模拟诊断
-> wecom_bind_service 走真实 WecomBindRecoveryTaskHandler
```

真实 handler 只做：

- CSM_C360 dispatch payload 到 `JdyWecomBindInput` 的映射。
- 真实只读预检。
- 企微服务商后台登录态检测。
- QR 登录恢复和 cookie 刷新。
- 扫码恢复后重跑只读预检。
- `task.progress` / `task.completed` 事件上报。

本地已验证事件序列：

```text
task.accepted
task.progress status=running
task.progress status=readonly_preflight_started
task.progress status=readonly_preflight_completed 或 waiting_login
task.completed status=ready_for_real_bind / manual_confirm_required / manual_action_required
```

本地测试命令：

```bash
python -m pytest \
  tests/test_platform_c360_worker_runtime.py \
  tests/test_platform_c360_worker_client.py \
  tests/test_platform_c360_task_handlers.py \
  tests/test_platform_wecom_bind_recovery_handler.py \
  tests/test_platform_wecom_bind_real_recovery.py \
  tests/test_platform_wecom_login_recovery.py \
  tests/test_platform_wecom_bot.py
```

截至本文档更新时，Windows Server 的 `RPA_WORKER_SIMULATE=false` 真机只读验证尚未在本会话执行。下一步应在 Windows 本机用安全环境变量启动：

```powershell
conda activate RPA_GROUP
cd C:\rpa_work\RPA_GROUP
python -m rpa_platform.worker.c360_worker --once --verbose
```

允许记录的脱敏 proof 字符串：

```text
TASK_RECEIVED
READONLY_PREFLIGHT_STARTED
WAITING_LOGIN
QR_NOTIFIED
LOGIN_STATUS restored
READONLY_PREFLIGHT_COMPLETED
TASK_COMPLETED ready_for_real_bind
EVENT_HISTORY_STORED
```

继续不做：

- 不执行真实企微绑定写入。
- 不写简道云。
- 不修改、导入、重启或部署旧线上 `RPA.py`。
- 不提交真实 webhook、Cookie、Token、QR 图片、截图、日志或数据库内容。

### 7. 当前执行情况保存方式

截至 2026-06-20，CSM_C360 控制面已经保存任务主记录，并已保存每一步原始事件历史。

当前已保存到 `rpa_tasks` 的内容包括：

- `task_id`
- `task_type`
- `source_type` / `source_app_id` / `source_form_id` / `source_entry_id` / `source_data_id`
- `route_key`
- `status`
- `idempotency_key`
- `request_json`
- `normalized_json`
- `result_json`
- `api_key_fingerprint`
- `worker_id`
- `error_message`
- `dispatched_at`
- `started_at`
- `finished_at`
- `created_at` / `updated_at`

当前状态流转由 CSM_C360 控制面处理：

- 创建任务时写入 `status=queued`。
- 派发给 worker 时写入 `status=dispatched`、`worker_id`、`dispatched_at`。
- 收到 `task.accepted` 或 `task.progress` 时写入 `status=running`，并补 `started_at`。
- 收到 `task.completed` 时写入 `status=succeeded` 或 `status=failed`，并保存 `result_json`、`error_message`、`finished_at`。

当前已保存到 `rpa_task_events` 或等价事件表的内容包括：

- `task.dispatch` 控制面下发事件。
- `task.accepted`、`task.progress`、`task.completed` 每条 WebSocket 消息的原始 JSON。
- 多条 progress 的时间序列。
- 细粒度步骤开始、步骤完成、步骤失败、重试、二维码通知、等待扫码等事件历史的承载入口。

用户已确认事件表中“执行日志/每一步骤情况不用脱敏，原样保存即可”。当前边界是：`rpa_task_events.event_json` 保存原始 JSON；`rpa_tasks` 主记录继续用于列表、筛选和最终状态查询。

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

状态：第一版 worker 侧状态已完成。

- 遇到 `wecom_session_expired` 时可发送二维码通知并轮询登录态恢复。
- 当前恢复后最多进入 `ready_for_real_bind` / `manual_confirm_required`，不默认真实写入。
- `waiting_login` 会映射为 `manual_action_required`，并带 `queue_control.action=pause`、`scope=wecom_bind_service`，表达只暂停企微绑定类任务。
- `ready_for_real_bind` / `manual_confirm_required` 会带 `queue_control.action=resume`，表达登录已恢复、同类队列可恢复调度。
- CSM_C360 控制面的落库、调度暂停和自动恢复仍需要跨仓实现，本仓只先定义 worker 可消费结果/事件。

### Task 4：恢复后自动重试预检

状态：编排骨架和 QR 重触发状态已完成。

- 扫码恢复后已支持重跑只读预检。
- `ok` 映射为 `ready_for_real_bind`，`review` 映射为 `manual_confirm_required`。
- 管理员超时未扫码时返回 `waiting_login`、`reason=wecom_login_not_restored`、`expires_at`、`notify_attempts`、`remaining_notify_attempts`、`next_action` 和 `retry_after`。
- 控制面重新派发时可把 `notify_attempts` 或 `login_recovery.notify_attempts` 带回 worker；未超过 `WECOM_QR_MAX_NOTIFY_TIMES` 时会重新生成/发送 QR 并继续只读验证。
- 达到通知上限时返回 `login_recovery_notify_exhausted` 和 `manual_action=manual_escalation_required`，不会继续生成/发送 QR，避免无限刷屏。

### Task 5：控制面状态与可观测性

状态：worker 结果契约、本机 verbose 可观测性、控制面原始事件持久化均已完成生产 simulation 验证。

- 未登录期间第一版建议暂停同类 `wecom_bind_service` 队列，不暂停诊断类任务，也不触碰旧 `RPA.py` 队列。
- `waiting_login`、二维码过期时间、通知次数、剩余次数和下一步动作已由 worker result/progress 提供给 CSM_C360 消费。
- CSM_C360 当前会保存任务主记录、最终 `result_json`，并保存每条 dispatch/accepted/progress/completed 的原始事件历史。
- RPA_GROUP 真实企微只读 handler 本地接入已完成；Windows Server 真机只读验证、人工处理单、同类队列暂停/恢复和积压任务恢复仍需后续补齐。
- 超时未扫码时队列保持暂停；仍有剩余通知次数则允许重新触发 QR，次数耗尽后进入人工升级。

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

CSM_C360 控制面“原始事件持久化”已完成并通过生产 simulation 复验。RPA_GROUP 已完成真实企微只读 handler 的本地接入，不先碰真实写入。执行计划记录在：

```text
docs/superpowers/plans/2026-06-20-rpa-wecom-real-handler-integration.md
```

进入该计划前的已满足前置条件：

1. CSM_C360 已新增 `rpa_task_events` 或等价事件表。
2. 控制面派发 `task.dispatch` 时已保存原始下发 payload。
3. worker 回传 `task.accepted`、`task.progress`、`task.completed` 时已保存原始 WebSocket JSON。
4. `GET /v1/rpa/tasks/{task_id}/events` 和 `scripts/manual/query_rpa_task_events.py` 可查询事件列表。
5. Windows worker `--once --verbose` 已用 `task_id=5a4410adb49f413ea0db5d36314652cf` 验证事件顺序。

该计划的本地代码目标已完成：`c360_worker` 从纯模拟 `wecom_bind_service` 接到真实 `WecomBindRecoveryTaskHandler`，但仍只跑只读预检、QR 登录恢复和状态上报；真实企微绑定写入、简道云写入继续保持关闭，等待用户单独确认。下一步是在 Windows Server 以 `RPA_WORKER_SIMULATE=false` 做真机只读验证。

已知待优化点：

- 手动 PowerShell inline 脚本可能导致中文客户名显示为 `????`；当前已新增 UTF-8 本地预览入口：

```powershell
cd C:\rpa_work\RPA_GROUP
.\.venv\Scripts\Activate.ps1
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
python -m rpa_platform.worker.wecom_login_notification_preview --task-id task-utf8 --enterprise-name "上海测试客户" --expires-at 1000
```

- CSM_C360 需要消费 `queue_control.action=pause/resume`、`scope=wecom_bind_service`、`notify_attempts`、`remaining_notify_attempts`、`next_action` 和 `retry_after`。
- 登录恢复后如何自动唤醒控制面同类队列并重试只读预检，需要下一阶段补端到端任务流验证。
- RPA_GROUP 当前 `RPA_WORKER_SIMULATE=false` 已路由到真实 `WecomBindRecoveryTaskHandler`；真实写入开关仍未打开，需要用户单独确认后再推进。

## 相关代码文件/模块

- `rpa_platform/worker/c360_worker.py`
- `rpa_platform/worker/c360_worker_runtime.py`
- `rpa_platform/worker/wecom_login_recovery.py`
- `rpa_platform/worker/wecom_login_notification_preview.py`
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
- `docs/superpowers/plans/2026-06-20-rpa-task-raw-event-persistence.md`
- `docs/superpowers/plans/2026-06-20-rpa-wecom-real-handler-integration.md`
