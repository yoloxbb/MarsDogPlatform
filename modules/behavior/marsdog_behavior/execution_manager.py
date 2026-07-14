"""Execution Manager — manages the lifecycle of behavior goal execution.

Handles:
- Sending goals to the executor (MockActionExecutor or ActionClientAdapter)
- Monitoring feedback and result
- Canceling goals on timeout or preemption
- Tracking current execution state
"""

from __future__ import annotations

import time
from typing import Optional

from bionic_dog_bt.datatypes import ActiveBehavior, ExecutorFeedback, BehaviorFeedbackEvent
from bionic_dog_bt.constants import STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILURE, STATUS_CANCELED
from bionic_dog_bt.logger import get_logger, LogEvent

_log = get_logger("exec_mgr")


class ExecutionManager:
    """Manages the lifecycle of a single executing behavior goal.

    Wraps an ExecutorInterface (mock or ROS2 Action Client) and provides
    a consistent interface for the behavior tree tick loop.
    """

    def __init__(self, executor):
        """Args:
            executor: ExecutorInterface implementation
        """
        self._executor = executor
        self._current_goal_id: Optional[str] = None
        self._last_goal_id: Optional[str] = None
        self._last_feedback: Optional[ExecutorFeedback] = None

    @property
    def current_goal_id(self) -> Optional[str]:
        return self._current_goal_id

    @property
    def last_goal_id(self) -> Optional[str]:
        return self._last_goal_id

    def send_goal(self, active: ActiveBehavior, blackboard) -> str:
        """Send a goal to the executor and update the blackboard.

        Returns the goal_id.
        """
        goal_id = self._executor.send_goal(active)
        blackboard.start_behavior(active, goal_id)
        blackboard.executor_feedback = self._executor.get_feedback(goal_id)
        blackboard.active_behavior = None  # Consumed

        self._current_goal_id = goal_id
        self._last_goal_id = goal_id

        mode = "interactive" if active.params.get("interactive") else "solo"
        _log.event(LogEvent.BEHAVIOR_START,
                   behavior_name=active.behavior_name,
                   priority_level=active.priority_level,
                   mode=mode, goal_id=goal_id)
        return goal_id

    def cancel_current(self, blackboard) -> bool:
        """Cancel the currently running goal."""
        if self._current_goal_id:
            result = self._executor.cancel_goal(self._current_goal_id)
            self._current_goal_id = None
            return result
        return False

    def tick(self, blackboard) -> Optional[BehaviorFeedbackEvent]:
        """Advance execution and check for results.

        Returns a BehaviorFeedbackEvent if the current goal completed,
        None otherwise.
        """
        self._executor.tick()

        if blackboard.current_goal_id is None:
            return None

        # Check timeout
        if blackboard.current_status == STATUS_RUNNING and blackboard.check_timeout():
            blackboard.mark_timeout()
            if blackboard.current_goal_id:
                self._executor.cancel_goal(blackboard.current_goal_id)
                cb = blackboard.current_behavior
                _log.event(LogEvent.BEHAVIOR_TIMEOUT,
                           behavior_name=cb.behavior_name if cb else "?",
                           timeout_sec=cb.timeout_sec if cb else 0)
            self._current_goal_id = None
            return None

        # Check result
        if blackboard.current_goal_id and blackboard.current_status == STATUS_RUNNING:
            result = self._executor.get_result(blackboard.current_goal_id)
            if result is not None:
                blackboard.last_feedback_event = result
                blackboard.current_status = result.status

                if blackboard.current_behavior:
                    blackboard.set_cooldown(
                        blackboard.current_behavior.behavior_name,
                        blackboard.current_behavior.cooldown_sec)

                _log.event(LogEvent.BEHAVIOR_COMPLETE,
                           behavior_name=result.behavior_name,
                           status=result.status, reward=result.reward)

                self._executor.remove_goal(blackboard.current_goal_id)
                self._current_goal_id = None
                return result

        # Update feedback
        if blackboard.current_goal_id and blackboard.current_status == STATUS_RUNNING:
            blackboard.executor_feedback = self._executor.get_feedback(
                blackboard.current_goal_id)

        return None

    def has_active_goal(self) -> bool:
        """Check if there's an active goal executing."""
        return self._current_goal_id is not None

    def clear(self, blackboard) -> None:
        """Clear execution state (e.g., after preemption)."""
        if self._current_goal_id:
            self._executor.remove_goal(self._current_goal_id)
        self._current_goal_id = None
        self._last_feedback = None
