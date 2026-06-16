# 简道云后台企业微信绑定页接口化研究

## 结论摘要

- 页面入口：`https://dc.jdydevelop.com/fx_sa/wework_bind`
- 前端模块：`ant-web/src/pages/fx_sa/wework_bind/index.tsx`
- 绑定页接口都在 `fx_sa.wxwork` 下：
  - 搜索企业部署列表：`POST /api/fx_sa/wxwork/get_corp_deploy_list`
  - 提交前校验 User_ID：`POST /api/fx_sa/wxwork/get_owner`
  - 提交绑定：`POST /api/fx_sa/wxwork/install_corp_deploy`
- “绑定”按钮不会请求详情接口，只把当前表格行写入弹窗表单。
- 本次只做了搜索和弹窗读取验证，未点击“确定”，未调用提交绑定接口。

## 搜索接口

请求：

```json
{
  "filter": "明文CorpID或企业名称",
  "skip": 0,
  "limit": 10
}
```

前端分页固定 `pageSize = 10`。搜索词变化时 `skip = 0`，翻页时 `skip = (current - 1) * pageSize`。

响应由页面直接使用：

```json
{
  "has_more": false,
  "corp_deploy_list": [
    {
      "_id": "...",
      "corp_id": "密文企业ID",
      "name": "企业名称",
      "tenant_id": "已绑定User_ID或空",
      "suite_name": "云平台子产品",
      "integrate_suite_name": "集成模式套件名称",
      "suite_id": "套件ID",
      "suite_scenario": "套件场景"
    }
  ]
}
```

运行验证：用企业名称搜索样本企业，唯一命中；行内字段为“简道云 / 简道云 / main”，密文企业 ID 长度 32。文档不记录明文 CorpID 和完整密文企业 ID。

## 绑定弹窗

点击表格行的“绑定”按钮时，前端只执行本地状态更新：

```text
currentCorp = record
form.corp_id = record.corp_id
form.corp_name = record.name
form.tenant_id = record.tenant_id
modalVisible = true
```

因此没有独立的“获取绑定弹窗详情接口”。接口化实现中，弹窗详情应直接来自搜索接口返回的目标行。

弹窗字段：

- `corp_id`：企业 ID，disabled，必填
- `corp_name`：企业名称，必填
- `tenant_id`：User_ID，必填
- `token`：必填
- `encoding_aes_key`：encodingAesKey，必填

## 提交绑定流程

点击“确定”后，前端先做必填校验。若当前行已有 `tenant_id` 且与填写值不同，会弹出“确认换绑”二次确认；确认后才继续。

提交前校验：

```http
POST /api/fx_sa/wxwork/get_owner
```

请求体：

```json
{
  "user_id": "填写的User_ID",
  "suite_id": "搜索行里的suite_id",
  "suite_scenario": "搜索行里的suite_scenario"
}
```

如果响应中的 `can_bind_corp_secret` 不是真值，页面提示“当前企业不支持绑定代开发授权”，不会继续提交。

正式提交：

```http
POST /api/fx_sa/wxwork/install_corp_deploy
```

请求上下文：

```text
origin: https://dc.jdydevelop.com
referer: https://dc.jdydevelop.com/fx_sa/wework_bind
content-type: application/json
```

登录态来自 `dc.jdydevelop.com` 的浏览器 cookie。文档不记录 `monitor` 等会话 cookie；新平台实现也不要把 cookie 写入任务日志。

请求体：

```json
{
  "corp_id": "密文企业ID",
  "corp_name": "企业名称",
  "tenant_id": "填写的User_ID",
  "token": "企微生成的token",
  "encoding_aes_key": "企微生成的EncodingAESKey",
  "user_id": "同tenant_id",
  "suite_id": "搜索行里的suite_id",
  "suite_scenario": "搜索行里的suite_scenario"
}
```

已验证样本返回：

```json
{
  "tenant_id": "提交的User_ID",
  "owner_id": "提交的User_ID"
}
```

样本中 `tenant_id` 与 `owner_id` 均回显为提交的 User_ID。接口 HTTP 200 且返回上述字段时，可以视为简道云后台绑定提交成功。

前端使用普通 `axios.post(path, data)`，HTTP 200 后直接认为成功并提示“绑定成功”。错误状态在前端有通用提示：

- `401`：用户未登录
- `402`：当前会话已过期
- `403`：没有数据请求权限
- `404`：找不到数据资源
- 其他错误：解析后端错误体并弹出

## 企微后台授权企业搜索接口

页面入口：

```text
https://open.work.weixin.qq.com/wwopen/developers/tools#/sass/customApp/tpl/info?id=1009479
```

