from pathlib import Path

import pytest

from marsdog_vision_interaction.core.stranger_emotion_context import (
    STRANGER_EMOTION_ALERT,
    STRANGER_EMOTION_FRIEND,
    StrangerEmotionContext,
)
from marsdog_vision_interaction.core.presence_event_state import (
    PresenceEventConfig,
    PresenceEventState,
)
from marsdog_vision_interaction.messages.visual_event_derivation import (
    stranger_face_target_is_current,
    stranger_refinement_event,
)
from marsdog_vision_interaction.nodes.vision_interaction_node import (
    VisionInteractionNode,
    _append_stranger_refinement,
    _apply_presence_event_states,
)
from marsdog_vision_interaction.utils.config_loader import load_config


def _emotion_state(*triggered: str) -> dict:
    active = set(triggered)
    return {
        "schema_version": "2.0",
        "timestamp": 1710000000.0,
        "emotions": {
            name: {
                "value": 50 if name in active else 0,
                "triggerThreshold": 25,
                "triggerOperator": "gte",
                "triggered": name in active,
            }
            for name in (
                "Joy",
                "Excite",
                "Anxiety",
                "Fear",
                "Curious",
                "Calm",
            )
        },
    }


def _face_observation(identity: str) -> dict:
    return {
        "active_target": {
            "identity": identity,
            "identity_state": (
                "unverified" if identity == "unknown" else "confirmed_known"
            ),
            "tracking_state": "tracking",
            "pose_action": "",
        },
        "faces": [{"recognized_user": "" if identity == "unknown" else identity}],
        "hands": [],
        "tracked_objects": [],
    }


def _current_stranger_face_observation() -> dict:
    target_id = "epoch-1:human:7"
    active_target = {
        "vision_epoch": "epoch-1",
        "target_id": target_id,
        "track_id": 7,
        "face_track_id": 17,
        "identity": "unknown",
        "identity_state": "confirmed_unknown",
        "tracking_state": "tracking",
        "pose_action": "",
    }
    return {
        "vision_epoch": "epoch-1",
        "observation_status": "valid",
        "source_observation_id": "frame-7",
        "_source_observation_age_sec": 0.1,
        "_source_stranger_target_ids": [target_id],
        "active_target": active_target,
        "human_candidates": [{
            **active_target,
        }],
        "faces": [{
            "track_id": 17,
            "recognized_user": "unknown",
            "identity_state": "confirmed_unknown",
        }],
        "hands": [],
    }


def test_alert_emotions_take_precedence_over_friend_emotions() -> None:
    context = StrangerEmotionContext(timeout_sec=2.5)
    assert context.update(
        _emotion_state("Joy", "Fear"), received_monotonic=10.0
    )
    assert context.classify(now=10.1) == STRANGER_EMOTION_ALERT


def test_joy_excite_and_calm_classify_stranger_as_friend() -> None:
    for emotion in ("Joy", "Excite", "Calm"):
        context = StrangerEmotionContext(timeout_sec=2.5)
        assert context.update(
            _emotion_state(emotion), received_monotonic=10.0
        )
        assert context.classify(now=11.0) == STRANGER_EMOTION_FRIEND


def test_stale_unassigned_or_invalid_emotion_falls_back_to_generic() -> None:
    context = StrangerEmotionContext(timeout_sec=2.5)
    assert context.update(
        _emotion_state("Anxiety"), received_monotonic=10.0
    )
    assert context.classify(now=12.6) == ""

    assert context.update(
        _emotion_state("Curious"), received_monotonic=20.0
    )
    assert context.classify(now=20.1) == ""

    assert not context.update(
        {"schema_version": "2.0", "emotions": {"Joy": {}}},
        received_monotonic=20.2,
    )
    assert context.classify(now=20.3) == ""


def test_partial_invalid_state_does_not_replace_last_valid_snapshot() -> None:
    context = StrangerEmotionContext(timeout_sec=2.5)
    assert context.update(_emotion_state("Joy"), received_monotonic=10.0)
    assert not context.update(
        {"schema_version": "2.0", "emotions": {"Joy": {}}},
        received_monotonic=10.5,
    )
    assert context.classify(now=11.0) == STRANGER_EMOTION_FRIEND


