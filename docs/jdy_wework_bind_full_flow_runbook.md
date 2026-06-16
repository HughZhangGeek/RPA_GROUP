# 简道云企微绑定完整接口链路 Runbook

状态：2026-06-16 单条真实链路已完成上线验证
适用范围：简道云后台企业微信绑定、企业微信代开发应用配置、权限、试用、授权登录、上线提交
非目标：不改旧 `RPA.py`，不记录 Cookie、Token、EncodingAESKey、kitsecret 等敏感明文，不覆盖线上稳定 RPA 流程

## 1. 结论

本链路可以接口化，不需要长期依赖页面点击。短期自动化可使用固定浏览器 Profile 保存登录态，接口请求复用该 Profile 的 Cookie；长期可把简道云侧替换为服务端凭证，企微侧继续使用专用 Profile。

完整成功链路：

```text
简道云查企业
-> 企微查企业应用
-> 生成 Token / EncodingAESKey
-> 简道云 install_corp_deploy 先写入密钥
-> 企微保存开发信息并通过回调校验
-> 企微设置权限
-> 企微设置试用规则：60 天 + 15 天
-> 企微设置授权登录回调域
-> 企微创建上线单 order/add
-> 等待约 5 分钟
-> 企微提交上线 order/set
```

关键顺序是：先在简道云侧写入同一组 `token` / `encoding_aes_key`，再保存企微开发信息。企微点击完成时会校验回调，简道云侧必须已经认识这组密钥。

## 2. 输入参数

任务输入应至少包含：

```json
{
  "enterprise_name": "企业名称",
  "plain_corp_id": "明文 CorpID",
  "requested_user_id": "简道云 User_ID",
  "suite_id": 1,
  "suite_scenario": "main",
  "wecom_suiteid": 1009479,
  "suite_name": "简道云"
}
```

运行时派生字段：

```text
jdy.corp_secret_id     简道云后台返回的密文企业 ID
jdy.original_tenant_id 绑定前已有 tenant_id，可能为空或与 requested_user_id 不同
wecom.app_id           企微授权企业应用 ID
wecom.aes_app_id       企业微信授权登录 sdk_auth.aes_app_id
wecom.homeurl          https://wxwork.jiandaoyun.com/wxwork/{corp_secret_id}/dashboard
wecom.callbackurl      https://wxwork.jiandaoyun.com/wxwork/corp/{corp_secret_id}/service
wecom.redirect_domain  wxwork.jiandaoyun.com
wecom.token            本次生成或读取的 Token，禁止普通日志明文输出
wecom.encoding_aes_key 本次生成或读取的 EncodingAESKey，禁止普通日志明文输出
```

## 3. 登录态策略

第一版自动化使用 Cookie 方案：

```text
Windows 机器固定浏览器 Profile
-> 人工扫码登录简道云后台和企微开发者后台
-> Worker 使用同一 Profile 发请求
-> 每次任务前做登录态健康检查
-> 失效时进入 waiting_login / manual_required
```

安全要求：

- 不主动从 Chrome 密码库或系统目录读取 Cookie。
- 不把 Cookie、sid、vst、monitor、Token、EncodingAESKey、kitsecret 写入日志、数据库详情或文档。
- 调试用 cURL 只能放 `.local/`，不得提交。
- 日志只保存脱敏摘要，例如 `corp_secret_id` 保留首尾，密钥统一为 `***`。

## 4. 简道云侧接口

### 4.1 查找企业部署行

```http
POST https://dc.jdydevelop.com/api/fx_sa/wxwork/get_corp_deploy_list
```

请求体：

```json
{
  "filter": "明文 CorpID 或企业名称",
  "skip": 0,
  "limit": 10
}
```

处理规则：

- 优先用明文 CorpID 搜索。
- 0 命中时再用企业名称搜索。
- 必须唯一命中，且 `name` 与目标企业名称一致。
- 记录 `corp_id/name/tenant_id/suite_id/suite_scenario/suite_name/integrate_suite_name`。
- 若 `tenant_id` 与本次 `requested_user_id` 不同，记录 `original_tenant_id`，并按业务配置允许换绑后继续。
- 企业完成绑定后，`get_corp_deploy_list` 可能用明文 CorpID、企业简称、企业全称都查不到。这不是登录态失效的充分证据，应继续用 `get_owner` 判断是否进入已绑定恢复态。

