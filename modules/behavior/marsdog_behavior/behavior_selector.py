"""Behavior Selector — priority-based behavior selection and preemption logic.

Selects the highest-priority candidate and evaluates whether it should
preempt the currently executing behavior.
"""

from __future__ import annotations

from typing import Optional

from bionic_dog_bt.arbitration import (
    check_interrupt_policy as _check_interrupt_policy,
    evaluate_preemption as _evaluate_preemption,
)


def select_best_from_pool(candidates: list[dict], blackboard) -> Optional[dict]:
    """Select the best candidate from the pool.

    Used by standalone/mock mode where the full pool is available.
    For ROS2 mode, CandidatePool.select_best() is preferred.
    """
    if not candidates:
        return None

    sorted_cands = sorted(candidates, key=lambda c: (
        c["priority_level"],
        c.get("sub_priority", 0),
        c.get("emotion_priority", 50),
        -c["value"],
    ))
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
    """Backward-compatible facade for the core arbitration policy.

    ``current_behavior_name`` is retained in the public signature for existing
    callers; the policy only needs the current priority, value, and interrupt
    policy.
    """
    return _evaluate_preemption(
        active_priority,
        active_value,
        active_behavior_name,
        current_priority,
        current_value,
        current_interrupt_policy,
        executor_feedback,
    )
