"""Behavior tree action node: ExecuteActiveBehavior.

This is the core action node that handles:
- Sending goals to the executor
- Preemption logic (cross-level and same-level)
- Timeout detection
- Cooldown enforcement
- Feedback processing
"""

from __future__ import annotations

from typing import Protocol

from .behavior_tree_node import Node, Status
from .arbitration import evaluate_preemption
from .blackboard import Blackboard
from .datatypes import ExecutorFeedback, BehaviorFeedbackEvent
from .logger import get_logger, LogEvent
from .constants import (
    STATUS_RUNNING,
    STATUS_SUCCESS,
)

_log = get_logger("actions")


# ═══════════════════════════════════════════════════════════════════════════════
# Executor Interface (abstraction — swap implementation without touching BT)
# ═══════════════════════════════════════════════════════════════════════════════

class ExecutorInterface(Protocol):
    """Protocol that any executor must satisfy.

    Current implementation: MockActionExecutor (internal mock)
    Future: ActionClientAdapter wrapping ROS2 Action Client → /execute_behavior
    """

    def send_goal(self, active) -> str: ...
    def cancel_goal(self, goal_id: str) -> bool: ...
    def tick(self) -> None: ...
    def get_feedback(self, goal_id: str) -> ExecutorFeedback | None: ...
    def get_result(self, goal_id: str) -> BehaviorFeedbackEvent | None: ...
    def remove_goal(self, goal_id: str) -> None: ...
    def has_goal(self, goal_id: str) -> bool: ...


# ═══════════════════════════════════════════════════════════════════════════════

