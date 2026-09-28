from pathlib import Path

from marsdog_vision_interaction.core.stranger_emotion_context import (
    STRANGER_EMOTION_ALERT,
    STRANGER_EMOTION_FRIEND,
    StrangerEmotionContext,
)
from marsdog_vision_interaction.nodes.vision_interaction_node import (
    VisionInteractionNode,
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


def test_stranger_event_is_refined_and_replaces_generic_event() -> None:
    observation = _face_observation("unknown")
    assert VisionInteractionNode._derive_events(observation) == [
        "EVT_VISION_STRANGER"
    ]
    assert VisionInteractionNode._derive_events(
        observation, STRANGER_EMOTION_ALERT
    ) == ["EVT_VISION_STRANGER_ALERT"]
    assert VisionInteractionNode._derive_events(
        observation, STRANGER_EMOTION_FRIEND
    ) == ["EVT_VISION_STRANGER_FRIEND"]


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
