# RPA 平台 Windows WebSocket 执行协议草案

状态：2026-06-17 草案
适用范围：`rpa_platform/` 新平台化路径、jdycsm 控制面、Windows RPA 执行面
非目标：不改旧 `RPA.py`，不让外部系统直连 Windows，不上传 Cookie 或业务密钥明文

## 1. 目标

Windows 机器先部署完整 RPA 执行环境，由 Windows 服务主动 WebSocket 反连 jdycsm。所有外部业务请求统一进入 jdycsm，jdycsm 负责入库、派发、审计和状态机，Windows 只负责持有本地登录态并串行执行任务。

第一版只支持少量 Windows worker，每台 worker 单并发。协议优先保证可恢复、可审计、可避免重复真实写入，调度策略保持简单。

## 2. 边界

### 2.1 jdycsm 控制面

- 提供统一 HTTP API 接收业务请求。
- 校验请求、生成 `task_id` 和 `idempotency_key`。
- 保存任务 payload、状态、进度、结果和 artifact 索引。
- 根据 `machine_id`、`robot_id`、`capabilities` 查找在线连接。
- 通过 WebSocket 下发任务并接收 ack、progress、result、error。
- 连接断开时不丢任务，将任务置为 `worker_offline` 或 `waiting_worker`，等待重连 reconcile。

### 2.2 Windows RPA 执行面

- 启动后主动连接 jdycsm WebSocket。
- 本地生成并持久化稳定 `machine_id`，不要只依赖 hostname。
- 注册 `machine_id`、`robot_id`、hostname、版本、能力和登录态摘要。
- 本地保存浏览器 Profile、Cookie、截图原图、RPA 日志。
- 收到任务后单并发执行，实时回传步骤状态。
- Cookie、Token、headers、Authorization、password、secret、api_key、api-key、EncodingAESKey、kitsecret 等敏感明文不上传，只允许脱敏摘要。

## 3. 连接

建议入口：

```text
wss://jdycsm.example.com/rpa/ws/worker
```

鉴权方式第一版使用机器级 token：

```http
Authorization: Bearer <machine_token>
X-RPA-Machine-ID: <stable_machine_id>
X-RPA-Robot-ID: <robot_id>
```

后续可以升级为 mTLS，但第一版不引入证书生命周期复杂度。

## 4. 消息信封

所有 WebSocket 消息使用统一信封：

```json
{
  "type": "task.dispatch",
  "message_id": "01JZ0000000000000000000000",
  "sent_at": "2026-06-17T10:00:00+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {}
}
```

字段规则：

- `type`：消息类型，使用点分命名。
- `message_id`：消息唯一 ID，用于 ack 和排障。
- `sent_at`：ISO 8601 时间。
- `machine_id`：Windows 本地稳定机器 ID。
- `robot_id`：执行机器人 ID，与现有 `robots.id` 对齐。
- `payload`：消息体，禁止放 Cookie、headers、Authorization、password、secret、api_key、api-key 或密钥明文。

## 5. 消息类型

### 5.1 worker.register

Windows 连接成功后立即发送。

```json
{
  "type": "worker.register",
  "message_id": "msg_register_001",
  "sent_at": "2026-06-17T10:00:00+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "hostname": "WIN-RPA-01",
    "service_version": "0.1.0",
    "capabilities": {
      "wecom_bind_service": true,
      "wecom_client_rpa": false,
      "browser_profile": true,
      "single_concurrency": true
    },
    "login_health": {
      "jdy_admin": "unknown",
      "wecom_admin": "unknown",
      "checked_at": null
    },
    "current_task": null
  }
}
```

jdycsm 收到后更新 worker 在线状态和能力。如果 `current_task` 非空，进入 reconcile。

### 5.2 worker.heartbeat

Windows 每 15 秒发送一次。

```json
{
  "type": "worker.heartbeat",
  "message_id": "msg_heartbeat_001",
  "sent_at": "2026-06-17T10:00:15+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "status": "idle",
    "current_task_id": null,
    "queue_depth_local": 0,
    "login_health": {
      "jdy_admin": "ok",
      "wecom_admin": "ok",
      "checked_at": "2026-06-17T10:00:12+08:00"
    }
  }
}
```

jdycsm 超过 45 秒未收到 heartbeat 时，将连接标记为离线。若有已派发未完成任务，状态置为 `worker_offline`，等待 worker 重连上报。

### 5.3 task.dispatch

jdycsm 下发任务给 Windows。

