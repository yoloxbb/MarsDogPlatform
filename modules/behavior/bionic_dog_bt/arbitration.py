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


def priority_key(
    priority_level: int,
    params: dict | None = None,
    *,
    sub_priority: int = 0,
) -> tuple[int, int, int, int]:
    """Order event meaning before sensor source, then behavior detail."""
    values = params if isinstance(params, dict) else {}
    return (
        int(priority_level),
        int(values.get("semantic_rank", 3)),
        int(values.get("modality_rank", 3)),
        int(values.get("behavior_rank", values.get("sub_priority", sub_priority))),
    )


def evaluate_preemption(
    active_priority: int,
    active_value: float,
    active_behavior_name: str,
    current_priority: int,
    current_value: float,
    current_interrupt_policy: str,
    executor_feedback,
    active_params: dict | None = None,
    current_params: dict | None = None,
) -> tuple[bool, str]:
    """Return whether a new candidate may interrupt the running behavior."""
    active_params = active_params if isinstance(active_params, dict) else {}
    current_params = current_params if isinstance(current_params, dict) else {}
    # Accepted voice commands replace long voice Goals regardless of ASR
    # confidence or behavior rank.  Hardware wake also replaces follow/play.
    # The old Goal retains ownership until safe feedback permits cancellation
    # and its real Result arrives; check_interrupt_policy enforces safety.
    long_voice_goal = (
        current_params.get("completion_policy") == "until_preempted"
        and current_params.get("source") == "audio_direct"
        and str(current_params.get("trigger_event", "")).startswith(
            "EVT_VOICE_COMMAND_"
        )
    )
    if long_voice_goal and active_params.get("source") == "audio_direct":
        active_event = str(active_params.get("trigger_event", ""))
        current_event = str(current_params.get("trigger_event", ""))
        if active_event.startswith("EVT_VOICE_COMMAND_"):
            allowed, policy_reason = check_interrupt_policy(
                active_behavior_name,
                active_priority,
                current_interrupt_policy,
                executor_feedback,
            )
            return (
                allowed,
                f"voice command replaces long voice goal: {policy_reason}",
            )
        if (
            active_event == "EVT_VOICE_WAKEUP"
            and active_behavior_name == "respond_owner_call"
            and current_event in {
                "EVT_VOICE_COMMAND_FOLLOW",
                "EVT_VOICE_COMMAND_PLAY_ALONE",
            }
        ):
            allowed, policy_reason = check_interrupt_policy(
                active_behavior_name,
                active_priority,
                current_interrupt_policy,
                executor_feedback,
            )
            return (
                allowed,
                f"hardware wake replaces long voice goal: {policy_reason}",
            )

    active_key = priority_key(active_priority, active_params)
    current_key = priority_key(current_priority, current_params)
    if active_key < current_key:
        return check_interrupt_policy(
            active_behavior_name,
            active_priority,
            current_interrupt_policy,
            executor_feedback,
        )

    if active_key == current_key:
        active_interaction = str(
            active_params.get("interaction_id", "")
        ).strip()
        current_interaction = str(
            current_params.get("interaction_id", "")
        ).strip()
        if active_interaction and active_interaction == current_interaction:
            try:
                active_rank = int(active_params["session_preempt_rank"])
                current_rank = int(current_params["session_preempt_rank"])
            except (KeyError, TypeError, ValueError):
                active_rank = current_rank = 0
            if active_rank < current_rank:
                allowed, policy_reason = check_interrupt_policy(
                    active_behavior_name,
                    active_priority,
                    current_interrupt_policy,
                    executor_feedback,
                )
                return (
                    allowed,
                    "same-session rank %d < %d: %s"
                    % (active_rank, current_rank, policy_reason),
                )

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

    return False, f"Lower priority key: {active_key} > {current_key}"


def check_interrupt_policy(
    active_behavior_name: str,
    active_priority: int,
    current_policy: str,
    executor_feedback,
) -> tuple[bool, str]:
    """Apply the currently running behavior's interrupt policy."""
    if active_behavior_name == "emergency_stop" and active_priority == 0:
        return True, "emergency_stop overrides all"

    if executor_feedback is None:
        return False, "latest feedback unavailable"

    feedback_status = str(
        getattr(executor_feedback, "status", "")
    ).upper()
    if feedback_status in {"DISPATCHED", "RECOVERY_REQUIRED"}:
        return False, f"feedback status {feedback_status} is not interruptible"

    if not bool(getattr(executor_feedback, "safe_to_interrupt", False)):
        return False, "latest feedback is not safe_to_interrupt"

    if current_policy == INTERRUPT_IMMEDIATE:
        return True, "immediate preempt at safe feedback"

    if current_policy == INTERRUPT_SAFE_POINT:
        return True, "safe_point reached"

    if current_policy == INTERRUPT_NON_INTERRUPTIBLE:
        return False, "current behavior is non_interruptible"

    return False, f"unknown policy: {current_policy}"
