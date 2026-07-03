"""Blackboard: shared state for the behavior tree.

The blackboard is the central nervous system of the behavior tree.
It holds the currently active behavior candidate, the executing behavior,
executor feedback, cooldown state, and tick metadata.
"""

from __future__ import annotations

import time
from typing import Optional

from .datatypes import ActiveBehavior, ExecutorFeedback, BehaviorFeedbackEvent
from .constants import STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILURE
from .emotion_module import EmotionModule
from .need_module import NeedModule
from .mock_perception_client import MockPerceptionClient


class Blackboard:
    """Central shared state for the behavior tree runtime."""

    def __init__(self):
        # ── Behavior State ───────────────────────────────────────────────────
        self.active_behavior: Optional[ActiveBehavior] = None  # Candidate from input provider
        self.current_behavior: Optional[ActiveBehavior] = None  # Currently executing behavior
        self.current_status: str = STATUS_SUCCESS  # Last known status of current behavior
        self.current_goal_id: Optional[str] = None  # Executor goal ID for current behavior

        # ── Executor Feedback ────────────────────────────────────────────────
        self.executor_feedback: Optional[ExecutorFeedback] = None

        # ── Feedback Events ──────────────────────────────────────────────────
        self.last_feedback_event: Optional[BehaviorFeedbackEvent] = None

        # ── Cooldown Tracking ────────────────────────────────────────────────
        # Maps behavior_name → timestamp until which the behavior is cooled down
        self.cooldown_until: dict[str, float] = {}

        # ── Preemption Tracking ──────────────────────────────────────────────
        self.preemption_occurred: bool = False
        self.preemption_detail: str = ""

        # ── Tick Metadata ────────────────────────────────────────────────────
        self.tick_count: int = 0
        self.last_tick_time: float = 0.0

        # ── Timeout Tracking ─────────────────────────────────────────────────
        self.timeout_occurred: bool = False
        self._behavior_start_time: float = 0.0
        self._behavior_timeout: float = 0.0

        # ── Emotion Module ───────────────────────────────────────────────────
        self.emotion_module: EmotionModule = EmotionModule()

        # ── Need Module ──────────────────────────────────────────────────────
        self.need_module: NeedModule = NeedModule()

        # ── Perception Client ────────────────────────────────────────────────
        self.perception_client: MockPerceptionClient = MockPerceptionClient()

    def tick_emotions(self) -> None:
        """Apply emotion decay for this tick cycle."""
        self.emotion_module.tick()

    def tick_needs(self) -> None:
        """Recompute need levels for this tick cycle."""
        self.need_module.tick()

    def set_active_behavior(self, behavior: ActiveBehavior) -> None:
        """Set a new candidate behavior from the input provider."""
        self.active_behavior = behavior
        self.preemption_occurred = False
        self.preemption_detail = ""
        self.timeout_occurred = False

    def start_behavior(self, behavior: ActiveBehavior, goal_id: str) -> None:
        """Mark a behavior as started (goal sent to executor)."""
        self.current_behavior = behavior
        self.current_goal_id = goal_id
        self.current_status = STATUS_RUNNING
        self._behavior_start_time = time.time()
        self._behavior_timeout = behavior.timeout_sec

    def clear_current_behavior(self) -> None:
        """Clear the current behavior (e.g., after completion)."""
        self.current_behavior = None
        self.current_goal_id = None
        self.current_status = STATUS_SUCCESS
        self.executor_feedback = None

    def is_in_cooldown(self, behavior_name: str) -> bool:
        """Check if a behavior is currently in cooldown."""
        if behavior_name not in self.cooldown_until:
            return False
        return time.time() < self.cooldown_until[behavior_name]

    def set_cooldown(self, behavior_name: str, cooldown_sec: float) -> None:
        """Set cooldown for a behavior."""
        if cooldown_sec > 0:
            self.cooldown_until[behavior_name] = time.time() + cooldown_sec

    def check_timeout(self) -> bool:
        """Check if the current behavior has timed out. Returns True if timeout occurred.

        Uses current_behavior.timeout_sec dynamically if available (allows test overrides),
        falling back to the cached _behavior_timeout set at start_behavior().
        """
        if self.current_status != STATUS_RUNNING:
            return False
        # Prefer dynamic timeout from current_behavior (allows runtime overrides)
        timeout = self._behavior_timeout
        if self.current_behavior is not None and self.current_behavior.timeout_sec > 0:
            timeout = self.current_behavior.timeout_sec
        if timeout <= 0:
            return False
        elapsed = time.time() - self._behavior_start_time
        return elapsed >= timeout

    def mark_timeout(self) -> None:
        """Mark that a timeout has occurred."""
        self.timeout_occurred = True
        self.current_status = STATUS_FAILURE
