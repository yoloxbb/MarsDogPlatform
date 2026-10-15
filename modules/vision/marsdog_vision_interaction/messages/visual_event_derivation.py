"""Identity-gated event derivation; no node, provider or ROS ownership."""
from __future__ import annotations
import math
from numbers import Real
from typing import Any
from .face_identity import (
    pose_event_identity_eligible as _face_pose_event_identity_eligible,
)
from .visual_event_types import (
    EVT_VISION_STRANGER,
    face_identity_to_vision_event,
    refine_stranger_vision_event,
    pose_action_to_vision_event,
)


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
    stranger_presence_active: bool = False,
    stranger_face_target_is_current: bool = False,
):
    events: list[str] = []
    active = observation.get("active_target", {})
    identity = str(active.get("identity", "unknown"))
    identity_confirmed = identity_eligible(active)
    if observation.get("faces"):
        if identity in ("", "unknown"):
            if not stranger_presence_active or not stranger_face_target_is_current:
                face_event = ""
            else:
                face_event = refine_stranger_vision_event(
                    emotion_classification
                )
        else:
            face_event = face_identity_to_vision_event(identity)
        if face_event:
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


def stranger_face_target_is_current(
    observation: dict[str, Any], *, source_freshness_sec: float = 0.5
) -> bool:
    """Whether the active stranger's face belongs to this valid source frame.

    Presence can remain active through invalid frames. Emotion refinement is
    narrower: it requires the active tracked stranger, source provenance, and
    its matching face to all be present in the current valid observation.
    """
    if (
        observation.get("observation_status") != "valid"
        or not str(observation.get("source_observation_id", "") or "").strip()
    ):
        return False
    age = observation.get("_source_observation_age_sec")
    if (
        isinstance(age, bool)
        or not isinstance(age, Real)
        or not math.isfinite(float(age))
        or float(age) < 0.0
        or float(age) > source_freshness_sec
    ):
        return False
    epoch = str(observation.get("vision_epoch", "") or "").strip()
    if not epoch:
        return False
    active = observation.get("active_target")
    if not isinstance(active, dict):
        return False
    target_id = active.get("target_id")
    track_id = active.get("track_id")
    face_track_id = active.get("face_track_id")
    if (
        not isinstance(target_id, str)
        or not target_id.strip()
        or active.get("identity") != "unknown"
        or active.get("identity_state") != "confirmed_unknown"
        or active.get("tracking_state") != "tracking"
        or isinstance(track_id, bool)
        or not isinstance(track_id, int)
        or track_id <= 0
        or isinstance(face_track_id, bool)
        or not isinstance(face_track_id, int)
        or face_track_id <= 0
        or str(active.get("vision_epoch", "") or "") != epoch
    ):
        return False
    source_target_ids = observation.get("_source_stranger_target_ids")
    if (
        not isinstance(source_target_ids, list)
        or target_id not in source_target_ids
    ):
        return False
    candidates = observation.get("human_candidates")
    if not isinstance(candidates, list):
        return False
    if not any(
        isinstance(candidate, dict)
        and candidate.get("target_id") == target_id
        and candidate.get("vision_epoch") == epoch
        and candidate.get("identity") == "unknown"
        and candidate.get("identity_state") == "confirmed_unknown"
        and candidate.get("tracking_state") == "tracking"
        and isinstance(candidate.get("track_id"), int)
        and not isinstance(candidate.get("track_id"), bool)
        and candidate.get("track_id") == track_id
        and isinstance(candidate.get("face_track_id"), int)
        and not isinstance(candidate.get("face_track_id"), bool)
        and candidate.get("face_track_id") == face_track_id
        for candidate in candidates
    ):
        return False
    faces = observation.get("faces")
    return isinstance(faces, list) and any(
        isinstance(face, dict)
        and isinstance(face.get("track_id"), int)
        and not isinstance(face.get("track_id"), bool)
        and face.get("track_id") > 0
        and face.get("track_id") == face_track_id
        and face.get("recognized_user") in ("", "unknown")
        and face.get("identity_state") == "confirmed_unknown"
        for face in faces
    )


def stranger_refinement_event(emotion_classification: str) -> str:
    """Return a classified subtype; the canonical event carries fallback."""
    event = refine_stranger_vision_event(emotion_classification)
    return "" if event == EVT_VISION_STRANGER else event