```json
{
  "type": "task.dispatch",
  "message_id": "msg_dispatch_001",
  "sent_at": "2026-06-17T10:01:00+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "task_id": "task_001",
    "idempotency_key": "wecom_bind_service:ww001:user-1",
    "flow_type": "wecom_bind_service",
    "requested_capability": "wecom_bind_service",
    "deadline_at": "2026-06-17T10:31:00+08:00",
    "task_payload": {
      "enterprise_name": "上海测试客户",
      "plain_corp_id": "ww001",
      "requested_user_id": "user-1"
    },
    "runtime_context": {
      "retry_count": 0,
      "resume_from": null
    }
  }
}
```

Windows 收到后必须先落本地执行记录，再 ack，防止 ack 后进程退出导致任务丢失。

### 5.4 task.ack

Windows 确认已接收任务。

```json
{
  "type": "task.ack",
  "message_id": "msg_ack_001",
  "sent_at": "2026-06-17T10:01:01+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "task_id": "task_001",
    "dispatch_message_id": "msg_dispatch_001",
    "accepted": true,
    "local_execution_id": "local_001"
  }
}
```

如果 worker 正忙或能力不匹配，返回 `accepted=false`，jdycsm 重新调度。

### 5.5 task.progress

Windows 回传步骤进度。

```json
{
  "type": "task.progress",
  "message_id": "msg_progress_001",
  "sent_at": "2026-06-17T10:02:00+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "task_id": "task_001",
    "status": "running",
    "step_key": "jdy_resolve_corp",
    "step_name": "查询简道云企业部署",
    "attempt": 1,
    "output": {
      "corp_secret_id": "cor***001",
      "owner_state": "can_bind_corp_secret"
    },
    "artifact_refs": []
  }
}
```

`output` 必须先脱敏。截图原图默认留在 Windows 本地，jdycsm 只保存索引：

```json
{
  "artifact_refs": [
    {
      "artifact_type": "screenshot",
      "artifact_id": "shot_001",
      "local_path_hint": "C:/rpa/artifacts/task_001/shot_001.png",
      "sha256": "optional"
    }
  ]
}
```

### 5.6 task.result

任务成功或进入可等待状态时发送。

```json
{
  "type": "task.result",
  "message_id": "msg_result_001",
  "sent_at": "2026-06-17T10:05:00+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "task_id": "task_001",
    "final_status": "waiting_wecom_online_delay",
    "next_check_at": "2026-06-17T10:10:00+08:00",
    "result_summary": {
      "auditorderid": "ord***001",
      "corpapp_id": "app***001"
    },
    "runtime_context_patch": {
      "wecom": {
        "auditorderid": "ord***001"
      }
    }
  }
}
```

`final_status` 应兼容现有平台状态机。第一版远端协议可额外展示 `dispatched`、`worker_offline`、`waiting_worker`，但落到现有 `rpa_platform` 代码时要明确映射。

### 5.7 task.error

任务失败、需要人工或登录失效时发送。

```json
{
  "type": "task.error",
  "message_id": "msg_error_001",
  "sent_at": "2026-06-17T10:03:00+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "task_id": "task_001",
    "status": "waiting_login",
    "error_type": "LOGIN_REQUIRED",
    "error_message": "企微后台登录态失效，需要人工扫码",
    "step_key": "wecom_submit_online",
    "retryable": true,
    "manual_action": {
      "action_type": "login_required",
      "target": "wecom_admin",
      "notify_audience": "rpa_admins",
      "notification_channel": "wecom_bot",
      "notification_mode": "link_only",
      "handle_url": "https://jdycsm.example.com/rpa/manual-actions/action_001",
      "qr_delivery": "not_uploaded"
    },
    "artifact_refs": []
  }
}
```

`waiting_login` 的默认通知策略：

- Windows worker 只上报登录态失效、目标系统和本地诊断摘要，不直接决定通知谁。
- jdycsm 控制面创建 `manual_action`，再通过企微机器人通知 RPA 运维/机器人管理员。
- 企微消息默认只包含任务、机器、目标系统和 jdycsm 处理链接，不附带二维码原图。
- 默认处理方式是管理员远程到对应 Windows 机器，在固定浏览器 Profile 内扫码续登。
- 提交业务请求的普通用户不接收登录二维码，最多看到任务处于 `waiting_login` 或“等待机器人登录恢复”。

第一版不建议上传或群发二维码截图。若后续确实需要二维码转发，必须作为显式配置能力：

