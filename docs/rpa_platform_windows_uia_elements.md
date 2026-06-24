# RPA 第二阶段：Windows 元素采集与元素驱动执行

状态：2026-06-24 第二阶段起步版
适用范围：RPA_GROUP Windows Server 执行面、企微/钉钉客户端元素采集、元素驱动点击/输入/等待、必要时坐标兜底
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
| 执行 | `uiautomation` 薄封装为本仓库 `UiaAutomationDriver` | Python/Windows 原生路线，依赖轻，支持 Windows Server，适合企微/钉钉客户端和桌面控件。 |
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

打开企微客户端并进入权限设置页面后，推荐使用快捷键采集。每条命令启动后会等待热键；把鼠标移动到目标控件上，按 `Ctrl+Alt+C`，采集完成后命令自动退出。

```powershell
python -m rpa_platform.worker.element_picker --hotkey ctrl+alt+c --business-action wecom_bind.permission.org_info --note "组织架构信息节点" --output .local\elements\wecom_bind_permission\org_info.json
python -m rpa_platform.worker.element_picker --hotkey ctrl+alt+c --business-action wecom_bind.permission.name --note "姓名权限复选框" --output .local\elements\wecom_bind_permission\name.json
python -m rpa_platform.worker.element_picker --hotkey ctrl+alt+c --business-action wecom_bind.permission.department --note "部门名权限复选框" --output .local\elements\wecom_bind_permission\department.json
python -m rpa_platform.worker.element_picker --hotkey ctrl+alt+c --business-action wecom_bind.permission.save --note "权限设置保存按钮" --output .local\elements\wecom_bind_permission\save.json
```

只读检查 JSON：

```powershell
Get-Content .local\elements\wecom_bind_permission\name.json -Encoding UTF8
```

注意：

- 采集输出先留在 `.local/`，不要提交。
- 如果 `name` 为空、`control_type` 不稳定，先用 Microsoft Inspect 或 Accessibility Insights 复核 UIA 树。
- 如果企微客户端基于 Chromium/Electron 且 UIA 树缺失，可尝试用启动参数 `--force-renderer-accessibility` 让可访问性树更完整；生产执行前需确认不影响企微客户端稳定性。
- 如果快捷键与系统或远程桌面冲突，可以换成 `--hotkey ctrl+shift+f8` 之类不常用的组合。

不用快捷键时，也可以保留原方式：鼠标悬停到目标控件上后直接运行不带 `--hotkey` 的命令，工具会立即采集当前鼠标位置下的元素。

### 钉钉交接群：设置按钮采集

当前钉钉交接群流程先以 `.local/elements/dingtalk_group_handoff/` 保存现场采集结果，不提交仓库。前置页面状态：

- 已进入目标群：`帆软测试&简道云沟通群`。
- 搜索弹层已验证可通过“群组”和“普通群”进入群。
- 采集第一步目标是群页面右上角或侧边的“设置”按钮。
- 现场已确认：设置按钮固定坐标为 `(1874,66)`；“添加成员”按钮旧坐标为 `(1613,243)`。当前 smoke 默认仍可用坐标调试，批量脚本已改为优先识别 `add_member.png`。
- `add_member.png` 识别区域为 `(1441,50),(1896,51),(1441,626),(1896,626)`，代码中换算为 `pyautogui region=(1441,50,455,576)`。

Windows PowerShell 命令：

```powershell
conda activate RPA_GROUP
cd C:\rpa_work\RPA_GROUP
. C:\rpa_work\RPA_GROUP\.local\rpa-worker-env.ps1
New-Item -ItemType Directory -Force .local\elements\dingtalk_group_handoff | Out-Null

python -m rpa_platform.worker.element_picker --hotkey ctrl+shift+c --business-action dingtalk_group_handoff.group_settings_button --note "钉钉交接群详情页设置按钮" --output .local\elements\dingtalk_group_handoff\group_settings_button.json
python -m json.tool .local\elements\dingtalk_group_handoff\group_settings_button.json
```

