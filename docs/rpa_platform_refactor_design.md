# RPA 平台化重构设计

## 1. 背景

当前 `RPA_GROUP` 已经稳定运行，主要依赖 FastAPI、SQLite、后台 Worker、PyAutoGUI、图片识别、坐标点击和 Excel 步骤配置，支撑企业微信/钉钉建群、群发消息、风控暂停恢复等流程。

后续目标是把它升级为内部多团队可复用的 RPA 平台。新系统不做商业化，对内使用，重点解决：

- Excel 配置不易维护和复用。
- 图像识别/坐标依赖强，新电脑、新分辨率、新页面版本都需要重新截图。
- 跨后台浏览器操作需要更可靠的定位、重试、恢复和审计。
- 多团队需要按流程、团队、通知配置复用。
- 后续需要接入 AI，但 AI 第一版只做异常诊断，不直接执行点击或输入。

本设计面向一次较大的本地重构：新 API、新配置、新数据模型、新执行框架。旧系统只作为流程和经验参考，不要求兼容旧 API 或旧 Excel 执行入口。

## 2. 已确认决策

### 2.1 系统边界

- 完全新系统，不兼容旧 API。
- 新 API、新配置、新数据模型。
- 旧 `RPA.py`、Excel 和图片动作作为业务经验参考，不作为新系统必须兼容的入口。
- 架构按 `server` 与 `worker` 分离设计。
- 第一版部署时可以同机运行在一台 Windows Server 上。
- 第一版只有一台 Windows 机器人，同一时间只执行一个可运行任务。

### 2.2 样板流程

第一条样板流程为：**简道云 Webhook 触发的企业微信代开发应用上线流程**。

核心链路：

1. 用户在简道云表单提交申请。
2. 简道云通过 Webhook/API 推送任务到 RPA 系统。
3. RPA 打开简道云后台企业微信绑定弹窗。
4. RPA 从简道云后台读取企业 ID/密文 ID。
5. RPA 根据固定规则生成企微后台需要的主页 URL、回调 URL 和可信域名。
6. RPA 打开企微后台授权客户列表。
7. RPA 按企业客户名称定位目标企业，进入“开始代开发应用”流程。
8. RPA 填写企微后台开发配置，并读取企微生成的 `token` 和 `EncodingAESKey`。
9. RPA 回到简道云后台绑定弹窗，回填 `token` 和 `EncodingAESKey`，点击确定。
10. 企微后台出现审核状态后，任务进入等待审核状态。
11. 定时检查企微审核状态，状态进入可上线时自动执行上线。
12. 企微后台显示“已上线”后，任务成功。
13. 调用简道云 API 提交/回写结果。
14. 按团队/流程通知配置发送企微机器人通知。

### 2.3 AI 范围

- 第一版 AI 只做异常诊断，不执行点击、输入、滚动等操作。
- AI 输入包括截图、当前步骤、当前 URL、页面文本/DOM 摘要、最近日志和任务上下文。
- AI 输出结构化异常分类、置信度、原因说明和建议动作。
- 第一版不做复杂截图脱敏；截图可完整保存并用于 AI 诊断。
- 截图和任务详情默认仅管理员可见。

后续可以扩展操作型 AI，但本设计第一版不包含。

## 3. 目标架构

```text
rpa_server
  - Web 控制台
  - Webhook 接收
  - 流程模板和版本管理
  - 任务队列和状态机
  - 通知配置
  - 简道云 API 回写
  - 审计日志和截图管理

rpa_worker
  - Playwright 浏览器执行
  - Windows 浏览器 profile
  - 登录态健康检查
  - 步骤执行、重试、截图、trace
  - AI 异常诊断调用
  - 人工接管恢复

Windows Server
  - 第一版同机运行 rpa_server 和 rpa_worker
  - 固定 Chrome/Edge profile
  - 管理员扫码维护简道云后台和企微后台登录态
```

### 3.1 执行优先级

```text
1. Playwright 确定性步骤
2. 步骤级重试和页面恢复
3. AI 异常诊断
4. 人工选择或人工远程接管
```

第一版主执行器为 Playwright。后续可扩展 UIA、PyAutoGUI/视觉识别、Computer Use 操作兜底等适配器。