- 只允许发送给白名单管理员私聊或专用安全群，不发给业务用户。
- 二维码 artifact 设置短 TTL，到期删除。
- jdycsm 只保存脱敏索引、触发人、接收人、过期时间和处理结果。
- 二维码不能写入普通日志、PR、任务详情正文或长期 artifact。
- 扫码后仍以 Windows worker heartbeat/login health 作为恢复依据。

### 5.8 worker.diagnostics

Windows 调试时发送脱敏诊断摘要。该消息只能包含环境、进程、网络、登录态、artifact 索引和最近错误摘要，不允许包含 Cookie、Token、headers、Authorization、password、secret、api_key、api-key、EncodingAESKey、kitsecret、页面原始截图或完整日志。

```json
{
  "type": "worker.diagnostics",
  "message_id": "msg_diag_001",
  "sent_at": "2026-06-17T10:04:00+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "diagnostic_id": "diag_001",
    "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
    "robot_id": "windows-rpa-01",
    "task_id": "task_001",
    "mode": "manual_debug",
    "windows": {
      "hostname": "WIN-RPA-01",
      "session_name": "console",
      "interactive_desktop": true,
      "screen_resolution": "1920x1080",
      "display_scaling": "100%"
    },
    "worker": {
      "pid": 1234,
      "service_version": "0.1.0",
      "started_at": "2026-06-17T09:55:00+08:00",
      "current_task_id": "task_001"
    },
    "network": {
      "wss_connected": true,
      "last_heartbeat_at": "2026-06-17T10:03:45+08:00"
    },
    "local_refs": {
      "log_path_hint": "C:/rpa_group/logs/worker.log",
      "artifact_dir_hint": "C:/rpa_group/artifacts/task_001",
      "sqlite_path_hint": "C:/rpa_group/data/platform-worker.db"
    },
    "recent_errors": [
      {
        "at": "2026-06-17T10:03:00+08:00",
        "error_type": "LOGIN_REQUIRED",
        "step_key": "wecom_submit_online",
        "message": "企微后台登录态失效，需要人工扫码"
      }
    ]
  }
}
```

诊断消息的作用是让 jdycsm 知道“去 Windows 哪里看”和“当前是否具备交互式 RPA 条件”。本地 `--diagnose` 只打印同结构的脱敏 JSON，不建立 WebSocket 连接；在线诊断可通过 `worker.diagnostics` 信封发送同结构 payload。原始截图、浏览器 trace、完整日志和 Cookie 仍默认留在 Windows 本机。

## 6. 状态映射

### 6.1 jdycsm 控制面状态

```text
pending
dispatched
running
waiting_login
manual_required
waiting_worker
worker_offline
success
failed
```

### 6.2 rpa_platform 现有状态

当前 `rpa_platform.domain.state_machine.TaskStatus` 已有：

```text
pending
checking_login
running
waiting_login
waiting_manual_selection
waiting_manual_intervention
waiting_wecom_review
waiting_wecom_online_delay
ready_to_online
waiting_test_confirmation
jdy_callback_failed
success
failed
cancelled
```

第一版映射建议：

| jdycsm 状态 | rpa_platform 状态 | 说明 |
| --- | --- | --- |
| `pending` | `pending` | 已入库未派发 |
| `dispatched` | `checking_login` 或新增远端派发态 | 已发给 worker，等待 ack/登录检查 |
| `running` | `running` | Windows 正在执行 |
| `waiting_login` | `waiting_login` | 需要人工扫码 |
| `manual_required` | `waiting_manual_intervention` | 需要人工处理 |
| `waiting_worker` | `pending` 或新增状态 | 没有可用 worker |
| `worker_offline` | 建议新增状态或保存在远端调度字段 | 已派发 worker 断线 |
| `success` | `success` | 完成 |
| `failed` | `failed` | 失败终止 |

如果短期不改状态机，`worker_offline` 和 `waiting_worker` 可先作为 jdycsm 控制面的调度状态，不直接写入 Windows 本地 `TaskStatus`。

## 7. 幂等和重连

- 外部请求必须携带或派生 `idempotency_key`。
- jdycsm 的任务表对 `idempotency_key` 建唯一约束，重复请求返回已有 `task_id`。
- Windows 本地也保存 `task_id`、`idempotency_key`、`local_execution_id` 和最近结果。
- WebSocket 重连后，worker.register 必须上报 `current_task`。
- 若 worker 上报任务仍在运行，jdycsm 将任务恢复为 `running`。
- 若 worker 上报任务已完成但 jdycsm 未收到 result，jdycsm 接受补发 result。
- 若 jdycsm 认为任务可重试，但 Windows 本地已有同一 `idempotency_key` 的成功记录，Windows 必须拒绝重复真实写入并回传既有结果摘要。

