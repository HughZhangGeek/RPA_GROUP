# RPA 第二阶段：Windows 元素采集与元素驱动执行

状态：2026-06-24 第二阶段起步版
适用范围：RPA_GROUP Windows Server 执行面、企微客户端元素采集、元素驱动点击/输入/等待
非目标：不修改旧线上 `RPA.py`，不提交 `.local/`、Cookie、token、webhook、二维码、日志、数据库、截图或真实上下文 JSON

## 1. 第二阶段理解

第一里程碑已经证明 `JDY webhook -> CSM_C360 控制面 -> Windows worker -> 只读预检/登录恢复/无人值守真实写入 -> JDY 回写 -> 流程推进` 这条链路可用。第二阶段的目标不是继续扩展截图/坐标脚本，而是把企微客户端类任务升级为：

```text
Windows Server 真实界面元素采集
-> 标记成业务动作元素配置
-> 任务命令引用元素配置
-> UIA 驱动执行 wait/click/input/assert/scroll
-> 必要时才使用高风险坐标兜底
```

采集和调试阶段默认只读，不触发真实业务提交。真实写入仍保留双门禁：Windows 本机 `RPA_WORKER_ALLOW_UNATTENDED_WRITE=true`，并且 CSM dispatch payload 明确 `unattended_write=true` 或 `confirm_write=true`。

## 2. 方案调研结论

推荐组合：

| 场景 | 推荐 | 原因 |
| --- | --- | --- |
| 采集 | `uiautomation` + Microsoft Inspect / Accessibility Insights | `uiautomation` 能直接从鼠标下元素读取 UIA 属性；Inspect/Accessibility Insights 用于人工校验控件的 Name、ControlType、AutomationId 和 Patterns。 |
| 执行 | `uiautomation` 薄封装为本仓库 `UiaAutomationDriver` | Python/Windows 原生路线，依赖轻，支持 Windows Server，适合企微客户端和桌面控件。 |
| 调试 | Microsoft Inspect、Accessibility Insights、`python -m rpa_platform.worker.element_picker` | 官方工具看 UIA 树，仓库 CLI 输出可复用 JSON，方便把“看到的控件”变成“可执行动作”。 |
| Web DOM | Playwright/CDP | 仅当目标是浏览器 DOM 时使用。企微客户端桌面 UI 不优先走 CDP；简道云/企微后台 Web 页仍优先 Playwright/接口链路。 |
| 备选 | pywinauto | 成熟、BSD 许可证、支持 Win32/UIA，但本阶段先用更直接的 `uiautomation` 作为采集和执行主库；如遇控件兼容问题，再对 `pywinauto` 增加第二适配器。 |
| 底层兜底 | pywin32 / COM | 维护活跃、能力强，但 API 太底层，先作为疑难问题兜底，不作为第一层动作 DSL。 |

依赖选择：

- `requirements.txt` 新增 `uiautomation==2.0.29; platform_system == "Windows"`，避免非 Windows 开发机安装 Windows 专用依赖。
- 不把 `pywinauto` 立即加入依赖；等真实企微控件验证发现 `uiautomation` 不稳定时再加第二驱动。

## 3. 元素配置格式

采集输出是一个业务动作配置，建议先放在 Windows 本机 `.local/elements/` 下人工审阅，确认后再提炼成仓库内模板。

