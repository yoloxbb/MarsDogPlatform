"""Behavior Selector — priority-based behavior selection and preemption logic.

Selects the highest-priority candidate and evaluates whether it should
preempt the currently executing behavior.
"""

from __future__ import annotations

from typing import Optional

from bionic_dog_bt.arbitration import (
    check_interrupt_policy as _check_interrupt_policy,
    evaluate_preemption as _evaluate_preemption,
    candidate_priority_key,
)


def select_best_from_pool(candidates: list[dict], blackboard) -> Optional[dict]:
    """Select the best candidate from the pool.

    Used by standalone/mock mode where the full pool is available.
    For ROS2 mode, CandidatePool.select_best() is preferred.
    """
    if not candidates:
        return None

    for candidate in sorted(candidates, key=candidate_priority_key):
        if not blackboard.is_in_cooldown(candidate["behavior_name"]):
            return candidate
    return None


def evaluate_preemption(active_priority: int, active_value: float,
                        active_behavior_name: str,
                        current_priority: int, current_value: float,
                        current_interrupt_policy: str,
                        current_behavior_name: str,
                        executor_feedback, *,
                        active_params=None, current_params=None) -> tuple[bool, str]:
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
        active_params=active_params,
        current_params=current_params,
    )
