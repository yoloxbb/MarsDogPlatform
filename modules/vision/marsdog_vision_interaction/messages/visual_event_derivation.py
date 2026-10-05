"""Identity-gated event derivation; no node, provider or ROS ownership."""
from __future__ import annotations
from typing import Any
from .face_identity import pose_event_identity_eligible as _face_pose_event_identity_eligible
from .visual_event_types import face_identity_to_vision_event, refine_stranger_vision_event, pose_action_to_vision_event


def pose_event_identity_eligible(active: dict[str, Any]) -> bool:
    return _face_pose_event_identity_eligible(
        str(active.get("identity", "")),
        str(active.get("identity_state", "")),
        str(active.get("tracking_state", "")),
    )


def derive_events(
    observation: dict[str, Any],
    emotion_classification: str = "",
    *,
    identity_eligible,
):
    events: list[str] = []
    active = observation.get("active_target", {})
    identity = str(active.get("identity", "unknown"))
    identity_confirmed = identity_eligible(active)
    if observation.get("faces"):
        face_event = face_identity_to_vision_event(identity)
        if identity in ("", "unknown"):
            face_event = refine_stranger_vision_event(
                emotion_classification
            )
        events.append(face_event)
    action = str(active.get("pose_action", ""))
    action_event = pose_action_to_vision_event(action, identity_confirmed)
    if action_event:
        events.append(action_event)
    for hand in observation.get("hands", []):
        hand_event = pose_action_to_vision_event(
            str(hand.get("hand_action", "")), identity_confirmed
        )
        if hand_event and hand_event not in events:
            events.append(hand_event)
    return events
