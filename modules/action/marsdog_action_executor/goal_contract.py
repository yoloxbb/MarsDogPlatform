"""Goal JSON/timeout and terminal-truth interpretation; no ROS runtime dependency."""
from __future__ import annotations
import json
import math
import time
from .models import BehaviorGoal
from .execution_context import parse_params_json_object

def _normalise_goal_timeout(value: object) -> float:
    """Return a finite budget; zero means no outer deadline."""
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(timeout):
        return 0.0
    return max(0.0, timeout)

def _outer_runtime_deadline(started: float, timeout_sec: float) -> float | None:
    """Keep the outer Goal alive when its requested budget is non-positive."""
    return started + timeout_sec if timeout_sec > 0.0 else None

def _navigation_cancel_won(cancel_requested: bool, waypoint_outcome) -> bool:
    """Return whether a cancel request is confirmed by the navigation truth.

    For fixed waypoint navigation, an acknowledged cancel is not enough.  The
    original task must reach INTERRUPTED.  A competing SUCCEEDED or FAILED
    terminal remains authoritative.  ``None`` is retained for the direct Nav2
    path and for cancellation before a waypoint task was dispatched.
    """
    if not cancel_requested:
        return False
    if waypoint_outcome is None:
        return True
    return bool(
        waypoint_outcome.terminal_confirmed
        and waypoint_outcome.state == "INTERRUPTED"
    )

def _debug_goal_from_request(
    goal_request,
    *,
    timestamp: float | None = None,
) -> tuple[BehaviorGoal, bool]:
    """Build a debug Goal without trusting the ROS ``params_json`` field.

    The boolean reports whether the field was a valid JSON object.  Invalid
    input is represented as an empty parameter mapping so even a direct test
    harness call to ``_on_accepted`` cannot raise while publishing debug data.
    The execution path still parses the original field and returns
    ``invalid_params``.
    """
    params = parse_params_json_object(
        getattr(goal_request, "params_json", "{}")
    )
    params_valid = params is not None
    goal_id = getattr(goal_request, "goal_id", "")
    return (
        BehaviorGoal(
            goal_id=goal_id,
            behavior_id=getattr(goal_request, "behavior_id", goal_id),
            behavior_name=getattr(goal_request, "behavior_name", ""),
            priority_level=getattr(goal_request, "priority_level", 0),
            params=dict(params) if params_valid else {},
            timeout_sec=getattr(goal_request, "timeout_sec", 60.0),
            timestamp=time.time() if timestamp is None else timestamp,
        ),
        params_valid,
    )