### 4.2 校验 User_ID

```http
POST https://dc.jdydevelop.com/api/fx_sa/wxwork/get_owner
```

请求体：

```json
{
  "user_id": "requested_user_id",
  "suite_id": 1,
  "suite_scenario": "main"
}
```

通过条件：

```text
can_bind_corp_secret = true
owner / corp 与目标业务预期一致
```

绑定完成后再次调用该接口时，可能变为：

```text
can_bind_corp_secret = false
can_update_corp_secret = true
```

这是已绑定后的正常信号。

已绑定恢复态处理规则：

```text
owner.corp_id              作为 jdy.corp_secret_id 恢复
corp.name                  作为简道云侧企业名称恢复，必须匹配企业全称或企业简称
corp.token                 若存在，复用为 wecom.token
corp.encoding_aes_key      若存在，复用为 wecom.encoding_aes_key
owner_state                记录为 can_update_corp_secret
```

恢复态如果 `corp.token` 和 `corp.encoding_aes_key` 已存在，不要重新调用 `install_corp_deploy`，也不要重新生成密钥；应复用简道云已保存的密钥继续补企微侧。只有恢复态缺少既有密钥时，才按人工确认后的写入流程重新安装绑定。

### 4.3 提交绑定

```http
POST https://dc.jdydevelop.com/api/fx_sa/wxwork/install_corp_deploy
```

请求体：

```json
{
  "corp_id": "jdy.corp_secret_id",
  "corp_name": "enterprise_name",
  "tenant_id": "requested_user_id",
  "token": "wecom.token",
  "encoding_aes_key": "wecom.encoding_aes_key",
  "user_id": "requested_user_id",
  "suite_id": 1,
  "suite_scenario": "main"
}
```

成功标准：

```json
{
  "tenant_id": "requested_user_id",
  "owner_id": "requested_user_id"
}
```

注意：该接口必须在企微保存开发信息前调用，否则企微回调校验可能失败。

## 5. 企微侧接口

企微基础请求上下文：

```text
origin: https://open.work.weixin.qq.com
referer: https://open.work.weixin.qq.com/wwopen/developers/tools
content-type: application/json
```

Cookie 来自企微开发者后台登录态，不记录明文。

真实页面 route 口径：

```text
模板列表：#/sass/customApp/tpl/list
模板详情：#/sass/customApp/tpl/info?id={suiteid}
开始代开发：#/sass/customApp/app/create?suiteid={suiteid}&appid={app_id}&corpName={企业名称}
应用详情：#/sass/customApp/app/detail?suiteid={suiteid}&appid={app_id}
授权登录：#/sass/customApp/app/detail/sso?suiteid={suiteid}&appid={app_id}
上线管理：#/sass/customApp/deploy/list
上线详情：#/sass/customApp/deploy/detail?auditorderid={auditorderid}
```

企微 POST 接口需要带真实页面公共 query：

```text
lang=zh_CN
ajax=1
f=json
random=0
```

缺少这些 query 时，部分真实接口可能返回“数据不存在”等页面态错误。

### 5.1 查授权企业应用

```http
GET https://open.work.weixin.qq.com/wwopen/developer/customApp/tpl/app/list
```

查询参数：

```text
lang=zh_CN
ajax=1
f=json
suiteid=1009479
scene=1
corp_name_keyword={enterprise_name}
offset=0
limit=10
random={随机数}
```

请求头：

```text
x-wecom-developer-page: /sass/customApp/tpl/info
x-wecom-developer-perm: 50
```

通过条件：

- `total = 1`
- `corpapp[0].authcorp_name = enterprise_name`
- 应用名为目标模板，例如“简道云”
- 记录 `app_id`、`customized_app_status`、`sdk_auth.aes_app_id`
- 真实响应可能是 `data.corpapp`，也可能是 `data.corpapp_list.corpapp`，两种结构都要兼容。

待开发状态下常见值：

```text
customized_app_status = 0
homeurl / callbackurl / token / aeskey 为空
```

### 5.2 保存代开发应用基础信息

```http
POST https://open.work.weixin.qq.com/wwopen/developer/customApp/tpl/corpApp
```

请求头：

```text
x-wecom-developer-page: /sass/customApp/app/create
x-wecom-developer-perm: 50
```

