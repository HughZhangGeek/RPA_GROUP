import json
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, status

from rpa_platform.domain.flow_steps import FlowStepValidationError
from rpa_platform.storage.sqlite_store import SQLiteStore


def create_flow_router(store: SQLiteStore) -> APIRouter:
    router = APIRouter(prefix="/platform")

    @router.get("/teams/{team_id}/flows", status_code=status.HTTP_200_OK)
    def list_flows(team_id: str) -> Dict[str, Any]:
        return {"items": [_flow_response(flow) for flow in store.list_flow_templates(team_id)]}

    @router.post("/teams/{team_id}/flows", status_code=status.HTTP_201_CREATED)
    def create_flow(team_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        name = _required_text(payload, "name")
        description = str(payload.get("description", "")).strip()
        flow_id = store.create_flow_template(team_id, name, description)
        return _flow_response(store.get_flow_template(flow_id))

    @router.get("/flows/{flow_id}/versions", status_code=status.HTTP_200_OK)
    def list_versions(flow_id: str) -> Dict[str, Any]:
        return {"items": [_version_response(version) for version in store.list_flow_versions(flow_id)]}

    @router.post("/flows/{flow_id}/versions/draft", status_code=status.HTTP_201_CREATED)
    def create_draft_version(flow_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        created_by = str(payload.get("created_by", "admin")).strip() or "admin"
        steps = payload.get("steps")
        try:
            version_id = store.create_flow_version(flow_id, steps=steps, created_by=created_by)
        except FlowStepValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        return _version_response(store.get_flow_version(version_id))

    @router.post("/flows/{flow_id}/versions/{version_id}/publish", status_code=status.HTTP_200_OK)
    def publish_version(flow_id: str, version_id: str) -> Dict[str, Any]:
        store.publish_flow_version(flow_id, version_id)
        return _flow_response(store.get_flow_template(flow_id))

    @router.post("/flows/{flow_id}/versions/{version_id}/copy", status_code=status.HTTP_201_CREATED)
    def copy_version(
        flow_id: str,
        version_id: str,
        payload: Dict[str, Any] = Body(default_factory=dict),
    ) -> Dict[str, Any]:
        created_by = str(payload.get("created_by", "admin")).strip() or "admin"
        copied_id = store.copy_flow_version(flow_id, version_id, created_by)
        return _version_response(store.get_flow_version(copied_id))

    @router.post("/flows/{flow_id}/versions/{version_id}/rollback", status_code=status.HTTP_200_OK)
    def rollback_version(flow_id: str, version_id: str) -> Dict[str, Any]:
        store.rollback_flow_version(flow_id, version_id)
        return _flow_response(store.get_flow_template(flow_id))

    return router


def _required_text(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required field: %s" % key,
        )
    text = str(value).strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Empty required field: %s" % key,
        )
    return text


def _flow_response(flow: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": flow["id"],
        "team_id": flow["team_id"],
        "name": flow["name"],
        "description": flow["description"],
        "published_version_id": flow["published_version_id"],
        "draft_version_id": flow["draft_version_id"],
        "created_at": flow["created_at"],
        "updated_at": flow["updated_at"],
    }


def _version_response(version: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": version["id"],
        "flow_template_id": version["flow_template_id"],
        "version_no": version["version_no"],
        "status": version["status"],
        "steps": json.loads(version["steps_json"]),
        "created_by": version["created_by"],
        "published_at": version["published_at"],
        "created_at": version["created_at"],
        "updated_at": version["updated_at"],
    }