```json
{
  "business_action": "wecom_bind.permission.save",
  "target": {
    "type": "uia",
    "window_title": "企业微信",
    "control_type": "Button",
    "name": "保存",
    "automation_id": "saveButton",
    "class_name": "Button",
    "xpath": "",
    "hierarchy_path": ["企业微信", "权限设置", "保存"],
    "bounding_rect_hint": [900, 720, 980, 760]
  },
  "fallback_position": {"x": 940, "y": 740},
  "collected_at": "2026-06-24T10:00:00+08:00",
  "note": "企微权限页面保存按钮"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `business_action` | 业务动作名，用稳定语义命名，例如 `wecom_bind.permission.name`。 |
| `target.type` | 当前为 `uia`。后续可扩展 `dom`、`image`。 |
| `window_title` | 目标窗口标题，缩小搜索范围。 |
| `control_type/name/automation_id/class_name` | UIA 主要定位字段，越稳定越优先。 |
| `xpath/hierarchy_path` | 调试和人工复核用；不同工具的路径语义可能不同，不作为唯一强依赖。 |
| `bounding_rect_hint` | 采集时的矩形提示，用于排查和高风险兜底，不作为主定位。 |
| `fallback_position` | 由矩形中心点生成。只有命令显式标记 `risk_level=high` 才允许使用坐标兜底。 |
| `collected_at/note` | 采集时间和备注。 |

## 4. Windows PowerShell 采集步骤

在 Windows Server 上执行：

```powershell
conda activate RPA_GROUP
cd C:\rpa_work\RPA_GROUP
. C:\rpa_work\RPA_GROUP\.local\rpa-worker-env.ps1
python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force .local\elements\wecom_bind_permission | Out-Null
```

打开企微客户端并进入权限设置页面后，把鼠标悬停到目标控件上，逐个执行：

```powershell
python -m rpa_platform.worker.element_picker --business-action wecom_bind.permission.org_info --note "组织架构信息节点" --output .local\elements\wecom_bind_permission\org_info.json
python -m rpa_platform.worker.element_picker --business-action wecom_bind.permission.name --note "姓名权限复选框" --output .local\elements\wecom_bind_permission\name.json
python -m rpa_platform.worker.element_picker --business-action wecom_bind.permission.department --note "部门名权限复选框" --output .local\elements\wecom_bind_permission\department.json
python -m rpa_platform.worker.element_picker --business-action wecom_bind.permission.save --note "权限设置保存按钮" --output .local\elements\wecom_bind_permission\save.json
```

只读检查 JSON：

```powershell
Get-Content .local\elements\wecom_bind_permission\name.json -Encoding UTF8
```

注意：

- 采集输出先留在 `.local/`，不要提交。
- 如果 `name` 为空、`control_type` 不稳定，先用 Microsoft Inspect 或 Accessibility Insights 复核 UIA 树。
- 如果企微客户端基于 Chromium/Electron 且 UIA 树缺失，可尝试用启动参数 `--force-renderer-accessibility` 让可访问性树更完整；生产执行前需确认不影响企微客户端稳定性。

## 5. 元素驱动动作

当前已支持的动作：

| action | 说明 |
| --- | --- |
| `wait_element` | 等待 UIA 元素出现。 |
| `click_element` | 点击 UIA 元素。 |
| `input_text` | 输入文本，优先走 ValuePattern。 |
| `set_text` | 兼容旧命令，内部等价于 `input_text`。 |
| `assert_checked` | 断言复选框/开关勾选状态。 |
| `scroll_to_element` | 通过 ScrollItemPattern 滚动到目标元素。 |

示例命令：

```json
[
  {
    "step_key": "wait_org_info",
    "step_name": "等待组织架构信息",
    "action": "wait_element",
    "target": {"type": "uia", "window_title": "企业微信", "control_type": "CheckBox", "name": "姓名"},
    "timeout_seconds": 5
  },
  {
    "step_key": "assert_name",
    "step_name": "确认姓名已勾选",
    "action": "assert_checked",
    "target": {"type": "uia", "window_title": "企业微信", "control_type": "CheckBox", "name": "姓名"},
    "expected": true
  },
  {
    "step_key": "save_permission",
    "step_name": "保存权限设置",
    "action": "click_element",
    "target": {"type": "uia", "window_title": "企业微信", "control_type": "Button", "name": "保存"}
  }
]
```

## 6. 相关代码文件/模块

- `rpa_platform/worker/element_picker.py`：鼠标下元素采集、元素配置生成。
- `rpa_platform/worker/uia_driver.py`：`uiautomation` 执行适配器。
- `rpa_platform/worker/client_commands.py`：动作白名单和 UIA target 校验。
- `rpa_platform/worker/wecom_client_runner.py`：元素驱动动作分派。
- `tests/test_platform_element_picker.py`：元素配置和采集 CLI 测试。
- `tests/test_platform_uia_driver.py`：UIA 驱动 fake backend 测试。
- `tests/test_platform_client_commands.py`：动作归一化测试。
- `tests/test_platform_wecom_client_runner.py`：runner 动作分派测试。

## 7. 下一步

1. 在 Windows Server 按第 4 节采集企微权限页面四个元素。
2. 对照 Inspect/Accessibility Insights 复核字段稳定性。
3. 从 `.local/elements/wecom_bind_permission/*.json` 提炼仓库内模板。
4. 用 `UiaAutomationDriver` 在 test mode 下执行 `wait/assert/scroll`，先不点击保存。
5. 确认只读动作稳定后，再把保存按钮点击纳入双门禁写入流程。
