import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib import request


PostJson = Callable[[str, Dict[str, Any], int], Dict[str, Any]]


def build_markdown_payload(title: str, lines: Iterable[str]) -> Dict[str, Any]:
    content_lines = ["**%s**" % title]
    content_lines.extend(str(line) for line in lines)
    return {"msgtype": "markdown", "markdown": {"content": "\n".join(content_lines)}}


def build_text_payload(content: str, mentioned_mobile_list: Optional[List[str]] = None) -> Dict[str, Any]:
    payload = {"msgtype": "text", "text": {"content": content}}
    if mentioned_mobile_list:
        payload["text"]["mentioned_mobile_list"] = list(mentioned_mobile_list)
    return payload


def build_image_payload(image_path: Path) -> Dict[str, Any]:
    raw = Path(image_path).read_bytes()
    return {
        "msgtype": "image",
        "image": {
            "base64": base64.b64encode(raw).decode("ascii"),
            "md5": hashlib.md5(raw).hexdigest(),
        },
    }


class WecomBotClient:
    def __init__(self, webhook_url: str, post_json: Optional[PostJson] = None, timeout: int = 10):
        self.webhook_url = webhook_url
        self.post_json = post_json or _post_json
        self.timeout = timeout

    def send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.post_json(self.webhook_url, payload, self.timeout)
        errcode = response.get("errcode", response.get("errCode", 0))
        errmsg = str(response.get("errmsg", response.get("message", "")))
        return {"ok": errcode in (0, "0", None), "errcode": errcode, "errmsg": errmsg}


def _post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"content-type": "application/json"},
    )
    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {"errcode": -1, "errmsg": "non-object response"}
    return data