## 4. 登录态设计

简道云后台和企微后台都只能扫码登录，不支持账号密码登录。因此登录不能作为普通自动化步骤处理。

### 4.1 登录模型

- Windows Server 上维护固定浏览器 profile。
- 管理员人工扫码登录简道云后台和企微后台。
- Worker 使用持久化浏览器 profile 执行任务。
- 每个任务开始前进行登录态健康检查。
- 如果登录失效，任务进入 `waiting_login`。
- 管理员扫码后，Runner 不依赖当前页面，而是重新打开固定入口 URL 并恢复执行。

### 4.2 扫码后页面回首页的处理

扫码成功后页面可能回到首页，因此任务必须保存：

- 当前阶段和步骤游标。
- 简道云固定入口 URL。
- 企微固定入口 URL。
- 企业客户名称。
- 明文 CorpID。
- 已读取或已生成的关键字段。

恢复时：

```text
检查登录态恢复
-> 重新打开对应固定入口 URL
-> 重新搜索/定位目标记录或企业
-> 校验当前阶段可继续
-> 从安全检查点继续
```

## 5. 样板流程详细设计

### 5.1 Webhook 输入

简道云 Webhook payload 至少包含：

- `user_id`
- 企业客户名称
- 企业微信 CorpID（明文）

Webhook 接收层要求：

- 保存原始 payload。
- 校验来源。
- 使用幂等键防止重复任务。
- 快速返回成功，避免上游重复推送。

建议幂等键：

```text
idempotency_key = flow_type + corp_id + user_id
```

如果 payload 后续提供稳定记录 ID，则将记录 ID 纳入幂等键；第一版按 `flow_type + corp_id + user_id` 处理，并在任务中记录收到的完整 payload 摘要。

### 5.2 简道云后台步骤

打开简道云固定入口后：

1. 使用明文 CorpID 或企业客户名称搜索/定位记录。
2. 优先使用 CorpID 搜索。
3. 如果 CorpID 命中 1 条，继续。
4. 如果 CorpID 命中 0 条，使用企业客户名称搜索。
5. 如果命中多条或名称不完全一致，进入人工处理。
6. 打开企业微信绑定弹窗。
7. 读取企业 ID/密文 ID。

简道云后台的企业微信绑定弹窗字段：

- 读取：企业 ID/密文 ID。
- 读取：企业名称。
- 读取或参考：User_ID，但第一版以 Webhook payload 的 `user_id` 为准。
- 回填：`token`。
- 回填：`EncodingAESKey`。
- 动作：点击“确定”提交绑定。

### 5.3 URL 派生规则

输入：

```text
corp_secret_id = 从简道云绑定弹窗读取的企业 ID/密文 ID
user_id = 从简道云 Webhook payload 读取
```

派生：

```text
应用主页 URL = https://wxwork.jiandaoyun.com/wxwork/{corp_secret_id}/dashboard
回调 URL = https://wxwork.jiandaoyun.com/wxwork/corp/{corp_secret_id}/service
可信域名 / 授权回调域 = wxwork.jiandaoyun.com
```

这些值由 RPA 系统生成，不从页面复制。

### 5.4 企微后台步骤

打开企微后台固定入口后：

1. 在授权企业客户列表中按企业客户名称搜索/定位目标行。
2. 企微后台页面看不到明文 CorpID，因此只能用企业名称定位。
3. 如果命中 0 条，进入 `RECORD_NOT_FOUND`。
4. 如果命中多条或名称不完全一致，进入人工处理。
5. 如果目标行状态为待开发，点击“开始代开发应用”。
6. 进入“确认基础信息”步骤。
7. 进入“配置开发信息”步骤。
8. 填写应用主页 URL、可信域名、回调 URL 等配置。
9. 读取或生成 `token` 和 `EncodingAESKey`。
10. 点击完成。

### 5.5 简道云回填绑定

从企微后台取回：

- `token`
- `EncodingAESKey`

回到简道云企业微信绑定弹窗：

1. 填入 `token`。
2. 填入 `EncodingAESKey`。
3. 点击确定。
4. 记录提交结果截图和步骤日志。

### 5.6 企微审核和上线

简道云绑定提交成功后，企微后台会出现审核状态。

