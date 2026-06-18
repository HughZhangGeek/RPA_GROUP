import hashlib
import tempfile
import unittest
from pathlib import Path

from rpa_platform.notifications.wecom_bot import (
    WecomBotClient,
    build_image_payload,
    build_markdown_payload,
    build_text_payload,
)


class WecomBotPayloadTest(unittest.TestCase):
    def test_image_payload_uses_base64_and_md5_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "login-qr.png"
            content = bytes([0, 1, 2, 3])
            image_path.write_bytes(content)

            payload = build_image_payload(image_path)

        self.assertEqual(payload["msgtype"], "image")
        self.assertEqual(payload["image"]["md5"], hashlib.md5(content).hexdigest())
        self.assertNotIn(str(image_path), str(payload))

    def test_markdown_and_text_payloads_do_not_include_webhook(self):
        markdown = build_markdown_payload(
            title="企微后台登录态失效",
            lines=["任务：task-001", "状态：等待管理员扫码"],
        )
        text = build_text_payload("请处理企微后台登录态恢复", mentioned_mobile_list=["13800000000"])

        self.assertEqual(markdown["msgtype"], "markdown")
        self.assertIn("企微后台登录态失效", markdown["markdown"]["content"])
        self.assertEqual(text["msgtype"], "text")
        self.assertEqual(text["text"]["mentioned_mobile_list"], ["13800000000"])
        self.assertNotIn("webhook", str(markdown).lower())
        self.assertNotIn("webhook", str(text).lower())


class WecomBotClientTest(unittest.TestCase):
    def test_send_posts_to_webhook_without_adding_webhook_to_payload_or_result(self):
        posts = []

        def fake_post(url, payload, timeout):
            posts.append({"url": url, "payload": payload, "timeout": timeout})
            return {"errcode": 0, "errmsg": "ok"}

        client = WecomBotClient(
            webhook_url="https://example.invalid/wecom-bot",
            post_json=fake_post,
            timeout=3,
        )

        result = client.send(build_text_payload("扫码登录"))

        self.assertEqual(result, {"ok": True, "errcode": 0, "errmsg": "ok"})
        self.assertEqual(posts[0]["url"], "https://example.invalid/wecom-bot")
        self.assertEqual(posts[0]["payload"]["text"]["content"], "扫码登录")
        self.assertNotIn("example.invalid", str(posts[0]["payload"]))
        self.assertNotIn("example.invalid", str(result))


if __name__ == "__main__":
    unittest.main()