如果继续采集“添加成员”按钮，命令为：

```powershell
python -m rpa_platform.worker.element_picker --hotkey ctrl+shift+c --business-action dingtalk_group_handoff.add_member_button --note "add member" --output .local\elements\dingtalk_group_handoff\add_member_button.json
python -m json.tool .local\elements\dingtalk_group_handoff\add_member_button.json
```

判断采集质量：

- 如果 `target.name`、`target.control_type`、`target.automation_id` 或 `target.class_name` 能明确指向设置按钮，优先用 UIA 点击。
- 如果采集到 `Chrome_RenderWidgetHostHWND`、`PaneControl` 或覆盖大范围 `bounding_rect_hint` 的面板，说明 UIA 没拿到真实按钮；保留 JSON 作为证据，再补一个坐标兜底命令。
- 坐标兜底执行使用 `UiaAutomationDriver.click_position()`，底层调用 Windows `user32.SetCursorPos` 和 `mouse_event`，比 `pyautogui.click` 更适合当前 RDP 场景。

坐标兜底命令形状：

```json
{
  "step_key": "open_dingtalk_group_settings_by_position",
  "step_name": "点击钉钉交接群设置按钮坐标兜底",
  "action": "fallback_position_click",
  "target": {"type": "position", "x": 0, "y": 0},
  "risk_level": "high"
}
```

把 `x/y` 替换为设置按钮中心点坐标。若只拿到了元素 JSON，可先参考 `fallback_position`；若 UIA 是大面板，必须人工确认按钮中心点后再填写。

完整本地 smoke 链路：

```powershell
python -m rpa_platform.worker.dingtalk_group_handoff --pause-before-start 3
```

默认链路会依次执行：

```text
点击 group_search_input.json
-> 剪贴板粘贴群名“帆软测试&简道云沟通群”
-> 坐标点击 select_search_type_group.json 的 fallback_position
-> 在 region=(386,90,880,348) 中以 confidence=0.75 识别 normal_group.png 并点击中心
-> 点击 group_settings_button.json
-> 点击 add_member_button.json
```

如果某个按钮 JSON 采到的是大面板，脚本会自动跳过这类大面板 UIA 并使用 JSON 里的 `fallback_position`。如果 `fallback_position` 也是大面板中心点，不是真实按钮中心点，用命令行覆盖：

```powershell
python -m rpa_platform.worker.dingtalk_group_handoff --pause-before-start 3 --settings-click-mode position --settings-position 1874,66 --add-member-click-mode position --add-member-position 1613,243
```

如果只想先跑到设置页，不点击“添加成员”：

```powershell
python -m rpa_platform.worker.dingtalk_group_handoff --pause-before-start 3 --stop-before-add-member
```

如果搜索框 UIA 点击在 RDP 里没有实际聚焦，优先用钉钉快捷键 `ctrl+shift+f` 呼出搜索框：

