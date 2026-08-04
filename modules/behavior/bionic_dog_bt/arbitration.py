"""Pure priority and preemption rules for behavior arbitration.

Keeping these rules independent from tree nodes and ROS2 adapters gives every
runtime path one authoritative implementation.
"""

from __future__ import annotations

from .constants import (
    INTERRUPT_IMMEDIATE,
    INTERRUPT_NON_INTERRUPTIBLE,
    INTERRUPT_SAFE_POINT,
    SAME_LEVEL_PREEMPTION_DELTA,
)


def evaluate_preemption(
    active_priority: int,
    active_value: float,
    active_behavior_name: str,
    current_priority: int,
    current_value: float,
    current_interrupt_policy: str,
    executor_feedback,
) -> tuple[bool, str]:
    """Return whether a new candidate may interrupt the running behavior."""
    if active_priority < current_priority:
        return check_interrupt_policy(
            active_behavior_name,
            active_priority,
            current_interrupt_policy,
            executor_feedback,
        )

    if active_priority == current_priority:
        delta = active_value - current_value
        if delta >= SAME_LEVEL_PREEMPTION_DELTA:
            return check_interrupt_policy(
                active_behavior_name,
                active_priority,
                current_interrupt_policy,
                executor_feedback,
            )
        return (
            False,
            f"Same-level delta={delta:.1f} < {SAME_LEVEL_PREEMPTION_DELTA} "
            f"(new={active_value:.0f} vs cur={current_value:.0f})",
        )

    return (
        False,
        f"Lower priority: Lv{active_priority} > Lv{current_priority}",
    )


def check_interrupt_policy(
    active_behavior_name: str,
    active_priority: int,
    current_policy: str,
    executor_feedback,
) -> tuple[bool, str]:
    """Apply the currently running behavior's interrupt policy."""
    if active_behavior_name == "emergency_stop" and active_priority == 0:
        return True, "emergency_stop overrides all"

    if current_policy == INTERRUPT_IMMEDIATE:
        return True, "immediate preempt"

    if current_policy == INTERRUPT_SAFE_POINT:
        if executor_feedback is not None and executor_feedback.safe_to_interrupt:
            return True, "safe_point reached"
        return False, "safe_point not reached, waiting"

    if current_policy == INTERRUPT_NON_INTERRUPTIBLE:
        return False, "current behavior is non_interruptible"

    return False, f"unknown policy: {current_policy}"