成功标准：

```text
企微后台最终状态显示“已上线”
```

中间状态配置为状态词表，不在代码中写死：

```text
waiting_review:
  - 审核中

ready_to_online:
  - 审核通过
  - 待上线
  - 现场确认后的其他可上线状态

online_success:
  - 已上线

review_failed:
  - 审核失败
  - 被驳回
```

未知状态进入 `waiting_manual_intervention`。

### 5.7 审核等待策略

审核通常几分钟内完成。任务进入 `waiting_wecom_review` 后释放机器人。

建议默认策略：

```text
首次检查：2 分钟后
检查间隔：2 分钟
最大检查次数：10 次
最大等待时间：约 20 分钟
```

到检查时间后，调度器重新把任务派给机器人：

```text
重新打开企微固定入口
-> 定位目标企业/应用
-> 读取状态
-> 审核中：再次挂起
-> 可上线：执行上线
-> 已上线：标记成功
-> 失败/未知：暂停或失败
```

### 5.8 简道云 API 回写

当企微状态为“已上线”后：

1. 调用简道云 API 提交/更新数据。
2. 记录 API 请求和响应摘要。
3. 标记任务成功。

如果企微已上线但简道云 API 回写失败，任务不应重新跑企微绑定和上线流程，而应进入独立状态：

```text
jdy_callback_failed
```

后续只重试简道云 API 回写。

## 6. 任务状态机

### 6.1 主状态

```text
pending
checking_login
running
waiting_login
waiting_manual_selection
waiting_manual_intervention
waiting_wecom_review
ready_to_online
jdy_callback_failed
success
failed
cancelled
```

### 6.2 状态说明

| 状态 | 含义 |
| --- | --- |
| `pending` | 等待执行 |
| `checking_login` | 检查后台登录态 |
| `running` | 正在执行步骤 |
| `waiting_login` | 等待管理员扫码恢复登录态 |
| `waiting_manual_selection` | 系统提取到候选项，等待管理员选择 |
| `waiting_manual_intervention` | 系统无法自动继续，等待管理员远程接管或确认 |
| `waiting_wecom_review` | 企微审核中，任务挂起并定时检查 |
| `ready_to_online` | 审核通过或待上线，可执行上线 |
| `jdy_callback_failed` | 企微已上线，但简道云 API 回写失败 |
| `success` | 企微已上线且简道云回写成功 |
| `failed` | 任务失败 |
| `cancelled` | 管理员取消 |

## 7. 人工处理设计

### 7.1 歧义记录处理

触发场景：

- 简道云搜索命中多条。
- 简道云名称不完全一致。
- 企微授权客户搜索命中多条。
- 企微授权客户名称不完全一致。

处理方式：

```text
优先：Web 页面结构化选择
兜底：截图 + 管理员远程 Windows Server 接管 + 点击继续
```

### 7.2 结构化选择页

Web 页面展示：

- 任务基本信息。
- Webhook 企业名称和 CorpID。
- 搜索关键词。
- 候选项列表。
- 当前页面截图。
- 暂停原因。
- 选择人、选择时间、备注。

管理员选择候选后，Runner 使用该候选定位信息继续执行。

### 7.3 远程接管

当页面结构无法提取候选项时：

1. RPA 页面展示当前截图和暂停原因。
2. 管理员远程登录 Windows Server。
3. 管理员手动处理到可继续状态。
4. 管理员回到 RPA 页面点击继续。
5. Runner 做继续前校验，再恢复执行。

## 8. 流程编排器设计

### 8.1 配置方式

第一版使用表格型流程编排器，类似 Excel 升级版。

页面结构：

```text
顶部：
  - 流程名称
  - 团队
  - 当前版本
  - 草稿/已发布状态
  - 发布 / 复制 / 回滚 / 试运行

中间：
  - 步骤表格

右侧：
  - 步骤配置抽屉
```

步骤表格字段：

- 序号。
- 步骤名称。
- 动作类型。
- 目标系统。
- 输入。
- 输出。
- 重试策略。
- 失败处理。
- 截图策略。
- 是否启用。
- 操作。

### 8.2 步骤配置

步骤配置支持表单和 JSON 双向同步。

配置抽屉 Tab：

