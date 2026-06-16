from enum import Enum
from typing import Union


class InvalidTaskTransition(ValueError):
    """Raised when a task status transition is not allowed."""


class TaskStatus(str, Enum):
    PENDING = "pending"
    CHECKING_LOGIN = "checking_login"
    RUNNING = "running"
    WAITING_LOGIN = "waiting_login"
    WAITING_MANUAL_SELECTION = "waiting_manual_selection"
    WAITING_MANUAL_INTERVENTION = "waiting_manual_intervention"
    WAITING_WECOM_REVIEW = "waiting_wecom_review"
    WAITING_WECOM_ONLINE_DELAY = "waiting_wecom_online_delay"
    READY_TO_ONLINE = "ready_to_online"
    WAITING_TEST_CONFIRMATION = "waiting_test_confirmation"
    JDY_CALLBACK_FAILED = "jdy_callback_failed"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    TaskStatus.SUCCESS,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


ALLOWED_TASK_TRANSITIONS = {
    TaskStatus.PENDING: {
        TaskStatus.CHECKING_LOGIN,
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.CHECKING_LOGIN: {
        TaskStatus.RUNNING,
        TaskStatus.WAITING_LOGIN,
        TaskStatus.FAILED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_LOGIN,
        TaskStatus.WAITING_MANUAL_SELECTION,
        TaskStatus.WAITING_MANUAL_INTERVENTION,
        TaskStatus.WAITING_WECOM_REVIEW,
        TaskStatus.WAITING_WECOM_ONLINE_DELAY,
        TaskStatus.READY_TO_ONLINE,
        TaskStatus.WAITING_TEST_CONFIRMATION,
        TaskStatus.JDY_CALLBACK_FAILED,
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_LOGIN: {
        TaskStatus.CHECKING_LOGIN,
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_MANUAL_SELECTION: {
        TaskStatus.CHECKING_LOGIN,
        TaskStatus.RUNNING,
        TaskStatus.WAITING_MANUAL_INTERVENTION,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_MANUAL_INTERVENTION: {
        TaskStatus.CHECKING_LOGIN,
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_WECOM_REVIEW: {
        TaskStatus.CHECKING_LOGIN,
        TaskStatus.RUNNING,
        TaskStatus.READY_TO_ONLINE,
        TaskStatus.WAITING_MANUAL_INTERVENTION,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_WECOM_ONLINE_DELAY: {
        TaskStatus.CHECKING_LOGIN,
        TaskStatus.RUNNING,
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.WAITING_MANUAL_INTERVENTION,
        TaskStatus.CANCELLED,
    },
    TaskStatus.READY_TO_ONLINE: {
        TaskStatus.CHECKING_LOGIN,
        TaskStatus.RUNNING,
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_TEST_CONFIRMATION: {
        TaskStatus.RUNNING,
        TaskStatus.WAITING_MANUAL_INTERVENTION,
        TaskStatus.CANCELLED,
    },
    TaskStatus.JDY_CALLBACK_FAILED: {
        TaskStatus.RUNNING,
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.SUCCESS: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


def ensure_task_transition(current: Union[TaskStatus, str], target: Union[TaskStatus, str]) -> None:
    current_status = TaskStatus(current)
    target_status = TaskStatus(target)
    if target_status not in ALLOWED_TASK_TRANSITIONS[current_status]:
        raise InvalidTaskTransition(
            f"Invalid task transition: {current_status.value} -> {target_status.value}"
        )
