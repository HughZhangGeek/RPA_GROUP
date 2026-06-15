# RPA 平台化重构交接：简道云企微绑定 + browser-use 路线

## 状态

- 日期：2026-06-15
- 仓库：`/Users/hugh/jdycsm_project/RPA_GROUP`
- 当前分支：`feature/rpa-platform-foundation`
- 当前阶段：新 RPA 平台化重构，Task 1-6 已完成，正在做阶段收口提交。
- 旧线上入口 `RPA.py` 是稳定系统，本轮未修改、未部署、未重启。
- 阶段收口前 `git status -sb` 显示：

```text
## feature/rpa-platform-foundation
 M docs/rpa_platform_refactor_design.md
?? docs/jdy_wework_bind_api_research.md
?? docs/superpowers/
?? rpa_platform/
?? tests/
```

## 重要边界

- 不要修改旧 `RPA.py`。
- 不要部署，不要重启服务。
- 不要提交 `.env`、`config.py`、日志、数据库、截图、zip 包。
- commit message、PR 标题、PR 描述默认中文。
- 当前新系统文件主要在 `rpa_platform/`，测试在 `tests/`，文档在 `docs/`。
- 企微后台页面自动化已确定走本地/自托管 `browser-use` 路线，不使用 Browser Use Cloud。
- `browser-use` 真实执行器后续可以运行在独立 Python 3.11+ worker 环境；主平台只依赖 adapter contract。

## 已完成内容

### Task 1: Jiandaoyun Admin Client

新增：

- `rpa_platform/integrations/__init__.py`
- `rpa_platform/integrations/jdy_admin_client.py`
- `tests/test_platform_jdy_admin_client.py`

能力：

- 封装简道云后台接口：
  - `POST /api/fx_sa/wxwork/get_corp_deploy_list`
  - `POST /api/fx_sa/wxwork/get_owner`
  - `POST /api/fx_sa/wxwork/install_corp_deploy`
- 支持企业部署列表搜索、唯一企业解析、owner 校验、绑定提交 payload 组装。
- 使用注入式 `JdyAdminTransport`，测试里用 fake transport，不写死 cookie。

### Task 2: Runtime Context Storage and Redaction

新增/修改：

- `rpa_platform/domain/redaction.py`
- `rpa_platform/storage/sqlite_store.py`
- `tests/test_platform_task_context.py`

能力：

- `tasks` 增加 `runtime_context_json TEXT NOT NULL DEFAULT '{}'`。
- `init_schema()` 增加本地轻量迁移，兼容已有 SQLite 库。
- 新增：
  - `get_task_context(task_id)`
  - `merge_task_context(task_id, patch)`
  - `set_task_current_step(task_id, step_key)`
- `get_task_detail()` 返回脱敏后的 `runtime_context`。
- `token`、`encoding_aes_key`、cookie 类字段统一隐藏；密文企业 ID / app_id 类字段保留首尾。

### Browser-use 路线调整 + Task 3/4 契约

新增/修改：

- `docs/superpowers/plans/2026-06-08-jdy-wework-bind-hybrid-flow.md`
- `rpa_platform/domain/flow_steps.py`
- `rpa_platform/worker/wecom_rpa.py`
- `tests/test_platform_flow_steps.py`
- `tests/test_platform_wecom_rpa.py`

已调整：

- 计划文档顶部明确企微页面自动化使用本地/自托管 `browser-use`。
- Browser Use Cloud 明确不作为第一版方案。
- `flow_steps.ALLOWED_ACTIONS` 增加：
  - `browser_use_task`
  - `jdy_resolve_corp`
  - `derive_wecom_urls`
  - `wecom_configure_app`
  - `jdy_check_owner`
  - `jdy_install_bind`
  - `wecom_submit_review`
  - `wecom_wait_review`
  - `wecom_submit_online`
- `validate_steps(..., enforce_action_allowlist=True)` 可启用动作白名单，默认仍为宽松模式。

`rpa_platform/worker/wecom_rpa.py` 当前提供：

- `WecomRpa` 协议
- `WecomReviewStatus`
- `BrowserUseTaskRequest`
- `BrowserUseRunner`
- `BrowserUseWecomRpa`
- `FakeBrowserUseRunner`
- `FakeWecomRpa`

