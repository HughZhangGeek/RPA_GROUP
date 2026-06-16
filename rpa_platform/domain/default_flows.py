WECOM_APP_LAUNCH_FLOW_STEPS = [
    {
        "key": "jdy_resolve_corp",
        "name": "简道云查找绑定企业",
        "action": "jdy_resolve_corp",
        "target": "jdy",
    },
    {
        "key": "derive_wecom_urls",
        "name": "生成企微配置 URL",
        "action": "derive_wecom_urls",
        "target": "system",
    },
    {
        "key": "wecom_configure_app",
        "name": "企微页面配置代开发应用",
        "action": "wecom_configure_app",
        "target": "wecom",
        "config": {"engine": "browser_use", "task_template": "wecom_configure_app_v1"},
    },
    {
        "key": "jdy_check_owner",
        "name": "简道云校验绑定 User_ID",
        "action": "jdy_check_owner",
        "target": "jdy",
    },
    {
        "key": "jdy_install_bind",
        "name": "简道云提交企业微信绑定",
        "action": "jdy_install_bind",
        "target": "jdy",
    },
    {
        "key": "wecom_submit_review",
        "name": "企微提交上线进入审核",
        "action": "wecom_submit_review",
        "target": "wecom",
        "config": {"engine": "browser_use", "task_template": "wecom_submit_review_v1"},
    },
    {
        "key": "wecom_wait_review",
        "name": "等待企微审核通过",
        "action": "wecom_wait_review",
        "target": "wecom",
        "config": {"engine": "browser_use", "task_template": "wecom_check_review_status_v1"},
    },
    {
        "key": "wecom_submit_online",
        "name": "企微待上线后提交上线",
        "action": "wecom_submit_online",
        "target": "wecom",
        "config": {"engine": "browser_use", "task_template": "wecom_submit_online_v1"},
    },
]


WECOM_BIND_SERVICE_FLOW_STEPS = [
    {"key": "jdy_wecom_bind_service", "name": "企微绑定接口服务", "action": "jdy_wecom_bind_service", "target": "service"},
    {"key": "wecom_wait_online_delay", "name": "等待企微上线单可提交", "action": "wecom_wait_online_delay", "target": "service"},
    {"key": "wecom_submit_online_order", "name": "企微提交上线单", "action": "wecom_submit_online_order", "target": "service"},
]