搜索接口：

```http
GET /wwopen/developer/customApp/tpl/app/list
```

查询参数：

```text
lang=zh_CN
ajax=1
f=json
suiteid=1009479
scene=1
corp_name_keyword=企业名称
offset=0
limit=10
random=随机数
```

请求头需要带企微开发者后台页面上下文：

```text
referer: https://open.work.weixin.qq.com/wwopen/developers/tools
x-wecom-developer-page: /sass/customApp/tpl/info
x-wecom-developer-perm: 50
```

登录态来自浏览器 cookie。文档不记录 cookie、sid、vst 等会话值；新平台实现也不要把这些值写入任务日志。

样本响应结构：

```json
{
  "data": {
    "corpapp_list": {
      "corpapp": [
        {
          "app_id": "...",
          "name": "简道云",
          "authcorp_name": "安徽云速付",
          "homeurl": "",
          "redirect_domain": "",
          "callbackurl": "",
          "token": "",
          "aeskey": "",
          "customized_app_status": 0,
          "sdk_auth": {
            "aes_app_id": "..."
          }
        }
      ]
    },
    "total": 1,
    "has_next_page": false
  }
}
```

运行样本：按企业名称搜索样本企业，`total = 1`，返回应用名为“简道云”，`customized_app_status = 0`。结合页面截图，该状态对应“待开发”，后续页面操作为“开始代开发应用”。

企微模板选择规则：

- 集成模式套件名称为“简道云”：`suiteid=1009479`
- 集成模式套件名称为“简道云教育版”：`suiteid=1038071`

接口化实现建议：

1. 使用企业名称搜索，企微侧没有明文 CorpID 可查。
2. 要求 `total = 1` 且 `corpapp[0].authcorp_name` 与目标企业名称完全一致，否则进入人工处理。
3. `customized_app_status = 0` 时才能进入“开始代开发应用”分支；其他状态先记录状态码和页面文案，再决定是否等待、重试或人工处理。
4. 响应中的 `token/aeskey/callbackurl/homeurl` 在待开发状态为空，后续应在配置开发信息步骤后读取或生成。

## 企微后台创建代开发应用配置接口

该接口对应企微后台“开始代开发应用”后的配置提交动作，不是简道云后台绑定动作。它会把应用主页、回调 URL、可信域名、token、aeskey 等写入企微侧，属于有副作用的关键提交。

```http
POST /wwopen/developer/customApp/tpl/corpApp
```

查询参数：

```text
lang=zh_CN
ajax=1
f=json
random=随机数
```

请求上下文：

```text
origin: https://open.work.weixin.qq.com
referer: https://open.work.weixin.qq.com/wwopen/developers/tools
content-type: application/json
x-wecom-developer-page: /sass/customApp/app/create
x-wecom-developer-perm: 50
```

登录态来自企微开发者后台浏览器 cookie。文档不记录 sid、vst 等会话值；新平台实现也不要把 cookie 或企微 token/aeskey 写入任务日志。

请求体结构：

```json
{
  "suiteid": "1009479",
  "corpapp": {
    "app_id": "搜索接口返回的app_id",
    "suiteid": 1009479,
    "page_type": "CREATE",
    "name": "简道云",
    "name_pinyin": "jiandaoyun",
    "logo": "模板logo",
    "description": "模板描述",
    "homeurl": "https://wxwork.jiandaoyun.com/wxwork/{corp_secret_id}/dashboard",
    "redirect_domain": "wxwork.jiandaoyun.com",
    "callbackurl": "https://wxwork.jiandaoyun.com/wxwork/corp/{corp_secret_id}/service",
    "token": "企微生成或确认的token",
    "aeskey": "企微生成或确认的EncodingAESKey",
    "enter_homeurl_in_wx": true,
    "is_homeurl_miniprogram": false,
    "domain_belong_to": 0,
    "jssdkdomain_list": {
      "domains": []
    },
    "white_ip_list": {
      "ip": []
    },
    "miniprogram_enter_path": "",
    "miniprogramInfo": {}
  }
}
```

样本请求里还包含模板元数据字段，例如 `kitid`、`kitsecret`、`ww_corpid`、`createtime`、`updatetime`、`suite_type`、`publish_status`、行业分类和扩展信息等。这些字段应优先来自企微页面接口返回的模板或应用记录，不要在 RPA 平台里硬编码真实值。

直接构造可行性判断：