class ExecuteActiveBehavior(Node):
    """Action node that sends a behavior goal to the executor and monitors progress.

    Preemption rules:
    1. No current behavior → send immediately.
    2. Same behavior name + still RUNNING → keep waiting (no duplicate).
    3. New behavior has lower priority_level (higher priority) → try preempt.
    4. Same level: preempt only if new.value >= current.value + 15.
    5. New behavior has higher priority_level (lower priority) → no preempt.
    6. Respect interrupt_policy: immediate / safe_point / non_interruptible.
       - non_interruptible only yields to emergency_stop (Lv0).
    7. Timeout: cancel goal, return FAILURE.
    8. Cooldown: don't start if behavior is in cooldown.
    """

    def __init__(self, name: str, blackboard: Blackboard, executor: ExecutorInterface):
        super().__init__(name)
        self.blackboard = blackboard
        self.executor = executor
        self._sent_behavior_id: str | None = None

    def initialise(self) -> None:
        super().initialise()
        self._sent_behavior_id = None

    def update(self) -> Status:
        bb = self.blackboard
        ex = self.executor

        # ── Tick the executor to advance simulation ──────────────────────────
        ex.tick()

        # ── Check timeout on current behavior ────────────────────────────────
        if bb.current_behavior is not None and bb.current_status == STATUS_RUNNING:
            if bb.check_timeout():
                timed_out = bb.current_behavior
                bb.mark_timeout()
                if bb.current_goal_id:
                    ex.cancel_goal(bb.current_goal_id)
                bb.last_feedback_event = BehaviorFeedbackEvent(
                    behavior_id=timed_out.behavior_id,
                    behavior_name=timed_out.behavior_name,
                    status="TIMEOUT",
                    result="timeout",
                    reason=(
                        f"Behavior exceeded timeout "
                        f"({timed_out.timeout_sec:.1f}s)"
                    ),
                )
                _log.event(LogEvent.BEHAVIOR_TIMEOUT,
                           behavior_name=timed_out.behavior_name,
                           timeout_sec=timed_out.timeout_sec)
                return Status.FAILURE

        # ── Check result of completed goal ───────────────────────────────────
        if bb.current_goal_id and bb.current_status == STATUS_RUNNING:
            result = ex.get_result(bb.current_goal_id)
            if result is not None:
                bb.last_feedback_event = result
                bb.current_status = result.status

                # Set cooldown
                if bb.current_behavior:
                    bb.set_cooldown(bb.current_behavior.behavior_name, bb.current_behavior.cooldown_sec)

                _log.event(LogEvent.BEHAVIOR_COMPLETE,
                           behavior_name=result.behavior_name,
                           status=result.status, reward=result.reward)
                ex.remove_goal(bb.current_goal_id)

                if result.status == STATUS_SUCCESS:
                    return Status.SUCCESS
                else:
                    return Status.FAILURE

        # ── No new active behavior → keep ticking current ────────────────────
        if bb.active_behavior is None:
            if bb.current_behavior is not None and bb.current_status == STATUS_RUNNING:
                # Update executor feedback
                if bb.current_goal_id:
                    bb.executor_feedback = ex.get_feedback(bb.current_goal_id)
                return Status.RUNNING
            return Status.FAILURE

        # ── We have an active_behavior that hasn't been sent yet ─────────────
        active = bb.active_behavior

        # Skip if already sent this behavior_id
        if active.behavior_id == self._sent_behavior_id:
            if bb.current_status == STATUS_RUNNING:
                return Status.RUNNING
            return Status.FAILURE

        # ── Check cooldown ───────────────────────────────────────────────────
        if bb.is_in_cooldown(active.behavior_name):
            _log.event(LogEvent.BEHAVIOR_COOLDOWN,
                       behavior_name=active.behavior_name)
            bb.active_behavior = None  # Discard
            return Status.FAILURE

        # ── Case 1: No current behavior → send immediately ───────────────────
        if bb.current_behavior is None or bb.current_status != STATUS_RUNNING:
            self._send_goal(active, bb)
            self._sent_behavior_id = active.behavior_id
            return Status.RUNNING

        # ── Case 2: Same behavior, still running → skip duplicate ────────────
        current = bb.current_behavior
        if (active.behavior_name == current.behavior_name
                and bb.current_status == STATUS_RUNNING):
            self.log(f"SAME: {active.behavior_name} already running, skipping duplicate")
            self._sent_behavior_id = active.behavior_id
            bb.active_behavior = None
            return Status.RUNNING

        # ── Decide whether to preempt ────────────────────────────────────────
        can_preempt, reason = self._evaluate_preemption(active, current, bb)
        if not can_preempt:
            _log.event(LogEvent.PREEMPT_BLOCKED, reason=reason,
                       active=active.behavior_name, current=current.behavior_name)
            bb.active_behavior = None  # Discard candidate
            bb.preemption_occurred = False
            bb.preemption_detail = reason
            if bb.current_status == STATUS_RUNNING:
                if bb.current_goal_id:
                    bb.executor_feedback = ex.get_feedback(bb.current_goal_id)
                return Status.RUNNING
            return Status.FAILURE

        # ── Execute preemption ───────────────────────────────────────────────
        _log.event(LogEvent.PREEMPT, reason=reason,
                   from_behavior=current.behavior_name,
                   to_behavior=active.behavior_name)
        bb.preemption_occurred = True
        bb.preemption_detail = reason

        bb.last_feedback_event = BehaviorFeedbackEvent(
            behavior_id=current.behavior_id,
            behavior_name=current.behavior_name,
            status="CANCELED",
            result="canceled",
            reason=f"Preempted by {active.behavior_name}: {reason}",
            reward=-0.1,
        )
        if bb.current_goal_id:
            ex.cancel_goal(bb.current_goal_id)

        self._send_goal(active, bb)
        self._sent_behavior_id = active.behavior_id
        return Status.RUNNING

    def _send_goal(self, active, bb: Blackboard) -> None:
        """Send a goal to the executor and update blackboard.

        Emotion candidates normally arrive with a visual-service-resolved
        interaction mode. Older/unresolved callers retain a latest-scene
        compatibility check here.
        """
        # ── Check person presence for emotion-triggered behaviors ────────────
        source = active.params.get("source", "")
        is_direct_audio = source == "audio_direct"
        if (
            active.need_type == "emotional"
            and not is_direct_audio
            and not active.params.get("visual_resolved")
        ):
            person = bb.perception_client.check_person()
            if person["present"]:
                active.params["interactive"] = True
                active.params["interaction_mode"] = "interactive"
                active.params["target_identity"] = person["identity"]
                active.params["target"] = {
                    "target_type": "human",
                    "target_id": person["identity"],
                }
                self.log(f"check_person: INTERACTIVE (identity={person['identity']})")
            else:
                active.params["interactive"] = False
                active.params["interaction_mode"] = "solo"
                active.params.pop("target_identity", None)
                active.params["target"] = None
                self.log(f"check_person: SOLO (no person present)")

        goal_id = self.executor.send_goal(active)
        bb.start_behavior(active, goal_id)
        bb.executor_feedback = self.executor.get_feedback(goal_id)
        bb.active_behavior = None  # Consumed
        mode = "interactive" if active.params.get("interactive") else "solo"
        _log.event(LogEvent.BEHAVIOR_START,
                   behavior_name=active.behavior_name,
                   priority_level=active.priority_level,
                   mode=mode, goal_id=goal_id)

    def _evaluate_preemption(self, active, current, bb: Blackboard) -> tuple[bool, str]:
        """Evaluate whether active should preempt current."""
        return evaluate_preemption(
            active.priority_level,
            active.value,
            active.behavior_name,
            current.priority_level,
            current.value,
            current.interrupt_policy,
            bb.executor_feedback,
        )
