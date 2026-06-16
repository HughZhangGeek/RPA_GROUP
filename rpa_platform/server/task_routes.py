from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, status

from rpa_platform.domain.state_machine import TaskStatus
from rpa_platform.storage.sqlite_store import SQLiteStore


ACTION_STATUS_MAP = {
    "waiting_login": TaskStatus.WAITING_LOGIN,
    "waiting_manual_selection": TaskStatus.WAITING_MANUAL_SELECTION,
    "waiting_manual_intervention": TaskStatus.WAITING_MANUAL_INTERVENTION,
}


def create_task_router(store: SQLiteStore) -> APIRouter:
    router = APIRouter(prefix="/platform")

    @router.get("/tasks/{task_id}", status_code=status.HTTP_200_OK)
    def get_task(task_id: str) -> Dict[str, Any]:
        try:
            return store.get_task_detail(task_id)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    @router.post("/tasks/{task_id}/manual-actions", status_code=status.HTTP_201_CREATED)
    def create_manual_action(task_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        action_type = _required_text(payload, "action_type")
        if action_type not in ACTION_STATUS_MAP:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="unsupported action_type: %s" % action_type,
            )
        reason = _required_text(payload, "reason")
        candidates = payload.get("candidates", [])
        action_id = store.create_manual_action(task_id, action_type, reason, candidates)
        store.set_task_status(task_id, ACTION_STATUS_MAP[action_type])

        artifact = payload.get("artifact")
        if artifact:
            store.create_task_artifact(
                task_id=task_id,
                step_id=artifact.get("step_id"),
                artifact_type=_required_text(artifact, "artifact_type"),
                path=_required_text(artifact, "path"),
                metadata=artifact.get("metadata", {}),
            )
        return store.get_manual_action(action_id)

    @router.post("/tasks/{task_id}/resume", status_code=status.HTTP_200_OK)
    def resume_task(task_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        handled_by = _required_text(payload, "handled_by")
        try:
            return store.resume_task(
                task_id,
                handled_by=handled_by,
                selected_candidate=payload.get("selected_candidate"),
                note=str(payload.get("note", "")),
            )
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

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
