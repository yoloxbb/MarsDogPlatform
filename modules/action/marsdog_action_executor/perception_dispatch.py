"""Perception JSON fan-out; malformed snapshots retain the existing stop path."""
from __future__ import annotations
import json

def _dispatch_visual_event(
    raw_data,
    *,
    attention_controller=None,
    target_approach_adapter=None,
    visual_target_approach_adapter=None,
    wake_orientation_adapter=None,
    person_nav_approach_adapter=None,
) -> bool:
    """Decode one visual event and fail the motion path closed.

    A malformed/non-object message is still safety-relevant while the target
    approach loop is moving.  Feeding an empty snapshot into the adapter
    invalidates its active observation and publishes the redundant zero Twist
    before this function returns.
    """
    try:
        payload = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        if target_approach_adapter is not None:
            target_approach_adapter.update_visual({})
        if visual_target_approach_adapter is not None:
            visual_target_approach_adapter.update_visual({})
        if wake_orientation_adapter is not None:
            wake_orientation_adapter.update_visual({})
        if person_nav_approach_adapter is not None:
            person_nav_approach_adapter.update_visual({})
        return False
    if attention_controller is not None:
        attention_controller.update_visual(payload)
    if target_approach_adapter is not None:
        target_approach_adapter.update_visual(payload)
    if visual_target_approach_adapter is not None:
        visual_target_approach_adapter.update_visual(payload)
    if wake_orientation_adapter is not None:
        wake_orientation_adapter.update_visual(payload)
    if person_nav_approach_adapter is not None:
        person_nav_approach_adapter.update_visual(payload)
    return True

def _dispatch_object_detection(
    raw_data,
    *,
    visual_target_approach_adapter=None,
) -> bool:
    """Decode one object-detection v2 packet for the active leased stream."""
    try:
        payload = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    if visual_target_approach_adapter is None:
        return True
    return bool(visual_target_approach_adapter.update_object_detection(payload))
