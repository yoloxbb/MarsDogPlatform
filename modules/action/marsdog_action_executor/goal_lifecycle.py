"""Goal reservation, cancellation requests and leases over existing executor ports.

Cancel acknowledgement never releases ownership; Result cleanup owns that step.
Enums are injected by the ROS shell, allowing this policy to run without ROS.
"""
from __future__ import annotations
import json
import math
import time
from .execution_context import parse_params_json_object
from .goal_contract import _debug_goal_from_request


def on_goal(self, goal_request, *, goal_response):
    """Accept only exact names from behavior_tree_actions.yaml.

    Priority-based preemption: a higher-priority goal interrupts
    the currently-running behavior (voice commands > emotions).
    """
    name = goal_request.behavior_name
    gid = goal_request.goal_id
    new_priority = int(getattr(goal_request, "priority_level", 0))

    params = parse_params_json_object(
        getattr(goal_request, "params_json", "{}")
    )
    if params is None:
        self.get_logger().warning(
            f"Rejected goal: invalid_params goal_id={gid} -> {name}; "
            "params_json must be a valid JSON object"
        )
        return goal_response.REJECT
    try:
        timeout_value = float(getattr(goal_request, "timeout_sec", 60.0))
    except (TypeError, ValueError):
        return goal_response.REJECT
    if not math.isfinite(timeout_value):
        return goal_response.REJECT

    if (name != "emergency_stop" and any(
        getattr(adapter, "recovery_required", False)
        for adapter in (
            getattr(self, "_uwb_roam_adapter", None),
            self._uwb_follow_adapter,
            getattr(self, "_person_nav_approach_adapter", None),
        )
    )):
        self.get_logger().error("Rejected goal: controller terminal unknown; recovery required")
        return goal_response.REJECT

    if name in self._acceptable_behaviors:
        if name != "emergency_stop":
            with self._goal_reservation_lock:
                busy = self._reserved_goal_id is not None
            if busy or self._behavior_execution_lock.locked():
                # The previous Result, not CancelGoal acceptance, is
                # the only point where motion ownership changes.
                self.get_logger().warning(
                    f"Rejected goal while previous Result is pending: {gid} -> {name}"
                )
                return goal_response.REJECT
            with self._goal_reservation_lock:
                if self._reserved_goal_id is not None:
                    return goal_response.REJECT
                self._reserved_goal_id = str(gid)
        if name == "emergency_stop":
            self._interrupt.request_cancel()
            self._behavior_sounds.stop()
            if getattr(self, "_uwb_roam_adapter", None) is not None:
                self._uwb_roam_adapter.emergency_stop()
            if self._uwb_follow_adapter is not None:
                self._uwb_follow_adapter.emergency_stop()
            if self._wake_orientation_adapter is not None:
                self._wake_orientation_adapter.emergency_stop()
            if self._target_approach_adapter is not None:
                self._target_approach_adapter.emergency_stop()
            if self._person_nav_approach_adapter is not None:
                self._person_nav_approach_adapter.emergency_stop()
            if self._visual_target_approach_adapter is not None:
                self._visual_target_approach_adapter.emergency_stop()
            if self._mobility_adapter is not None:
                self._mobility_adapter.emergency_stop()
            if self._chassis_backend is not None:
                self._chassis_backend.emergency_stop()
            self._stationary_expression_adapter.emergency_stop()
        self.get_logger().info(
            f"Accepted goal: {gid} -> {name} "
            f"(priority={new_priority})"
        )
        return goal_response.ACCEPT

    from difflib import get_close_matches
    close = get_close_matches(
        name,
        sorted(self._acceptable_behaviors),
        n=3,
        cutoff=0.5,
    )
    hint = f" Did you mean: {close}?" if close else ""
    self.get_logger().warning(
        f"Rejected goal: unsupported_behavior={name!r} "
        f"goal_id={gid}. "
        f"Accepted: {len(self._acceptable_behaviors)} strict "
        f"behavior-tree names.{hint}"
    )
    return goal_response.REJECT


def on_cancel(self, goal_handle, *, cancel_response):
    """Accept all cancel requests."""
    self.get_logger().info(
        f"Cancel requested: {goal_handle.request.goal_id}"
    )
    if (self._long_goal_id is not None
            and str(goal_handle.request.goal_id) != self._long_goal_id):
        return cancel_response.REJECT
    self._interrupt.request_cancel()
    self._behavior_sounds.stop()
    if (self._long_goal_id is not None
            and goal_handle.request.behavior_name == "play_alone"
            and getattr(self, "_uwb_roam_adapter", None) is not None):
        self._uwb_roam_adapter.cancel_step()
    if (
        self._uwb_follow_adapter is not None
        and goal_handle.request.behavior_name == "follow_owner"
    ):
        if self._long_goal_id is not None:
            self._uwb_follow_adapter.request_cancel()
        else:
            self._uwb_follow_adapter.cancel_step()
    if self._wake_orientation_adapter is not None:
        self._wake_orientation_adapter.cancel_step()
    if self._target_approach_adapter is not None:
        self._target_approach_adapter.cancel_task()
    if self._person_nav_approach_adapter is not None:
        self._person_nav_approach_adapter.cancel_task()
    if self._visual_target_approach_adapter is not None:
        self._visual_target_approach_adapter.cancel_task()
    if self._mobility_adapter is not None:
        self._mobility_adapter.cancel_step()
    if (self._chassis_backend is not None
            and not (self._long_goal_id is not None
                     and goal_handle.request.behavior_name in
                     ("play_alone", "follow_owner"))):
        self._chassis_backend.cancel_step()
    elif (self._chassis_backend is not None
          and self._long_goal_id is not None
          and goal_handle.request.behavior_name == "play_alone"
          and not getattr(self._uwb_roam_adapter, "active", False)):
        self._chassis_backend.cancel_step()
    self._stationary_expression_adapter.cancel_step()
    return cancel_response.ACCEPT


def on_accepted(self, goal_handle):
    """Kick off async execution when goal is accepted."""
    goal_handle.execute()

    g = goal_handle.request
    goal, params_valid = _debug_goal_from_request(g)
    if not params_valid:
        # Defensive path for direct callback harnesses or a future
        # transport regression.  Normal ROS flow rejects this in
        # _on_goal before _on_accepted can be invoked.
        self.get_logger().error(
            f"Accepted callback received invalid params_json: "
            f"goal_id={goal.goal_id}; recorded params as an empty object"
        )
    self._debug.publish_goal(goal)


def on_goal_lease(self, message):
    try:
        payload = json.loads(message.data)
    except (TypeError, ValueError):
        return
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return
    gid = payload.get("goal_id")
    bid = payload.get("behavior_id")
    if (not isinstance(gid, str) or not gid
            or not isinstance(bid, str) or not bid):
        return
    with self._goal_reservation_lock:
        if gid != self._reserved_goal_id:
            return
    with self._lease_lock:
        self._lease_seen[(gid, bid)] = time.monotonic()


def lease_expired(self, gid: str, bid: str, started: float):
    with self._lease_lock:
        renewed = self._lease_seen.get((gid, bid))
    grace = float(self.get_parameter("long_goal_lease_grace_sec").value)
    timeout = float(self.get_parameter("long_goal_lease_timeout_sec").value)
    return (time.monotonic() - (renewed if renewed is not None else started)
            > (timeout if renewed is not None else grace))
