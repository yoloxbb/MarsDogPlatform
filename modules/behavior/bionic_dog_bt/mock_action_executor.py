"""Mock action executor: simulates behavior execution.

Builds randomized action sequences from the action catalog.
Falls back to YAML action_sequence if no catalog entry exists.
Each step has a duration; the executor simulates progress over time.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from .datatypes import (
    ActiveBehavior,
    BehaviorFeedbackEvent,
    BehaviorSpec,
    ExecutorFeedback,
)
from .constants import (
    STATUS_RUNNING,
    STATUS_SUCCESS,
    STATUS_FAILURE,
    STATUS_CANCELED,
)
from .yaml_loader import YAMLLoader
from .action_catalog import build_action_sequence


class MockGoal:
    """Internal representation of an executing goal.

    Uses an explicit action_sequence list (built from catalog or YAML)
    rather than reading from BehaviorSpec each time.
    """

    def __init__(self, goal_id: str, behavior: ActiveBehavior,
                 action_sequence: list[dict]):
        self.goal_id = goal_id
        self.behavior = behavior
        self.action_sequence: list[dict] = action_sequence
        self.status: str = STATUS_RUNNING
        self.current_step: int = 0
        self.step_start_time: float = time.time()
        self.total_steps: int = len(action_sequence)
        self.start_time: float = time.time()

    @property
    def progress(self) -> float:
        """Overall progress 0.0 .. 1.0."""
        if self.total_steps == 0:
            return 1.0
        completed_steps = self.current_step
        if self.current_step < self.total_steps:
            step = self.action_sequence[self.current_step]
            elapsed = time.time() - self.step_start_time
            duration = max(step.get("duration", 1.0), 0.001)
            partial = min(elapsed / duration, 1.0)
        else:
            partial = 0.0
        return min((completed_steps + partial) / self.total_steps, 1.0)

    @property
    def safe_to_interrupt(self) -> bool:
        """Whether current step is at a safe point for interruption."""
        if self.current_step >= self.total_steps:
            return True
        step = self.action_sequence[self.current_step]
        return bool(step.get("safe_to_interrupt", True))

    @property
    def current_step_info(self) -> dict:
        """Info about the current executing step."""
        if self.current_step < self.total_steps:
            return dict(self.action_sequence[self.current_step])
        return {}

    @property
    def current_action(self) -> str:
        """The action ID currently executing."""
        return self.current_step_info.get("action", "N/A")


class MockActionExecutor:
    """Simulates a robot action executor.

    Builds randomized action sequences from the action catalog at goal
    creation time. Falls back to YAML action_sequence for behaviors not
    in the catalog. Reports progress and safe_to_interrupt via get_feedback().
    """

    def __init__(self, yaml_loader: YAMLLoader):
        self._loader = yaml_loader
        self._goals: dict[str, MockGoal] = {}
        self._completed: dict[str, BehaviorFeedbackEvent] = {}
        self._canceled: set[str] = set()

    def send_goal(self, active_behavior: ActiveBehavior) -> str:
        """Send a new goal to the executor. Returns goal_id.

        Builds a randomized action sequence from the action catalog.
        Falls back to the YAML spec's action_sequence if no catalog entry.
        """
        interactive = active_behavior.params.get("interactive", False)
        action_seq = build_action_sequence(
            active_behavior.behavior_name, interactive=interactive
        )

        if not action_seq:
            # Fall back to YAML spec
            spec = self._loader.get_spec(active_behavior.behavior_name)
            if spec is None:
                raise ValueError(f"Unknown behavior: {active_behavior.behavior_name}")
            action_seq = list(spec.action_sequence)

        goal_id = f"goal_{uuid.uuid4().hex[:12]}"
        goal = MockGoal(goal_id, active_behavior, action_seq)
        self._goals[goal_id] = goal
        return goal_id

    def cancel_goal(self, goal_id: str) -> bool:
        """Cancel a running goal. Returns True if cancelled."""
        if goal_id in self._goals:
            goal = self._goals[goal_id]
            if goal.status == STATUS_RUNNING:
                goal.status = STATUS_CANCELED
                self._canceled.add(goal_id)
                self._completed[goal_id] = BehaviorFeedbackEvent(
                    behavior_id=goal.behavior.behavior_id,
                    behavior_name=goal.behavior.behavior_name,
                    status=STATUS_CANCELED,
                    result="canceled",
                    reason="Preempted by higher priority behavior",
                    reward=-0.1,
                    timestamp=time.time(),
                )
            return True
        return False

    def tick(self) -> None:
        """Advance all running goals by one simulation step."""
        now = time.time()
        for goal in list(self._goals.values()):
            if goal.status != STATUS_RUNNING:
                continue

            while goal.current_step < goal.total_steps:
                step = goal.action_sequence[goal.current_step]
                duration = step.get("duration", 1.0)
                elapsed = now - goal.step_start_time

                if elapsed >= duration:
                    goal.current_step += 1
                    goal.step_start_time = now
                else:
                    break

            if goal.current_step >= goal.total_steps:
                goal.status = STATUS_SUCCESS
                self._completed[goal.goal_id] = BehaviorFeedbackEvent(
                    behavior_id=goal.behavior.behavior_id,
                    behavior_name=goal.behavior.behavior_name,
                    status=STATUS_SUCCESS,
                    result="completed",
                    reason="All action steps finished",
                    reward=1.0,
                    emotion_delta={"satisfaction": 0.1},
                    need_delta={goal.behavior.need_type: -0.5},
                    timestamp=now,
                )

    def get_feedback(self, goal_id: str) -> Optional[ExecutorFeedback]:
        """Get current feedback for a goal."""
        if goal_id not in self._goals:
            return None
        goal = self._goals[goal_id]
        return ExecutorFeedback(
            behavior_id=goal.behavior.behavior_id,
            behavior_name=goal.behavior.behavior_name,
            status=goal.status,
            progress=goal.progress,
            safe_to_interrupt=goal.safe_to_interrupt,
            message=f"Step {goal.current_step + 1}/{goal.total_steps}: "
            f"{goal.current_action}",
        )

    def get_result(self, goal_id: str) -> Optional[BehaviorFeedbackEvent]:
        """Get completion result for a finished goal."""
        if goal_id in self._canceled:
            goal = self._goals.get(goal_id)
            if goal:
                return BehaviorFeedbackEvent(
                    behavior_id=goal.behavior.behavior_id,
                    behavior_name=goal.behavior.behavior_name,
                    status=STATUS_CANCELED,
                    result="canceled",
                    reason="Canceled",
                    reward=-0.1,
                    timestamp=time.time(),
                )
        return self._completed.get(goal_id)

    def remove_goal(self, goal_id: str) -> None:
        """Remove a completed goal from tracking."""
        self._goals.pop(goal_id, None)
        self._completed.pop(goal_id, None)
        self._canceled.discard(goal_id)

    def has_goal(self, goal_id: str) -> bool:
        """Check if a goal is still active."""
        return goal_id in self._goals
