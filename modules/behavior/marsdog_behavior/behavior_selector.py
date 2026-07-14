"""Behavior Selector — priority-based behavior selection and preemption logic.

Selects the highest-priority candidate and evaluates whether it should
preempt the currently executing behavior.
"""

from __future__ import annotations

from typing import Optional

from bionic_dog_bt.constants import (
    SAME_LEVEL_PREEMPTION_DELTA,
    INTERRUPT_IMMEDIATE,
    INTERRUPT_SAFE_POINT,
    INTERRUPT_NON_INTERRUPTIBLE,
    STATUS_RUNNING,
)
from bionic_dog_bt.logger import get_logger, LogEvent

_log = get_logger("selector")


def select_best_from_pool(candidates: list[dict], blackboard) -> Optional[dict]:
    """Select the best candidate from the pool.

    Used by standalone/mock mode where the full pool is available.
    For ROS2 mode, CandidatePool.select_best() is preferred.
    """
    if not candidates:
        return None

    sorted_cands = sorted(candidates, key=lambda c: (c["priority_level"], -c["value"]))
    best = sorted_cands[0]

    for cand in sorted_cands:
        if not blackboard.is_in_cooldown(cand["behavior_name"]):
            best = cand
            break

    return best


def evaluate_preemption(active_priority: int, active_value: float,
                        active_behavior_name: str,
                        current_priority: int, current_value: float,
                        current_interrupt_policy: str,
                        current_behavior_name: str,
                        executor_feedback) -> tuple[bool, str]:
    """Evaluate whether the active behavior should preempt the current one.

    Args:
        active_priority: priority_level of new candidate
        active_value: value of new candidate
        active_behavior_name: name of new candidate
        current_priority: priority_level of running behavior
        current_value: value of running behavior
        current_interrupt_policy: interrupt_policy of running behavior
        current_behavior_name: name of running behavior
        executor_feedback: current ExecutorFeedback (for safe_to_interrupt check)

    Returns:
        (can_preempt: bool, reason: str)

    Preemption rules:
    1. Lower priority_level (more urgent) + immediate → preempt
    2. Lower priority_level + safe_point → wait for safe_to_interrupt
    3. Lower priority_level + non_interruptible → no preempt (except emergency_stop Lv0)
    4. Same level + delta >= 15 → preempt
    5. Same level + delta < 15 → no preempt (jitter prevention)
    6. Higher priority_level → no preempt
    """
    # ── New behavior has higher priority (lower level number) ─────────
    if active_priority < current_priority:
        return _check_interrupt_policy(
            active_behavior_name, active_priority,
            current_interrupt_policy, executor_feedback)

    # ── Same priority level ──────────────────────────────────────────
    if active_priority == current_priority:
        delta = active_value - current_value
        if delta >= SAME_LEVEL_PREEMPTION_DELTA:
            return _check_interrupt_policy(
                active_behavior_name, active_priority,
                current_interrupt_policy, executor_feedback)
        else:
            return (False,
                    f"Same-level delta={delta:.1f} < {SAME_LEVEL_PREEMPTION_DELTA} "
                    f"(new={active_value:.0f} vs cur={current_value:.0f})")

    # ── New behavior has lower priority ──────────────────────────────
    return (False,
            f"Lower priority: Lv{active_priority} > Lv{current_priority}")


def _check_interrupt_policy(active_behavior_name: str, active_priority: int,
                            current_policy: str, executor_feedback) -> tuple[bool, str]:
    """Check if the new behavior can interrupt based on the current policy."""
    # emergency_stop at Lv0 always wins
    if active_behavior_name == "emergency_stop" and active_priority == 0:
        return (True, "emergency_stop overrides all")

    if current_policy == INTERRUPT_IMMEDIATE:
        return (True, "immediate preempt")

    elif current_policy == INTERRUPT_SAFE_POINT:
        if executor_feedback is not None and executor_feedback.safe_to_interrupt:
            return (True, "safe_point reached")
        else:
            return (False, "safe_point not reached, waiting")

    elif current_policy == INTERRUPT_NON_INTERRUPTIBLE:
        return (False, "current behavior is non_interruptible")

    return (False, f"unknown policy: {current_policy}")