def test_stranger_refinement_waits_for_presence_and_current_source_face() -> None:
    observation = _current_stranger_face_observation()
    assert VisionInteractionNode._derive_events(observation) == []
    assert VisionInteractionNode._derive_events(
        observation,
        STRANGER_EMOTION_ALERT,
        stranger_presence_active=True,
    ) == ["EVT_VISION_STRANGER_ALERT"]
    assert VisionInteractionNode._derive_events(
        observation,
        STRANGER_EMOTION_FRIEND,
        stranger_presence_active=True,
    ) == ["EVT_VISION_STRANGER_FRIEND"]
    assert VisionInteractionNode._derive_events(
        observation, stranger_presence_active=True
    ) == ["EVT_VISION_STRANGER"]
    assert stranger_refinement_event(STRANGER_EMOTION_ALERT) == (
        "EVT_VISION_STRANGER_ALERT"
    )
    assert stranger_refinement_event(STRANGER_EMOTION_FRIEND) == (
        "EVT_VISION_STRANGER_FRIEND"
    )
    assert stranger_refinement_event("") == ""


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("observation_status", "invalid"),
        ("source_observation_id", ""),
        ("_source_observation_age_sec", 0.6),
    ],
)
def test_stranger_face_refinement_requires_fresh_valid_source(change, value) -> None:
    observation = _current_stranger_face_observation()
    observation[change] = value
    assert not stranger_face_target_is_current(observation)


def test_stranger_face_refinement_rejects_unassociated_active_face() -> None:
    observation = _current_stranger_face_observation()
    observation["_source_stranger_target_ids"] = []
    assert not stranger_face_target_is_current(observation)

    observation = _current_stranger_face_observation()
    observation["faces"][0]["track_id"] = 18
    assert not stranger_face_target_is_current(observation)


def test_active_stranger_cycle_keeps_base_and_coemits_one_refinement() -> None:
    state = PresenceEventState(
        PresenceEventConfig(
            enter_duration_sec=0.2,
            exit_duration_sec=0.2,
            retrigger_delay_sec=3.0,
        ),
        event_tag="stranger-presence",
        source_target_ids_key="_source_stranger_target_ids",
        identities={"unknown"},
        identity_state="confirmed_unknown",
    )
    presence_states = (("EVT_VISION_STRANGER", state),)
    event_id = ""
    packet = None
    for index in range(3):
        observation = _current_stranger_face_observation()
        observation["source_observation_id"] = f"frame-{index}"
        observation["events"] = []
        current_face = stranger_face_target_is_current(observation)
        packet = _apply_presence_event_states(
            observation,
            presence_states,
            now=10.0 + index * 0.11,
        )
        _append_stranger_refinement(
            packet,
            emotion_classification=STRANGER_EMOTION_ALERT,
            face_is_current=current_face,
        )
    assert packet is not None
    assert packet["events"] == [
        "EVT_VISION_STRANGER",
        "EVT_VISION_STRANGER_ALERT",
    ]
    event_id = packet["event_instances"]["EVT_VISION_STRANGER"]["event_id"]

    next_observation = _current_stranger_face_observation()
    next_observation["source_observation_id"] = "frame-3"
    next_observation["events"] = []
    next_face_is_current = stranger_face_target_is_current(next_observation)
    assert next_face_is_current
    packet = _apply_presence_event_states(
        next_observation,
        presence_states,
        now=10.33,
    )
    assert packet["event_instances"]["EVT_VISION_STRANGER"]["event_id"] == (
        event_id
    )
    _append_stranger_refinement(
        packet,
        emotion_classification=STRANGER_EMOTION_FRIEND,
        face_is_current=next_face_is_current,
    )
    assert packet["events"] == [
        "EVT_VISION_STRANGER",
        "EVT_VISION_STRANGER_FRIEND",
    ]
    assert packet["event_instances"]["EVT_VISION_STRANGER"]["event_id"] == (
        event_id
    )

    invalid_observation = _current_stranger_face_observation()
    invalid_observation["source_observation_id"] = ""
    invalid_observation["observation_status"] = "invalid"
    invalid_observation["events"] = []
    packet = _apply_presence_event_states(
        invalid_observation,
        presence_states,
        now=10.44,
    )
    _append_stranger_refinement(
        packet,
        emotion_classification=STRANGER_EMOTION_ALERT,
        face_is_current=stranger_face_target_is_current(invalid_observation),
    )
    assert packet["events"] == ["EVT_VISION_STRANGER"]
    assert packet["event_instances"]["EVT_VISION_STRANGER"]["event_id"] == (
        event_id
    )


def test_known_face_keeps_master_event() -> None:
    assert VisionInteractionNode._derive_events(
        _face_observation("owner"), STRANGER_EMOTION_ALERT
    ) == ["EVT_VISION_MASTER"]


def test_stranger_emotion_configuration_is_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    production = load_config(root / "config" / "vision.yaml")
    mock = load_config(root / "config" / "vision.mock.yaml")
    object_only = load_config(root / "config" / "vision.object-only.yaml")

    expected = {
        "enabled": True,
        "state_timeout_sec": 2.5,
        "alert_emotions": ["Anxiety", "Fear"],
        "friend_emotions": ["Joy", "Excite", "Calm"],
    }
    assert production["stranger_emotion"] == expected
    assert mock["stranger_emotion"] == expected
    assert object_only["stranger_emotion"] == {"enabled": False}
    assert production["topics"]["emotion_state"] == "/emotion/state"
    assert mock["topics"]["emotion_state"] == "/emotion/state"
