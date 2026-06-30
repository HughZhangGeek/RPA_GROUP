MISSING_WECOM_APP_ERROR_MSG = "未在企微后台找到匹配的简道云应用，请检查授权企业名称、企业简称或套件名称是否一致"


def known_public_error_msg(detail: str) -> str:
    detail = detail.strip()
    if "no custom app matched authcorp name and app name" in detail:
        return MISSING_WECOM_APP_ERROR_MSG
    return ""
