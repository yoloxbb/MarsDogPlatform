"""Behavior tree action node: ExecuteActiveBehavior.

This is the core action node that handles:
- Sending goals to the executor
- Preemption logic (cross-level and same-level)
- Timeout detection
- Cooldown enforcement
- Feedback processing
"""

from __future__ import annotations

import time

from .behavior_tree_node import Node, Status
from .blackboard import Blackboard
from .mock_action_executor import MockActionExecutor
from .constants import (
    STATUS_RUNNING,
    STATUS_SUCCESS,
    STATUS_FAILURE,
    STATUS_CANCELED,
    SAME_LEVEL_PREEMPTION_DELTA,
    INTERRUPT_IMMEDIATE,
    INTERRUPT_SAFE_POINT,
    INTERRUPT_NON_INTERRUPTIBLE,
    PRIORITY_LEVELS,
)


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

    def __init__(self, name: str, blackboard: Blackboard, executor: MockActionExecutor):
        super().__init__(name)
        self.blackboard = blackboard
        self.executor = executor
        self._sent_behavior_id: str | None = None  # Track which active_behavior we already processed

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
                bb.mark_timeout()
                if bb.current_goal_id:
                    ex.cancel_goal(bb.current_goal_id)
                self.log(f"TIMEOUT: {bb.current_behavior.behavior_name} "
                         f"(timeout={bb.current_behavior.timeout_sec}s)")
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

                self.log(f"RESULT: {result.behavior_name} → {result.status}")
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
            self.log(f"COOLDOWN: {active.behavior_name} on cooldown "
                     f"until {bb.cooldown_until.get(active.behavior_name, 0):.1f}")
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
            self.log(f"NO PREEMPT: {reason} | active={active.behavior_name}(Lv{active.priority_level}) "
                     f"vs current={current.behavior_name}(Lv{current.priority_level})")
            bb.active_behavior = None  # Discard candidate
            bb.preemption_occurred = False
            bb.preemption_detail = reason
            if bb.current_status == STATUS_RUNNING:
                if bb.current_goal_id:
                    bb.executor_feedback = ex.get_feedback(bb.current_goal_id)
                return Status.RUNNING
            return Status.FAILURE

        # ── Execute preemption ───────────────────────────────────────────────
        self.log(f"PREEMPT: {current.behavior_name} → {active.behavior_name} | {reason}")
        bb.preemption_occurred = True
        bb.preemption_detail = reason

        if bb.current_goal_id:
            ex.cancel_goal(bb.current_goal_id)

        self._send_goal(active, bb)
        self._sent_behavior_id = active.behavior_id
        return Status.RUNNING

    def _send_goal(self, active, bb: Blackboard) -> None:
        """Send a goal to the executor and update blackboard.

        For emotion-triggered behaviors, calls check_person() to determine
        interactive vs solo mode. This simulates the /perception/perception_task
        service call that happens at execution time.
        """
        # ── Check person presence for emotion-triggered behaviors ────────────
        if active.need_type == "emotional":
            person = bb.perception_client.check_person()
            if person["present"] and "source" not in active.params:
                # Not already set by a voice command — discover at execution time
                active.params["interactive"] = True
                active.params["target_identity"] = person["identity"]
                self.log(f"check_person: INTERACTIVE (identity={person['identity']})")
            elif "source" not in active.params:
                active.params["interactive"] = False
                self.log(f"check_person: SOLO (no person present)")

        goal_id = self.executor.send_goal(active)
        bb.start_behavior(active, goal_id)
        bb.executor_feedback = self.executor.get_feedback(goal_id)
        bb.active_behavior = None  # Consumed
        mode = "interactive" if active.params.get("interactive") else "solo"
        self.log(f"SEND: {active.behavior_name} Lv{active.priority_level} "
                 f"value={active.value} mode={mode} goal={goal_id}")

    def _evaluate_preemption(self, active, current, bb: Blackboard) -> tuple[bool, str]:
        """Evaluate whether active should preempt current.

        Returns (can_preempt: bool, reason: str).
        """
        # ── New behavior priority is higher (lower level number) ─────────────
        if active.priority_level < current.priority_level:
            return self._check_interrupt_policy(active, current)

        # ── Same priority level ──────────────────────────────────────────────
        if active.priority_level == current.priority_level:
            delta = active.value - current.value
            if delta >= SAME_LEVEL_PREEMPTION_DELTA:
                return self._check_interrupt_policy(active, current)
            else:
                return (False,
                        f"Same-level delta={delta:.1f} < {SAME_LEVEL_PREEMPTION_DELTA} "
                        f"(new={active.value:.0f} vs cur={current.value:.0f})")

        # ── New behavior priority is lower (higher level number) ─────────────
        return (False,
                f"Lower priority: Lv{active.priority_level} > Lv{current.priority_level}")

    def _check_interrupt_policy(self, active, current) -> tuple[bool, str]:
        """Check if active can interrupt current based on interrupt_policy."""
        policy = current.interrupt_policy

        # emergency_stop at Lv0 always wins, regardless of policy
        if active.behavior_name == "emergency_stop" and active.priority_level == 0:
            return (True, "emergency_stop overrides all")

        if policy == INTERRUPT_IMMEDIATE:
            return (True, "immediate preempt")

        elif policy == INTERRUPT_SAFE_POINT:
            fb = self.blackboard.executor_feedback
            if fb is not None and fb.safe_to_interrupt:
                return (True, "safe_point reached")
            else:
                return (False, "safe_point not reached, waiting")

        elif policy == INTERRUPT_NON_INTERRUPTIBLE:
            return (False, "current behavior is non_interruptible")

        return (False, f"unknown policy: {policy}")