请求体骨架：

```json
{
  "suiteid": "1009479",
  "corpapp": {
    "app_id": "wecom.app_id",
    "suiteid": 1009479,
    "page_type": "CREATE",
    "name": "简道云",
    "name_pinyin": "jiandaoyun",
    "logo": "从企微模板/应用记录继承",
    "description": "从企微模板/应用记录继承",
    "homeurl": "wecom.homeurl",
    "redirect_domain": "wxwork.jiandaoyun.com",
    "domain_belong_to": 0,
    "jssdkdomain_list": {"domains": []},
    "white_ip_list": {"ip": []},
    "callbackurl": "wecom.callbackurl",
    "token": "wecom.token",
    "aeskey": "wecom.encoding_aes_key",
    "enter_homeurl_in_wx": true,
    "is_homeurl_miniprogram": false,
    "miniprogram_enter_path": "",
    "miniprogramInfo": {}
  }
}
```

实现规则：

- 不硬编码 `kitid/kitsecret/ww_corpid/createtime/updatetime/suite_type/publish_status` 等模板元数据。
- 先从企微列表或详情接口取得当前应用/模板完整记录，再覆盖本次企业相关字段。
- `aeskey` 与简道云 `encoding_aes_key` 必须完全一致。

成功标准：

```text
response.data.corpapp.homeurl = wecom.homeurl
response.data.corpapp.callbackurl = wecom.callbackurl
response.data.corpapp.redirect_domain = wxwork.jiandaoyun.com
response.data.corpapp.sdk_auth.aes_app_id 存在
```

响应兼容与确认规则：

- 保存接口可能返回 `data.corpapp`，也可能只返回空对象或省略 `corpapp`。
- 接口响应缺少 `corpapp` 时，不要直接重复提交；先重新读取应用列表或详情，确认 `homeurl/callbackurl/redirect_domain/token/aeskey` 是否已经写入。
- 如果重新读取已确认字段存在，视为保存成功并继续后续权限、试用、授权登录、上线步骤。
- 如果接口返回“数据不存在”且重新读取仍未写入，进入受控页面 fallback。

受控页面 fallback：

```text
1. 打开开始代开发 route：
   https://open.work.weixin.qq.com/wwopen/developers/tools#/sass/customApp/app/create?suiteid={suiteid}&appid={app_id}&corpName={企业名称}
2. 从当前任务 context 填入 homeurl、callbackurl、token、aeskey、redirect_domain。
3. 点击页面保存，让企微页面完成回调校验。
4. 保存后立即回到只读预检，确认字段已经存在。
5. 只读确认成功后，脚本从权限设置继续，不重复生成 token/aes，也不重复写 JDY。
```

fallback 边界：

- 只用于企微开发者后台网页 `corpApp` 基础信息保存失败恢复。
- 不属于企业微信客户端 RPA，不处理外部群创建、群发消息、弹窗或风控。
- 不在 runbook、日志、截图、PR 描述中暴露 token/aes 明文。

### 5.3 设置权限

读取接口：

```http
POST https://open.work.weixin.qq.com/wwopen/api/customApp/privilege/getCustomizedAppPrivilege
```

写入接口：

```http
POST https://open.work.weixin.qq.com/wwopen/api/customApp/privilege/setCustomizedAppPrivilege
```

请求头：

```text
x-wecom-developer-page: /sass/customApp/app/detail
x-wecom-developer-perm: 50,51
```

写入请求体结构：

```json
{
  "thirdapp_id": ["wecom.app_id"],
  "suiteid": "1009479",
  "privilege_list": ["从读取接口返回的完整权限树修改 b_check 后提交"]
}
```

本次真实选择的权限：

```text
组织架构信息：开启
成员基本信息：姓名、部门名
其它权限：保持关闭
```

对应样本权限值：

```text
组织架构信息：310000, 310001, 310002, 310100
成员基本信息：10006, 10010
```

实现规则：

- 必须先读完整权限树，再只修改目标节点 `b_check`。
- 保留 `thirdapp_id/app_name/app_logo/servicecorp_full_name/plg_auth_status` 等原字段。
- 权限变更会触发企业客户侧授权变更确认，这是预期行为。

### 5.4 设置试用规则

读取接口：

