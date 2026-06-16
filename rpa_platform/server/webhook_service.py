from typing import Any, Dict

from rpa_platform.storage.sqlite_store import SQLiteStore, TaskCreateResult


class PayloadValidationError(ValueError):
    """Raised when a Jiandaoyun webhook payload lacks required fields."""


class JdyWebhookService:
    def __init__(self, store: SQLiteStore, team_id: str, flow_template_id: str):
        self.store = store
        self.team_id = team_id
        self.flow_template_id = flow_template_id

    def receive(self, payload: Dict[str, Any]) -> TaskCreateResult:
        user_id = self._required_text(payload, "user_id")
        enterprise_name = self._required_text(payload, "企业客户名称")
        corp_id = self._required_text(payload, "企业微信明文 CorpID")
        idempotency_key = f"wecom_app_launch:{corp_id}:{user_id}"
        return self.store.create_task_from_published_flow(
            team_id=self.team_id,
            flow_template_id=self.flow_template_id,
            enterprise_name=enterprise_name,
            corp_id=corp_id,
            source_user_id=user_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    @staticmethod
    def _required_text(payload: Dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if value is None:
            raise PayloadValidationError(f"Missing required field: {key}")
        text = str(value).strip()
        if not text:
            raise PayloadValidationError(f"Empty required field: {key}")
        return text
