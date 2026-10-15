"""Blackboard: shared state for the behavior tree.

The blackboard is the central nervous system of the behavior tree.
It holds the currently active behavior candidate, the executing behavior,
executor feedback, cooldown state, and tick metadata.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from .datatypes import ActiveBehavior, ExecutorFeedback, BehaviorFeedbackEvent
from .constants import (
    GOAL_CANCEL_REQUESTED,
    GOAL_SENDING,
    GOAL_TERMINAL,
    STATUS_RUNNING,
    STATUS_SUCCESS,
)
from .emotion_module import EmotionModule
from .need_module import NeedModule
from .mock_perception_client import MockPerceptionClient
from .logger import get_logger

_log = get_logger("blackboard")


class Blackboard:
    """Central shared state for the behavior tree runtime."""

    def __init__(self, *, monotonic: Callable[[], float] | None = None,
                 wall_time: Callable[[], float] | None = None):
        self._monotonic = monotonic or time.monotonic
        self._wall_time = wall_time or time.time
        # ── Behavior State ───────────────────────────────────────────────────
        self.active_behavior: Optional[ActiveBehavior] = None  # Candidate from input provider
        self.current_behavior: Optional[ActiveBehavior] = None  # Currently executing behavior
        self.current_status: str = STATUS_SUCCESS  # Last known status of current behavior
        self.current_goal_id: Optional[str] = None  # Executor goal ID for current behavior
        self.goal_lifecycle: str = GOAL_TERMINAL
        self.cancel_reason: str = ""

        # ── Executor Feedback ────────────────────────────────────────────────
        self.executor_feedback: Optional[ExecutorFeedback] = None

        # ── Feedback Events ──────────────────────────────────────────────────
        self.last_feedback_event: Optional[BehaviorFeedbackEvent] = None

        # ── Cooldown Tracking ────────────────────────────────────────────────
        # Maps behavior_name → timestamp until which the behavior is cooled down
        self.cooldown_until: dict[str, float] = {}
        # Preserve wall timestamps for existing diagnostic consumers. Decisions
        # use an anchored monotonic deadline, independent of clock adjustment.
        self._cooldown_deadlines: dict[str, tuple[float, float]] = {}

        # ── Preemption Tracking ──────────────────────────────────────────────
        self.preemption_occurred: bool = False
        self.preemption_detail: str = ""

        # ── Tick Metadata ────────────────────────────────────────────────────
        self.tick_count: int = 0
        self.last_tick_time: float = 0.0

        # ── Timeout Tracking ─────────────────────────────────────────────────
        self.timeout_occurred: bool = False
        self.timeout_requested: bool = False
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
        self.goal_lifecycle = GOAL_SENDING
        self.cancel_reason = ""
        self.timeout_occurred = False
        self.timeout_requested = False
        self._behavior_start_time = self._monotonic()
        self._behavior_timeout = behavior.timeout_sec

    def clear_current_behavior(self) -> None:
        """Clear the current behavior (e.g., after completion)."""
        self.current_behavior = None
        self.current_goal_id = None
        self.current_status = STATUS_SUCCESS
        self.goal_lifecycle = GOAL_TERMINAL
        self.cancel_reason = ""
        self.timeout_requested = False
        self.executor_feedback = None

    def is_in_cooldown(self, behavior_name: str) -> bool:
        """Check if a behavior is currently in cooldown."""
        if behavior_name not in self.cooldown_until:
            return False
        wall_deadline = self.cooldown_until[behavior_name]
        anchored = self._cooldown_deadlines.get(behavior_name)
        if anchored is None or anchored[0] != wall_deadline:
            # Legacy callers can seed cooldown_until directly. Translate that
            # timestamp once; subsequent checks must not consult wall time.
            anchored = (wall_deadline, self._monotonic() + max(
                0.0, wall_deadline - self._wall_time()))
            self._cooldown_deadlines[behavior_name] = anchored
        return self._monotonic() < anchored[1]

    def set_cooldown(self, behavior_name: str, cooldown_sec: float) -> None:
        """Set cooldown for a behavior."""
        if cooldown_sec > 0:
            wall_deadline = self._wall_time() + cooldown_sec
            self.cooldown_until[behavior_name] = wall_deadline
            self._cooldown_deadlines[behavior_name] = (
                wall_deadline, self._monotonic() + cooldown_sec)

    def check_timeout(self) -> bool:
        """Check if the current behavior has timed out. Returns True if timeout occurred.

        Uses current_behavior.timeout_sec dynamically if available (allows test overrides),
        falling back to the cached _behavior_timeout set at start_behavior().
        """
        if self.current_status != STATUS_RUNNING:
            return False
        # Prefer dynamic timeout from current_behavior (allows runtime overrides)
        timeout = self._behavior_timeout
        if self.current_behavior is not None:
            timeout = self.current_behavior.timeout_sec
        if timeout <= 0:
            return False
        elapsed = self._monotonic() - self._behavior_start_time
        return elapsed >= timeout

    def request_cancel(self, reason: str, *, timeout: bool = False) -> None:
        """Record a cancel request without pretending the goal is terminal."""
        self.goal_lifecycle = GOAL_CANCEL_REQUESTED
        self.cancel_reason = str(reason)
        if timeout:
            self.timeout_occurred = True
            self.timeout_requested = True

    def mark_timeout(self) -> None:
        """Compatibility wrapper: timeout now requests cancellation only."""
        self.timeout_occurred = True
        self.timeout_requested = True
        self.goal_lifecycle = GOAL_CANCEL_REQUESTED
        self.cancel_reason = "timeout_requested"
        _log.warning("Timeout: %s elapsed=%.1fs timeout=%.1fs",
                     self.current_behavior.behavior_name if self.current_behavior else "?",
                     self._monotonic() - self._behavior_start_time,
                     self._behavior_timeout)
