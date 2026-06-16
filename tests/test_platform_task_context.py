import tempfile
import unittest
from pathlib import Path

from rpa_platform.domain.redaction import redact_context
from rpa_platform.storage.sqlite_store import SQLiteStore


class TaskContextStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(str(Path(self.tmpdir.name) / "platform.db"))
        self.store.init_schema()
        self.team_id = self.store.create_team("交付团队")
        self.flow_id = self.store.create_flow_template(self.team_id, "企微代开发应用上线", "")
        version_id = self.store.create_flow_version(
            self.flow_id,
            steps=[{"key": "jdy_resolve_corp", "name": "简道云查找绑定企业", "action": "jdy_resolve_corp"}],
            created_by="codex",
        )
        self.store.publish_flow_version(self.flow_id, version_id)
        self.task_id = self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_id,
            enterprise_name="安徽云速付",
            corp_id="ww-demo",
            source_user_id="user-1",
            idempotency_key="wecom_app_launch:ww-demo:user-1",
            payload={"user_id": "user-1", "企业客户名称": "安徽云速付", "企业微信明文 CorpID": "ww-demo"},
        ).task_id

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_merge_task_context_preserves_nested_values(self):
        self.store.merge_task_context(self.task_id, {"jdy": {"corp_secret_id": "secret-corp"}})
        self.store.merge_task_context(self.task_id, {"wecom": {"token": "token-secret"}})

        context = self.store.get_task_context(self.task_id)

        self.assertEqual(context["jdy"]["corp_secret_id"], "secret-corp")
        self.assertEqual(context["wecom"]["token"], "token-secret")

    def test_task_detail_includes_redacted_runtime_context(self):
        self.store.merge_task_context(
            self.task_id,
            {
                "jdy": {"corp_secret_id": "corp-secret-value-1234"},
                "wecom": {"token": "token-secret-value", "encoding_aes_key": "aes-secret-value"},
            },
        )

        detail = self.store.get_task_detail(self.task_id)

        self.assertEqual(detail["runtime_context"]["jdy"]["corp_secret_id"], "corp***1234")
        self.assertEqual(detail["runtime_context"]["wecom"]["token"], "***")
        self.assertEqual(detail["runtime_context"]["wecom"]["encoding_aes_key"], "***")

    def test_redact_context_masks_secret_like_fields(self):
        redacted = redact_context(
            {
                "corp_secret_id": "corp-secret-value-1234",
                "token": "token-secret",
                "encoding_aes_key": "aes-secret",
                "safe": "安徽云速付",
            }
        )

        self.assertEqual(redacted["corp_secret_id"], "corp***1234")
        self.assertEqual(redacted["token"], "***")
        self.assertEqual(redacted["encoding_aes_key"], "***")
        self.assertEqual(redacted["safe"], "安徽云速付")

    def test_set_task_current_step_updates_task_pointer(self):
        self.store.set_task_current_step(self.task_id, "jdy_resolve_corp")

        task = self.store.get_task(self.task_id)

        self.assertEqual(task["current_step_key"], "jdy_resolve_corp")


if __name__ == "__main__":
    unittest.main()
