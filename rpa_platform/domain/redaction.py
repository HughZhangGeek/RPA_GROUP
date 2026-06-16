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


def mask_identifier(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return "%s***%s" % (value[:4], value[-4:])


def redact_context(value: Any) -> Any:
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, child in value.items():
            if key in SECRET_KEYS:
                result[key] = "***"
            elif key in MASKED_IDENTIFIER_KEYS and isinstance(child, str):
                result[key] = mask_identifier(child)
            else:
                result[key] = redact_context(child)
        return result
    if isinstance(value, list):
        return [redact_context(item) for item in value]
    return value