```powershell
python -m rpa_platform.worker.dingtalk_group_handoff --pause-before-start 5 --step-delay 2 --search-open-mode shortcut --stop-before-add-member
```

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
| `fallback_position_click` | 高风险坐标兜底，必须显式设置 `risk_level=high`。 |

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
  },
  {
    "step_key": "open_dingtalk_group_settings_by_position",
    "step_name": "点击钉钉交接群设置按钮坐标兜底",
    "action": "fallback_position_click",
    "target": {"type": "position", "x": 1200, "y": 80},
    "risk_level": "high"
  }
]
```

## 6. 相关代码文件/模块

- `rpa_platform/worker/element_picker.py`：鼠标下元素采集、元素配置生成。
- `rpa_platform/worker/uia_driver.py`：`uiautomation` 执行适配器，包含 Windows `user32` 坐标点击兜底。
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
6. 钉钉交接群继续采集 `group_settings_button.json`；如果 UIA 只拿到大面板，改用高风险坐标兜底命令打开设置页，再采集设置页内后续元素。

## 8. 钉钉交接群批量执行

状态：2026-06-24 可本地小批量试跑

批量脚本入口：

- `rpa_platform/worker/dingtalk_group_handoff_batch.py`
- `scripts/dev/run_dingtalk_group_handoff_batch.py`

脚本读取 Excel 的 A 列群名称，并把每行结果写回 B 列。即使 Excel 因格式残留导致 `max_row` 很大，脚本也只处理 A 列非空的行。每处理一行默认立即保存一次 workbook，避免中断后丢进度。

Windows 侧更新代码：

```powershell
conda activate RPA_GROUP
cd C:\rpa_work\RPA_GROUP
. C:\rpa_work\RPA_GROUP\.local\rpa-worker-env.ps1
git pull origin feat/windows-uia-elements
```

先做只读预览：

```powershell
python scripts\dev\run_dingtalk_group_handoff_batch.py --workbook C:\rpa_work\RPA_GROUP\.local\elements\dingtalk_group_handoff\需要转交的群.xlsx --dry-run --limit 3
```

小批量真实执行 3 行：

```powershell
python scripts\dev\run_dingtalk_group_handoff_batch.py --workbook C:\rpa_work\RPA_GROUP\.local\elements\dingtalk_group_handoff\需要转交的群.xlsx --limit 3 --skip-completed --pause-before-start 5 --step-delay 2
```

确认稳定后正式运行：

```powershell
python scripts\dev\run_dingtalk_group_handoff_batch.py --workbook C:\rpa_work\RPA_GROUP\.local\elements\dingtalk_group_handoff\需要转交的群.xlsx --skip-completed
```

可用参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--workbook` | `.local\elements\dingtalk_group_handoff\需要转交的群.xlsx` | Excel 路径，可传用户放置的任意同结构文件。 |
| `--sheet` | `Sheet1` | 工作表名。 |
| `--member-name` | `季钰杰` | 要添加的成员名。 |
| `--start-row` | `2` | 从第几行开始处理。 |
| `--limit` | 空 | 限制本次处理的非空群名数量，适合先小批量测试。 |
| `--dry-run` | 关闭 | 只打印将处理的群，不点击、不写 B 列。 |
| `--skip-completed` | 关闭 | B 列已有状态时跳过。 |
| `--save-every` | `1` | 每处理多少行保存一次，默认每行保存。 |

当前写回状态：

- `添加成功`
- `成员已在群内`
- `群不存在`
- `添加成员入口失败`
- `确认按钮未点击`
- `钉钉窗口未捕获`
- `异常：<简短原因>`

注意：

- 执行前保持钉钉窗口可见，并把 Mac 本机鼠标移出 RDP 窗口，避免干扰 RDP 内坐标点击。真实执行会先捕获并激活标题包含 `钉钉` 或 `DingTalk` 的窗口，成功时终端会打印 `Captured DingTalk window: ...`；捕获失败会打印 `DingTalk window capture failed: ...` 并退出，不写 Excel。
- 批量脚本默认使用 `ctrl+shift+f` 呼出搜索框，避免钉钉 UIA 点击返回成功但实际没有聚焦。
- 批量脚本进入设置页后用 `.local\elements\dingtalk_group_handoff\add_member.png` 在 `region=(1441,50,455,576)` 内识别“添加成员”入口；识别失败会写 `添加成员入口失败`，保存当前行，然后继续下一行。
- 群不存在、添加成员入口失败、成员已在群内等提前收口分支会先重新捕获钉钉窗口，再发送一次 `Esc` 关闭当前搜索/添加成员弹层，避免第二次 `Esc` 落到主窗口导致钉钉退出。
- 搜索群名和成员名使用剪贴板粘贴；PowerShell 中文参数不稳定时，优先使用默认 `--member-name`。
- 本地资产仍放在 `.local\elements\dingtalk_group_handoff\`，包括 Excel、元素 JSON 和截图模板，不提交仓库。