```http
POST https://open.work.weixin.qq.com/wwopen/api/customApp/price/GetStandardPriceInfoForCA
```

写入接口：

```http
POST https://open.work.weixin.qq.com/wwopen/api/customApp/price/SetStandardPriceInfoForCA
```

请求头：

```text
x-wecom-developer-page: /sass/customApp/app/detail
x-wecom-developer-perm: 50,51
```

请求体：

```json
{
  "corpappid": "wecom.app_id",
  "base_price_info": {
    "try_rule_info": {
      "try_rule_type": 2,
      "try_time": 60,
      "second_try_time": 15,
      "prove_file": {
        "file_id": null,
        "file_name": null
      }
    }
  },
  "clear_base_price_info": false
}
```

业务口径：

```text
开启试用
基础试用 60 天
限时额外试用 15 天
```

成功标准：

```text
is_already_set_try_info = true
base_price_info.try_rule_info.try_time = 60
base_price_info.try_rule_info.second_try_time = 15
```

### 5.5 设置企业微信授权登录回调域

```http
POST https://open.work.weixin.qq.com/wwopen/developer/customApp/tpl/corpApp
```

请求头：

```text
x-wecom-developer-page: /sass/customApp/app/detail/sso
```

请求体：

```json
{
  "suiteid": "1009479",
  "corpapp": {
    "app_id": "wecom.app_id",
    "sdk_auth": {
      "aes_app_id": "wecom.aes_app_id",
      "redirect_domain2": "wxwork.jiandaoyun.com",
      "bundleid": "",
      "signature_android": "",
      "packagename": "",
      "b_ios": false,
      "b_android": false
    }
  }
}
```

实现规则：

- `sdk_auth.aes_app_id` 必须从当前 app 详情继承，每个企业应用不同。
- 只覆盖 `redirect_domain2 = wxwork.jiandaoyun.com`。

成功标准：

```text
response.data.corpapp.sdk_auth.redirect_domain2 = wxwork.jiandaoyun.com
response.data.corpapp.sdk_auth.aes_app_id = 当前 app 的 aes_app_id
```

### 5.6 创建上线单

```http
POST https://open.work.weixin.qq.com/wwopen/developer/order/add
```

请求头：

```text
x-wecom-developer-page: /sass/customApp/deploy/list
x-wecom-developer-perm: 51
```

请求体：

```json
{
  "auditorder": {
    "suiteid": 1009479,
    "corpappid": "wecom.app_id"
  },
  "skipNotice": false
}
```

成功标准：

```text
response.data.auditorder.auditorderid 存在
response.data.auditorder.corpappid = wecom.app_id
response.data.auditorder.authcorp_name = enterprise_name
response.data.auditorder.status = 1
```

记录：

```text
wecom.auditorderid
wecom.auditorder_status = 1
wecom.order_created_at
```

### 5.7 等待并提交上线

本次现场确认：`order/add` 后需要等待一段时间，状态变成“待上线”后才能点击“提交上线”。第一版不强依赖轮询接口，采用固定延迟 + 失败重试。

等待策略：

```text
order/add 成功后，任务进入 waiting_wecom_online_delay
next_check_at = now + 5 分钟
到点后调用 order/set
```

提交接口：

```http
POST https://open.work.weixin.qq.com/wwopen/developer/order/set
```

请求头：

```text
x-wecom-developer-page: /sass/customApp/deploy/detail
x-wecom-developer-perm: 51
```

请求体：

```json
{
  "auditorder": {
    "status": 5,
    "auditorderid": "wecom.auditorderid"
  }
}
```

成功标准：

```text
response.data.auditorder.auditorderid = wecom.auditorderid
response.data.auditorder.status = 5
response.data.auditorder.corpappid = wecom.app_id
```

兜底策略：

- 如果 `order/set` 返回“状态不允许 / 还不能上线 / 审核中”，不判失败，设置 `next_check_at = now + 2 分钟` 后重试。
- 建议最大重试 5 次。
- 超过次数仍不能上线，进入 `manual_required`。
- 登录态失效进入 `waiting_login`，人工扫码续登后从 `wecom.auditorderid` 恢复。

可选轮询候选：

```http
GET /wwopen/developer/customApp/tpl/app/list?suiteid=1009479&app_id={app_id}&scene=1&with_str_corp_id=1&offset=0&limit=1
```