1. 基础配置。
2. 定位/动作。
3. 重试/失败处理。
4. JSON 高级配置。

规则：

```text
表单修改 -> 自动更新 JSON
JSON 修改 -> 校验通过后回填表单
JSON 校验失败 -> 不允许保存
```

### 8.3 第一版动作类型

浏览器动作：

- 打开 URL。
- 点击。
- 输入。
- 读取文本/值。
- 等待状态。
- 表格行定位。
- 截图。

数据动作：

- 字段映射。
- URL 派生。
- 变量替换。
- 校验。
- 条件判断。

任务控制动作：

- 等待审核。
- 等待登录。
- 等待人工选择。
- 定时恢复。
- 通知。

API 动作：

- 接收 Webhook。
- 调用简道云 API 回写。
- 发送企微机器人通知。

### 8.4 暂缓到第二版

- 自由拖拽大画布。
- 复杂分支网关。
- 多机器人负载均衡。
- AI 自动生成流程。
- AI 操作型兜底。

## 9. 流程版本策略

支持：

- 草稿。
- 发布。
- 回滚。
- 复制版本。
- 任务绑定执行版本快照。

规则：

```text
新任务只使用当前已发布版本
草稿不会影响正在执行的任务
发布新版本不会影响已创建任务
任务执行时使用自己的版本快照
回滚只是把旧版本重新设为发布版本
复制版本用于基于历史版本创建新草稿
```

任务详情展示：

- 流程名称。
- 执行版本号。
- 版本发布时间。
- 步骤快照。
- 是否为当前最新版本。

## 10. 测试和试运行

### 10.1 单步测试

支持对草稿步骤进行单步测试：

- 选择步骤。
- 选择测试机器人。
- 输入或引用测试上下文。
- 执行单步。
- 返回结果、截图、读取值和错误原因。

### 10.2 草稿完整试运行

当前没有测试环境，只能使用真实环境谨慎试跑。

草稿试运行规则：

- `test_run = true`。
- 使用真实后台。
- 默认在关键动作前暂停确认。
- 管理员点击继续后才执行真实动作。
- 试运行日志和正式任务统计分开。

关键动作包括：

- 简道云绑定弹窗点击确定。
- 企微后台点击完成。
- 企微审核通过后点击上线。
- 简道云 API 提交上线结果。

暂停状态：

```text
waiting_test_confirmation
```

正式任务默认全自动执行，只有异常、歧义、登录失效或风控时才暂停。

## 11. AI 异常诊断

### 11.1 触发时机

- 步骤失败。
- 状态无法识别。
- 页面和预期不一致。
- 多次重试失败。

### 11.2 输入

- 当前步骤配置。
- 当前 URL。
- 页面截图。
- 页面文本/DOM 摘要。
- 最近执行日志。
- 任务上下文。

### 11.3 输出

```json
{
  "category": "LOGIN_REQUIRED",
  "confidence": 0.93,
  "reason": "页面显示扫码登录二维码",
  "recommended_action": "进入 waiting_login，通知管理员扫码",
  "requires_manual": true
}
```

### 11.4 第一版异常分类

```text
LOGIN_REQUIRED
RISK_CONTROL
RECORD_NOT_FOUND
AMBIGUOUS_RECORD
PAGE_STRUCTURE_CHANGED
WECOM_REVIEW_WAITING
WECOM_REVIEW_FAILED
WECOM_STATUS_UNKNOWN
STEP_TIMEOUT
API_CALLBACK_FAILED
UNKNOWN
```

### 11.5 限制

- AI 第一版不执行点击、输入、滚动。
- AI 不直接决定简道云绑定提交。
- AI 不直接决定企微上线。
- AI 只做诊断和建议。

## 12. 通知设计

通知按团队/流程配置。

第一版配置：

```text
team.webhook_url
flow.notification_enabled
flow.notify_on
```

通知事件：

- 成功。
- 失败。
- 等待登录。
- 等待人工选择。
- 等待人工接管。
- 风控暂停。
- 企微审核超时。

通知内容：

- 企业名称。
- CorpID 摘要。
- 流程名称。
- 任务状态。
- 当前阶段。
- 错误分类。
- 任务详情链接。

## 13. 团队和权限

