from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException, status

from rpa_platform.server.flow_routes import create_flow_router
from rpa_platform.server.task_routes import create_task_router
from rpa_platform.server.webhook_service import JdyWebhookService, PayloadValidationError
from rpa_platform.storage.sqlite_store import SQLiteStore


def create_app(store: SQLiteStore, default_team_id: str, default_flow_template_id: str) -> FastAPI:
    app = FastAPI(title="RPA Platform", docs_url="/platform/docs", redoc_url=None)
    webhook_service = JdyWebhookService(store, default_team_id, default_flow_template_id)

    @app.get("/platform/healthz", status_code=status.HTTP_200_OK)
    def healthz() -> Dict[str, str]:
        return {"status": "ok", "service": "rpa_platform"}

    @app.post("/platform/webhooks/jdy/wecom-app-launch", status_code=status.HTTP_202_ACCEPTED)
    def receive_jdy_wecom_app_launch(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        try:
            result = webhook_service.receive(payload)
        except PayloadValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        return {
            "task_id": result.task_id,
            "created": result.created,
            "status": "accepted",
        }

    app.include_router(create_flow_router(store))
    app.include_router(create_task_router(store))
    return app
