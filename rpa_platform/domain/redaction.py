from typing import Any, Dict


SECRET_KEYS = {
    "token",
    "aeskey",
    "encoding_aes_key",
    "encodingAesKey",
    "kitsecret",
    "cookie",
}

MASKED_IDENTIFIER_KEYS = {
    "corp_secret_id",
    "corp_id",
    "app_id",
    "aes_app_id",
}

WECOM_URL_KEYS = {
    "homeurl",
    "callbackurl",
}


def mask_identifier(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return "%s***%s" % (value[:4], value[-4:])


def mask_wecom_url(value: str) -> str:
    segments = value.split("/")
    for index, segment in enumerate(segments):
        if segment == "wxwork" and index + 1 < len(segments):
            next_segment = segments[index + 1]
            if next_segment == "corp" and index + 2 < len(segments):
                segments[index + 2] = mask_identifier(segments[index + 2])
            else:
                segments[index + 1] = mask_identifier(next_segment)
    return "/".join(segments)


def redact_context(value: Any) -> Any:
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, child in value.items():
            if key in SECRET_KEYS:
                result[key] = "***"
            elif key in MASKED_IDENTIFIER_KEYS and isinstance(child, str):
                result[key] = mask_identifier(child)
            elif key in WECOM_URL_KEYS and isinstance(child, str):
                result[key] = mask_wecom_url(child)
            else:
                result[key] = redact_context(child)
        return result
    if isinstance(value, list):
        return [redact_context(item) for item in value]
    return value