## 8. Windows 调试策略

Windows worker 必须内置可触发的诊断模式，避免只靠远程桌面临场猜测。调试信息分三层：

1. jdycsm 可见：脱敏状态、最近错误、路径索引、心跳和登录态摘要。
2. Windows 本地可见：完整日志、SQLite、本地 artifact、截图原图、浏览器 trace。
3. 人工远程可见：交互桌面、浏览器 Profile、企微/简道云真实页面。

调试模式要求：

- 每条日志带 `task_id`、`machine_id`、`robot_id`、`local_execution_id`。
- 支持 `--diagnose` 或 jdycsm 触发的诊断动作，产出 `worker.diagnostics`。
- 支持只读诊断，不 claim 新任务、不执行真实写入。
- 本地重放最后一条 `task.dispatch` 属于后续规划；若未来实现，默认应为 dry-run，真实写入必须显式确认。当前 worker CLI 不提供任务重放命令。
- 支持记录屏幕分辨率、DPI 缩放、当前 Windows session、进程身份和浏览器 Profile 路径。
- 诊断摘要不得包含 Cookie、Token、headers、Authorization、password、secret、api_key、api-key、EncodingAESKey、kitsecret、完整 HTML、完整截图或请求头明文。

Windows 交互式 RPA 的关键限制：

- PyAutoGUI、企业微信客户端和可视浏览器自动化不能依赖 Session 0 服务桌面。
- 第一版建议先用命令行或登录用户的计划任务运行，确认交互桌面稳定后再考虑服务化。
- RDP 断开可能改变桌面会话、分辨率或锁屏状态；涉及 UI 自动化时必须验证断开后的执行行为。
- 分辨率和缩放必须固定，优先使用 1920x1080、100% 缩放。
- 浏览器 Profile 必须由运行 worker 的同一 Windows 用户访问，避免 Profile 锁和 Cookie 不可见。

## 9. 企微客户端自动建群能力

企微客户端自动建群属于独立能力族，能力名建议为：

```text
wecom_client_rpa_create_group
```

它和企微绑定服务共享 WebSocket、任务状态、日志、artifact、人工介入和单并发调度，但执行引擎单独封装。企微绑定服务偏接口/后台网页；企微客户端建群偏 Windows 桌面应用自动化，不要把两者混成一个 runner。

### 9.1 task.dispatch payload

```json
{
  "type": "task.dispatch",
  "message_id": "msg_dispatch_create_group_001",
  "sent_at": "2026-06-17T11:00:00+08:00",
  "machine_id": "mch_4c6f4d8f-5f6b-4c56-9c7e-7f7d4a6a1d22",
  "robot_id": "windows-rpa-01",
  "payload": {
    "task_id": "task_create_group_001",
    "idempotency_key": "wecom_create_group:zh_test:customer_001:20260617",
    "flow_type": "wecom_client_rpa_create_group",
    "requested_capability": "wecom_client_rpa_create_group",
    "task_payload": {
      "group_type": "企微群",
      "customer_name": "zh_test_上海测试客户",
      "group_name": "zh_test_上海测试客户_服务群",
      "owner_name": "张三",
      "member_names": ["李四", "王五"],
      "test_mode": true,
      "operator_note": "真实测试群验证"
    },
    "runtime_context": {
      "template_id": "tpl_wecom_create_group_v1",
      "confirm_write": true
    }
  }
}
```

建群是真实副作用任务。第一版允许使用真实测试群验证，但任务必须带 `test_mode=true` 或显式 `confirm_write=true`，并且群名建议使用 `zh_test` 前缀，避免误触达真实客户。

### 9.2 元素化命令模型

旧 `RPA.py` 的截图/坐标动作应迁移为元素化命令，执行优先级如下：

```text
Windows UI Automation selector
-> 快捷键 / 剪贴板 / 窗口级动作
-> OCR / 图像识别
-> 坐标点击兜底
```

命令示例：

```json
{
  "step_key": "open_create_group",
  "step_name": "打开发起群聊入口",
  "action": "click_element",
  "target": {
    "type": "uia",
    "window_title": "企业微信",
    "control_type": "Button",
    "name": "发起群聊",
    "class_name": "",
    "automation_id": ""
  },
  "fallback": {
    "type": "image",
    "image_key": "wecom_create_group_button",
    "click_position": null
  },
  "assert_after": {
    "type": "uia",
    "name": "选择联系人"
  },
  "retry": {
    "times": 2,
    "interval_seconds": 1
  }
}
```