当前仍未引入真实 `browser-use` 依赖，也没有拉起浏览器；执行层通过 fake/browser-use agent contract 验证。

关键安全边界：

- `BrowserUseTaskRequest` 禁止 `use_cloud=True`。
- 企微自动化限制 `allowed_domains == ["open.work.weixin.qq.com"]`。
- 必须提供本地 `browser_profile`。
- prompt 中要求登录/扫码/验证码/企业匹配不唯一时停止并返回人工处理。

### BrowserUseRunner 最小实现

新增：

- `rpa_platform/worker/browser_use_runner.py`
- `tests/test_platform_browser_use_runner.py`

能力：

- `LocalBrowserUseRunner` 通过注入式 `agent_factory` 调用本地/自托管 browser-use agent。
- 将 `BrowserUseTaskRequest` 转换为 `BrowserUseAgentTask`，保留：
  - `allowed_domains`
  - `browser_profile`
  - `use_cloud=False`
  - `task_template` metadata
- 要求 agent 只返回 JSON object，并将 dict / JSON 字符串 / browser-use history `final_result()` 归一化为结构化 dict。
- `manual_required`、`needs_login` 等结构化结果原样交给上层 runner。
- agent 异常或非结构化输出会转换为 `{status: "error", error_type, error_detail}`。

### Task 5: Hybrid Runner Step Engine

新增：

- `rpa_platform/worker/hybrid_runner.py`
- `tests/test_platform_hybrid_runner.py`

能力：

- 串联默认企微上线混合步骤：
  - `jdy_resolve_corp`
  - `derive_wecom_urls`
  - `wecom_configure_app`
  - `jdy_check_owner`
  - `jdy_install_bind`
  - `wecom_submit_review`
- 写入 `runtime_context`：
  - `jdy.corp_secret_id`
  - `jdy.install_owner_id`
  - `wecom.homeurl`
  - `wecom.callbackurl`
  - `wecom.token`
  - `wecom.encoding_aes_key`
- `WAITING_WECOM_REVIEW` 任务只检查审核状态，继续审核中则设置下一次检查时间并释放机器人。
- `READY_TO_ONLINE` 任务只提交上线，成功后标记 `success` 并释放机器人。
- browser-use 返回 `needs_login` 时进入 `waiting_login` 并创建 manual action。
- browser-use 返回 `manual_required` 时进入 `waiting_manual_intervention` 并创建 manual action。

实现注意：

- `rpa_platform/storage/sqlite_store.py` 的 `_now()` 已改为微秒级，避免同一秒写入多条 task step 时排序不稳定。

### Task 6: Default Flow Fixture and Docs

新增/修改：

- `rpa_platform/domain/default_flows.py`
- `tests/test_platform_flow_steps.py`
- `docs/rpa_platform_refactor_design.md`
- `docs/jdy_wework_bind_api_research.md`

能力：

- `WECOM_APP_LAUNCH_FLOW_STEPS` 作为默认企微上线混合流程骨架。
- 默认流程可通过 `validate_steps(..., enforce_action_allowlist=True)`。
- 设计文档已更新第一版执行边界：
  - 简道云绑定页优先内部接口。
  - 企微开发者后台走本地/自托管 `browser-use` 页面自动化。
  - 企微提交接口仅用于排障理解，不作为第一版自动执行入口。
- 研究文档已补默认 action 名称，便于实现对齐。

## 验证记录

已执行：

```bash
conda run -n RPA_GROUP python -m unittest tests.test_platform_jdy_admin_client -v
conda run -n RPA_GROUP python -m unittest tests.test_platform_task_context -v
conda run -n RPA_GROUP python -m unittest tests.test_platform_flow_steps tests.test_platform_wecom_rpa -v
conda run -n RPA_GROUP python -m unittest tests.test_platform_browser_use_runner -v
conda run -n RPA_GROUP python -m unittest tests.test_platform_hybrid_runner -v
conda run -n RPA_GROUP python -m unittest discover -s tests -v
```

最新全量结果：

- `Ran 63 tests`
- `OK`
- 仍有既有 `_distutils_hack` conda 警告，但退出码为 0。

## 下一步建议

建议新会话从这里开始：

1. 先跑：

```bash
git status -sb
conda run -n RPA_GROUP python -m unittest discover -s tests -v
```