- 可以构造，但必须在企微搜索唯一命中且 `customized_app_status = 0` 后才允许。
- `corp_secret_id` 必须来自简道云后台搜索行的密文企业 ID，用于派生 `homeurl` 和 `callbackurl`。
- `token/aeskey` 必须与随后提交给简道云后台的值一致。
- `app_id`、模板元数据、`kitid/kitsecret` 等必须从企微页面接口或当前记录继承，不要凭记忆拼。
- 该接口是有副作用提交，默认只在任务进入明确“提交企微配置”步骤时调用；dry-run 只能生成脱敏请求摘要，不应发请求。

当前执行决策：

- 第一版不直接调用企微提交接口。
- 企微后台仍使用 RPA/浏览器页面操作，接口信息仅用于理解页面状态、字段来源和后续排障。
- 简道云后台使用内部接口优先，替代原页面 RPA 的搜索、取密文企业 ID 和最终绑定提交。

新平台默认流程 action 名称：

```text
jdy_resolve_corp
derive_wecom_urls
wecom_configure_app
jdy_check_owner
jdy_install_bind
wecom_submit_review
wecom_wait_review
wecom_submit_online
```

## 企微 RPA 页面步骤确认

企微侧第一版仍按页面 RPA 执行，已确认后半段页面状态和操作顺序：

1. 应用试用配置：
   - 勾选“开启试用”。
   - 试用时间选择“60天”。
   - 勾选“限时额外试用”。
   - 额外试用时间选择“7天”。
   - 点击“确定”保存。
2. 使用配置：
   - 应用主页配置为 `https://wxwork.jiandaoyun.com/wxwork/{corp_secret_id}/dashboard`。
   - 桌面端独立主页保持“未配置”。
   - 可信域名配置为 `wxwork.jiandaoyun.com`。
   - IP 白名单保持“未配置”。
3. 回调配置：
   - 代开发应用回调 URL 配置为 `https://wxwork.jiandaoyun.com/wxwork/corp/{corp_secret_id}/service`。
   - Token 与 EncodingAESKey 从企微页面读取，后续传给简道云后台 `install_corp_deploy`。
4. 权限设置：
   - 组织架构信息：未开启。
   - 成员基本信息：姓名、部门名。
   - 成员敏感信息：未设置。
   - 数据与智能专区权限：未开启。
   - 企业客户权限：未开启。
   - 微信客服：未开启。
   - 对外收款：未开启。
5. 提交上线：
   - 点击“提交上线”。
   - 提交成功后进入“代开发应用上线”列表。
   - 目标行显示企业客户名称，状态为“审核中”。
   - 任务状态应进入等待审核阶段，后续由定时检查或人工确认继续。
6. 审核通过后：
   - 列表目标行状态会从“审核中”变为“待上线”。
   - “待上线”是后续执行正式上线动作的触发状态。
   - 新平台状态建议从 `waiting_review` 流转为 `ready_to_online`。
7. 正式上线：
   - 进入“代开发应用审核详情”页。
   - 状态显示“待上线”。
   - 点击右侧“提交上线”即可，不需要额外配置。

截图中出现的完整密文企业 ID、Token、EncodingAESKey 不写入文档；任务日志只保存脱敏摘要。

## 新平台接入建议

1. 新增简道云后台接口客户端，使用固定浏览器 profile 的登录态发请求；不要读取或落盘 cookie 明文。
2. `search_corp_deploy(filter)` 优先用明文 CorpID，0 命中再用企业名称；必须要求唯一命中。
3. `open_bind_modal` 这类页面动作可删除，改为从搜索行提取 `corp_id/name/tenant_id/suite_id/suite_scenario`。
4. 若目标行已有 `tenant_id`：
   - 与申请 User_ID 相同：可继续。
   - 与申请 User_ID 不同：进入人工处理或要求显式“允许换绑”配置，默认不要自动换绑。
5. 企微侧继续使用 RPA 完成“开始代开发应用”和配置提交，RPA 输出 `token/aeskey` 供简道云接口使用。
6. 简道云正式绑定分两段：
   - `get_owner` 只读校验，可在拿到 User_ID 后提前执行。
   - `install_corp_deploy` 是有副作用提交，必须只在企微 RPA 已确认 token 和 EncodingAESKey 后执行。
7. 任务审计中保存脱敏请求摘要和响应状态，不保存明文 CorpID、完整密文企业 ID、token 或 EncodingAESKey。

## 未完成事项

- 当前 Chrome 自动化通道可以操控页面和读取 DOM，但受限执行域不可直接调用页面 `fetch/XMLHttpRequest`，本次未拿到原始 Network 响应体。
- 提交接口只从前端源码分析，未真实调用。
- 后续如果需要响应体样例，可在人工打开 DevTools Network 后导出 HAR，或在新平台 Worker 侧用持久化浏览器 profile 的 APIRequestContext 做只读接口验证。