命令模型当前支持的动作：

- `activate_app`：激活企业微信窗口。
- `find_element`：按 UIA selector 查找元素。
- `click_element`：点击 UIA 元素中心点或调用可用的 invoke pattern。
- `set_text`：对输入框设置文本，必要时用剪贴板粘贴兜底。
- `clipboard_paste`：从剪贴板粘贴文本。
- `send_hotkey`：发送快捷键。
- `wait_until`：等待元素、图片或窗口状态出现。
- `assert_element`：断言目标元素存在。
- `capture_artifact`：保存本地截图或诊断 artifact。
- `fallback_image_click`：图像识别兜底。
- `fallback_position_click`：坐标兜底，必须标记 `risk_level=high`。

### 9.3 配置页和元素拾取器

命令配置页面向业务同学，但要分层：

- 业务层：选择“企微自动建群”模板，填写客户名称、群名称、群主、成员、是否测试群、通知管理员。
- 高级层：由 RPA 管理员维护 UIA selector、fallback 图片、重试、断言和失败处理。

Windows 端元素拾取器作为 worker 的本地模式，不要求第一版打包 exe。建议交互：

```text
jdycsm 配置页点击“开始拾取”
-> WebSocket 通知 Windows worker 进入 picker 模式
-> 管理员在企微客户端上悬停目标控件
-> 按全局快捷键 Ctrl+Alt+P
-> worker 读取鼠标下 UIA 元素
-> 回传 selector 和截图索引
-> jdycsm 配置页展示并允许测试定位
```

快捷键捕获是为了避免“点击捕获”误触发真实企微操作。拾取器回传的数据必须脱敏，只包含元素元数据和本地截图索引，不上传业务页面截图原图。

### 9.4 自动建群第一版流程

第一版流程建议：

```text
激活企业微信
-> 确认主窗口可用
-> 打开发起群聊入口
-> 搜索/选择群主或创建者上下文
-> 搜索并选择群成员
-> 设置群名称
-> 确认创建
-> 校验群窗口/群名称出现
-> 保存截图和步骤日志到 Windows 本地
-> 回传 success/result_summary
```

验收标准：

- 使用真实测试群完成端到端建群。
- 每次只执行一个建群任务。
- 失败时本地保存截图和 UIA 诊断摘要。
- jdycsm 只保存状态、步骤、错误和 artifact 索引。
- 业务同学只能使用已发布模板发起测试或生产任务，不能直接编辑高级 selector。

## 10. artifact 策略

第一版只上传索引，不上传原始截图和日志：

```json
{
  "artifact_id": "shot_001",
  "task_id": "task_001",
  "artifact_type": "screenshot",
  "stored_on": "worker",
  "local_path_hint": "C:/rpa/artifacts/task_001/shot_001.png",
  "redaction": "not_uploaded",
  "created_at": "2026-06-17T10:02:30+08:00"
}
```

需要排障时，先由运维远程到 Windows 查看原图。后续如要上传，必须先定义脱敏策略和访问控制。

## 11. 相关代码文件/模块

- `rpa_platform/worker/scheduler.py`：现有 `TaskScheduler.run_once()` 最小 claim-and-execute 挂点。
- `rpa_platform/worker/runner.py`：`run_claimed_task(task_id, robot_id, now)` runner 协议。
- `rpa_platform/worker/wecom_bind_runner.py`：企微绑定接口服务 runner，可作为第一批远端任务能力。
- `rpa_platform/worker/wecom_client_runner.py`：建议新增的企微客户端 RPA runner。
- `rpa_platform/worker/uia_driver.py`：建议新增的 Windows UI Automation 执行适配器。
- `rpa_platform/worker/element_picker.py`：建议新增的 Windows 元素拾取器。
- `rpa_platform/storage/sqlite_store.py`：任务、机器人、幂等键、步骤和 artifact 表。
- `rpa_platform/domain/state_machine.py`：现有任务状态机。
- `rpa_platform/worker/diagnostics.py`：建议新增的 Windows 本地诊断摘要模块。
- `scripts/dev/run_platform_worker_once.py`：本地一次性执行入口。
- `scripts/dev/run_platform_dryrun.py`：本地 fake transport 验证入口。