若该接口返回 `auditorder.status`，可用它替代固定等待；当前第一版先按固定 5 分钟处理。

## 6. 自动化状态机

建议任务状态：

```text
pending
running
waiting_login
waiting_wecom_online_delay
manual_required
success
failed
```

建议步骤：

```text
jdy_resolve_corp
wecom_resolve_app
generate_wecom_secrets
jdy_check_owner
jdy_install_bind
wecom_configure_app
wecom_set_privileges
wecom_set_trial_rule
wecom_set_sso_redirect_domain
wecom_create_online_order
wecom_wait_online_delay
wecom_submit_online_order
```

注意：真实跑通时，为了通过企微回调验证，`jdy_install_bind` 在 `wecom_configure_app` 前执行。旧计划中如先企微配置再简道云绑定，应按本文修正。

## 7. 失败处理

| 阶段 | 失败信号 | 处理 |
| --- | --- | --- |
| 简道云查企业 | 0 命中或多命中 | `manual_required` |
| User_ID 校验 | `can_bind_corp_secret` 非真且不是已绑定更新态 | `manual_required` |
| 简道云绑定 | 非 200 或未回显 `tenant_id/owner_id` | `failed`，保留脱敏响应 |
| 企微查应用 | 企业不唯一或 app_id 缺失 | `manual_required` |
| 保存开发信息 | 回调校验失败 | 检查简道云密钥是否已写入、token/aeskey 是否一致 |
| 保存开发信息 | 返回“数据不存在”且重新读取未确认字段 | 进入受控页面 fallback，保存后只读确认 |
| 权限设置 | 企业侧授权确认未完成 | 记录状态，等待客户侧确认或人工处理 |
| 试用规则 | `is_already_set_try_info` 非真 | 重试一次，仍失败进入 `manual_required` |
| 授权登录域 | `redirect_domain2` 不一致 | 重试一次，仍失败进入 `manual_required` |
| 创建上线单 | 无 `auditorderid` | `failed` |
| 提交上线 | 还不能上线 | 2 分钟后重试，最多 5 次 |
| 登录态 | 401、跳登录页、扫码页 | `waiting_login` |

## 8. 日志与审计字段

必须记录：

```text
enterprise_name
plain_corp_id_hash 或脱敏值
jdy.corp_secret_id 脱敏值
original_tenant_id
requested_user_id
install_tenant_id
install_owner_id
wecom.app_id
wecom.aes_app_id 脱敏值
wecom.auditorderid
wecom.auditorder_status
step status / started_at / finished_at / error_type / error_detail
```

禁止记录：

```text
Cookie
wwrtx.sid / wwrtx.vst / wwopen.open.sid / monitor
Token 明文
EncodingAESKey 明文
kitsecret 明文
完整 cURL
截图中的敏感字段
```

## 9. 与当前代码的关系

相关模块：

```text
rpa_platform/integrations/jdy_admin_client.py
rpa_platform/worker/hybrid_runner.py
rpa_platform/worker/wecom_rpa.py
rpa_platform/worker/scheduler.py
rpa_platform/worker/runner.py
rpa_platform/domain/default_flows.py
rpa_platform/domain/redaction.py
```

当前代码已经有简道云接口客户端、混合 Runner、dry-run 和 worker once 基础能力。后续实现应把企微侧从页面 RPA 提示逐步替换为接口 Client，同时保留登录态失效和人工续登状态。

## 10. 本次真实验证口径

已验证：

```text
简道云 get_corp_deploy_list 可用
简道云 get_owner 可用
简道云 install_corp_deploy 可用
企微 tpl/app/list 可用
企微 corpApp 基础配置保存可用
企微 setCustomizedAppPrivilege 权限设置可用
企微 SetStandardPriceInfoForCA 试用规则可用
企微 corpApp app/detail/sso 授权登录域设置可用
企微 order/add 创建上线单可用
企微 order/set 提交上线可用
```

最终业务口径：

```text
套件：简道云
wecom suiteid：1009479
简道云 suite_id：1
suite_scenario：main
应用主页域名：wxwork.jiandaoyun.com
基础试用：60 天
限时额外试用：15 天
上线等待：order/add 后固定等待 5 分钟，再 order/set；不满足条件则延迟重试
```