第一版只做轻量团队字段，不做复杂权限控制。

用途：

- 任务筛选。
- 流程归属。
- 通知配置。
- 后续扩展权限。
- 统计不同团队任务量和成功率。

字段：

```text
team_id
team_name
```

第一版管理入口由管理员使用。

## 14. 数据模型草案

### 14.1 teams

```text
id
name
webhook_url
notification_enabled
created_at
updated_at
```

### 14.2 flow_templates

```text
id
team_id
name
description
published_version_id
draft_version_id
created_at
updated_at
```

### 14.3 flow_versions

```text
id
flow_template_id
version_no
status: draft / published / archived
steps_json
created_by
published_at
created_at
updated_at
```

### 14.4 tasks

```text
id
team_id
flow_template_id
flow_version_id
flow_version_snapshot_json
status
enterprise_name
corp_id
source_user_id
idempotency_key
payload_json
current_step_key
next_check_at
check_attempts
assigned_robot_id
created_at
updated_at
finished_at
```

### 14.5 task_steps

```text
id
task_id
step_key
step_name
status
attempt
started_at
finished_at
input_json
output_json
error_type
error_message
screenshot_id
```

### 14.6 task_artifacts

```text
id
task_id
step_id
artifact_type: screenshot / trace / log
path
metadata_json
created_at
```

### 14.7 robots

```text
id
name
status
host
browser_profile_path
last_heartbeat_at
capabilities_json
created_at
updated_at
```

### 14.8 manual_actions

```text
id
task_id
action_type
status
reason
candidates_json
selected_candidate_json
handled_by
handled_at
created_at
updated_at
```

## 15. 实施分期

### Phase 1: 新系统骨架和样板流程

- 新建 server/worker 边界。
- 新建数据库模型。
- 新建 Webhook 接收。
- 新建表格型流程配置页面。
- 新建流程版本管理。
- 新建 Playwright Worker。
- 跑通企业微信上线应用样板流程。
- 支持登录等待、人工选择、审核等待、简道云 API 回写。
- 支持 AI 异常诊断。

### Phase 2: 编排器增强

- 单步测试体验增强。
- 流程 diff。
- 更多动作类型。
- 更完善的候选项提取。
- 状态词表可视化维护。
- 操作日志和截图检索。

### Phase 3: 多机器人和 AI 操作兜底

- 多机器人调度。
- 机器人能力匹配。
- AI 低风险恢复动作。
- Computer Use 操作兜底。
- 复杂流程分支。

## 16. 风险和处理策略

| 风险 | 处理策略 |
| --- | --- |
| 页面结构变化 | Playwright 定位 + 步骤重试 + AI 诊断 + 人工接管 |
| 名称匹配错误 | CorpID 优先搜索；企微侧无法看 CorpID 时保守暂停人工选择 |
| 扫码登录失效 | `waiting_login`，管理员扫码后重新打开固定入口恢复 |
| 审核状态不确定 | 状态词表配置；未知状态人工接管 |
| 审核等待卡队列 | `waiting_wecom_review` 挂起释放机器人，定时检查 |
| 简道云 API 回写失败 | 进入 `jdy_callback_failed`，只重试 API 回写 |
| 草稿试运行误提交 | 关键动作前默认暂停确认 |
| AI 误判 | AI 只诊断不操作，低置信度进入人工处理 |

## 17. 第一版验收标准

- 能通过 Webhook 创建企业微信上线应用任务。
- 能使用表格型流程配置并发布版本。
- 新任务绑定执行版本快照。
- Worker 能使用 Windows 浏览器 profile 操作简道云和企微后台。
- 能读取简道云企业 ID/密文 ID。
- 能按规则生成主页 URL、回调 URL、可信域名。
- 能在企微后台定位目标企业并进入代开发配置。
- 能填写企微配置并读取 `token` 和 `EncodingAESKey`。
- 能回填简道云绑定弹窗并提交。
- 能进入 `waiting_wecom_review` 并释放机器人。
- 能定时恢复检查企微状态。
- 状态为“已上线”后能调用简道云 API 回写。
- 能处理登录失效、记录歧义、未知状态和 API 回写失败。
- AI 异常诊断能输出结构化分类。
- 成功和异常能按配置发送通知。
