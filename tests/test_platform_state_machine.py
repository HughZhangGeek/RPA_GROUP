import unittest

from rpa_platform.domain.state_machine import (
    InvalidTaskTransition,
    TaskStatus,
    ensure_task_transition,
)


class TaskStateMachineTest(unittest.TestCase):
    def test_allows_waiting_review_to_release_robot_and_resume_online(self):
        ensure_task_transition(TaskStatus.RUNNING, TaskStatus.WAITING_WECOM_REVIEW)
        ensure_task_transition(TaskStatus.WAITING_WECOM_REVIEW, TaskStatus.READY_TO_ONLINE)
        ensure_task_transition(TaskStatus.READY_TO_ONLINE, TaskStatus.RUNNING)
        ensure_task_transition(TaskStatus.RUNNING, TaskStatus.SUCCESS)

    def test_rejects_transition_from_terminal_success_back_to_running(self):
        with self.assertRaises(InvalidTaskTransition):
            ensure_task_transition(TaskStatus.SUCCESS, TaskStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()