2. 阅读：

```text
docs/jdy_wework_bind_api_research.md
docs/superpowers/plans/2026-06-08-jdy-wework-bind-hybrid-flow.md
rpa_platform/domain/default_flows.py
rpa_platform/worker/browser_use_runner.py
rpa_platform/worker/hybrid_runner.py
tests/test_platform_hybrid_runner.py
```

3. 下一项实现建议：

- 将 `TaskScheduler` 和 `HybridFlowRunner` 接起来，让 worker claim 到任务后可以调用 hybrid runner，而不是只跑 `FakeRunner`。
- 仍使用 fake `JdyAdminClient` transport / fake browser-use runner 做单测，不跑真实企微副作用流程。
- 暂时不要直接上真实浏览器登录企微，除非用户明确要求做人工确认的 live spike。

## 新会话交接词

```text
接手 /Users/hugh/jdycsm_project/RPA_GROUP，当前分支 feature/rpa-platform-foundation。

重要边界：
- 旧 RPA.py 是线上稳定系统，不要动，不要部署，不要重启。
- 新系统在 rpa_platform/，测试在 tests/，文档在 docs/，目前整体仍是未跟踪文件。
- commit message / PR 标题 / PR 描述默认中文。
- 不要提交 .env、config.py、日志、数据库、截图、zip 包。
- 当前阶段仍是新 RPA 平台化重构，不要改旧线上入口。

当前已完成：
1. Task 1 简道云后台接口客户端：
   - rpa_platform/integrations/jdy_admin_client.py
   - tests/test_platform_jdy_admin_client.py
   - 支持 get_corp_deploy_list / get_owner / install_corp_deploy。
   - 使用注入式 transport，不写死 cookie。

2. Task 2 运行期上下文与脱敏：
   - rpa_platform/domain/redaction.py
   - rpa_platform/storage/sqlite_store.py
   - tests/test_platform_task_context.py
   - tasks 增加 runtime_context_json。
   - 新增 get_task_context / merge_task_context / set_task_current_step。
   - get_task_detail 返回脱敏 runtime_context。

3. 已确定浏览器自动化动作走本地/自托管 browser-use，不用 Browser Use Cloud：
   - docs/superpowers/plans/2026-06-08-jdy-wework-bind-hybrid-flow.md 已更新顶部方向。
   - rpa_platform/domain/flow_steps.py 增加 action allowlist 和 browser_use_task。
   - rpa_platform/worker/wecom_rpa.py 增加 BrowserUseTaskRequest / BrowserUseRunner / BrowserUseWecomRpa / FakeBrowserUseRunner / FakeWecomRpa。
   - tests/test_platform_flow_steps.py 和 tests/test_platform_wecom_rpa.py 已覆盖契约。
   - 当前没有引入真实 browser-use，也没有拉起浏览器。

4. BrowserUseRunner 最小实现：
   - rpa_platform/worker/browser_use_runner.py
   - tests/test_platform_browser_use_runner.py
   - 使用 fake browser-use agent 验证 request 转换、结构化输出、manual_required / needs_login / 异常透传。

5. HybridFlowRunner 混合执行器：
   - rpa_platform/worker/hybrid_runner.py
   - tests/test_platform_hybrid_runner.py
   - 串联简道云 API、runtime_context、browser-use WeCom adapter 和 waiting_wecom_review / ready_to_online 状态。

6. 默认流程和文档：
   - rpa_platform/domain/default_flows.py
   - tests/test_platform_flow_steps.py
   - docs/rpa_platform_refactor_design.md
   - docs/jdy_wework_bind_api_research.md
   - WECOM_APP_LAUNCH_FLOW_STEPS 已可通过 action allowlist 校验。

验证：
- 最新全量命令：
  conda run -n RPA_GROUP python -m unittest discover -s tests -v
- 最新结果：63 tests OK。
- conda run 会打印既有 _distutils_hack 警告，但退出码 0。

建议下一步：
- 先 git status -sb，并跑全量 unittest。
- 阅读 docs/jdy_wework_bind_api_research.md、计划文档、default_flows、hybrid_runner。
- 下一步优先接 TaskScheduler -> HybridFlowRunner 的运行入口。
- 继续使用 fake client / fake browser-use runner 做单测，不要直接跑真实企微副作用流程。
```
