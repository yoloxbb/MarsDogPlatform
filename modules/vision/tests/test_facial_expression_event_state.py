from pathlib import Path

import pytest

from marsdog_vision_interaction.core.facial_expression_event_state import (
    HAPPY_EVENT,
    SAD_EVENT,
    FacialExpressionEventConfig,
    FacialExpressionEventState,
)
from marsdog_vision_interaction.nodes.vision_interaction_node import (
    VisionInteractionNode,
)
from marsdog_vision_interaction.utils.config_loader import load_config


def _observation(
    *,
    stamp: float,
    expression: str | None = "happy",
    confidence: float = 0.70,
    identity: str = "owner",
    identity_state: str = "confirmed_known",
    tracking_state: str = "tracking",
    face_track_id: int = 7,
    row_track_id: int = 7,
    valid_for: float | None = 0.5,
    epoch: str = "epoch-a",
) -> dict:
    face = {"track_id": row_track_id}
    if expression is not None:
        face["facial_expression"] = {
            "expression": expression,
            "confidence": confidence,
        }
    result = {
        "vision_epoch": epoch,
        "header": {"stamp": stamp, "frame_id": "camera_color_optical_frame"},
        "active_target": {
            "vision_epoch": epoch,
            "identity": identity,
            "identity_state": identity_state,
            "tracking_state": tracking_state,
            "face_track_id": face_track_id,
        },
        "faces": [face],
    }
    if valid_for is not None:
        result["facial_expression_valid_for_sec"] = valid_for
    return result


def _state() -> FacialExpressionEventState:
    return FacialExpressionEventState(
        FacialExpressionEventConfig.from_mapping(
            {
                "enabled": True,
                "minimum_confidence": 0.70,
                "stable_duration_sec": 1.0,
                "release_duration_sec": 0.5,
            }
        ),
        source_freshness_sec=0.5,
    )


def _stable_expression(
    state: FacialExpressionEventState,
    *,
    expression: str = "happy",
    start: float = 10.0,
    epoch: str = "epoch-a",
) -> list[str]:
    result: list[str] = []
    for index in range(11):
        now = start + index * 0.1
        result = state.update(
            _observation(
                stamp=100.0 + index * 0.1,
                expression=expression,
                epoch=epoch,
            ),
            now=now,
        )
    return result


def test_owner_happy_and_sad_enter_after_distinct_fresh_frames() -> None:
    happy = _state()
    assert _stable_expression(happy) == [HAPPY_EVENT]

    sad = _state()
    assert _stable_expression(sad, expression="sad") == [SAD_EVENT]


def test_repeated_source_publications_do_not_advance_entry() -> None:
    state = _state()
    same_frame = _observation(stamp=100.0)
    same_frame["sequence"] = 1
    same_frame["snapshot_id"] = "epoch-a:1"
    assert state.update(same_frame, now=10.0) == []
    same_frame["sequence"] = 2
    same_frame["snapshot_id"] = "epoch-a:2"
    assert state.update(same_frame, now=10.2) == []
    same_frame["sequence"] = 3
    same_frame["snapshot_id"] = "epoch-a:3"
    assert state.update(same_frame, now=11.1) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"confidence": 0.6999},
        {"identity": "alice"},
        {"identity_state": "unverified"},
        {"tracking_state": "temporarily_lost"},
        {"row_track_id": 8},
        {"face_track_id": -1},
        {"expression": "neutral"},
        {"valid_for": 0.0},
        {"valid_for": None},
    ],
)
def test_non_owner_or_unqualified_evidence_cannot_enter(changes: dict) -> None:
    state = _state()
    for index in range(12):
        observation = _observation(stamp=100.0 + index * 0.1, **changes)
        assert state.update(observation, now=10.0 + index * 0.1) == []


def test_confidence_threshold_is_inclusive_at_point_seven() -> None:
    state = _state()
    assert _stable_expression(state) == [HAPPY_EVENT]


def test_category_change_starts_new_candidate_and_releases_old_support() -> None:
    state = _state()
    assert _stable_expression(state) == [HAPPY_EVENT]

    assert state.update(
        _observation(stamp=102.0, expression="sad"), now=11.1
    ) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=102.1, expression="sad"), now=11.3
    ) == [HAPPY_EVENT]
    # Release begins at the first observation of the new category.
    assert state.update(
        _observation(stamp=102.2, expression="sad"), now=11.61
    ) == []

    # The sad candidate continues only with further distinct source frames.
    for index in range(7, 12):
        events = state.update(
            _observation(stamp=102.0 + index * 0.1, expression="sad"),
            now=11.1 + index * 0.1,
        )
    assert events == [SAD_EVENT]


def test_missing_expression_releases_after_half_second_and_recovery_cancels() -> None:
    state = _state()
    assert _stable_expression(state) == [HAPPY_EVENT]

    assert state.update(
        _observation(stamp=101.0, expression=None, valid_for=None), now=11.1
    ) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=101.0, expression=None, valid_for=None), now=11.4
    ) == [HAPPY_EVENT]
    # A new matching frame before 0.5 seconds cancels the release timer.
    assert state.update(_observation(stamp=101.1), now=11.5) == [HAPPY_EVENT]

    assert state.update(
        _observation(stamp=101.2, expression=None, valid_for=None), now=11.6
    ) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=101.2, expression=None, valid_for=None), now=12.11
    ) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"confidence": 0.69},
        {"valid_for": 0.0},
        {"valid_for": None},
        {"identity_state": "unverified"},
        {"tracking_state": "temporarily_lost"},
    ],
)
def test_confidence_freshness_and_owner_loss_release_after_half_second(
    changes: dict,
) -> None:
    state = _state()
    assert _stable_expression(state) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=101.1, **changes), now=11.1
    ) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=101.2, **changes), now=11.4
    ) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=101.3, **changes), now=11.61
    ) == []


def test_source_gap_longer_than_freshness_restarts_stability() -> None:
    state = _state()
    assert state.update(_observation(stamp=100.0), now=10.0) == []
    assert state.update(_observation(stamp=100.1), now=10.1) == []
    assert state.update(_observation(stamp=100.2), now=10.7) == []
    for index in range(1, 10):
        events = state.update(
            _observation(stamp=100.2 + index * 0.1),
            now=10.7 + index * 0.1,
        )
    assert events == []
    assert state.update(_observation(stamp=101.2), now=11.7) == [HAPPY_EVENT]


def test_epoch_change_clears_active_and_pending_state() -> None:
    state = _state()
    assert _stable_expression(state) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=200.0, epoch="epoch-b"), now=11.1
    ) == []
    assert state.update(
        _observation(stamp=200.1, epoch="epoch-b"), now=11.2
    ) == []


def test_interrupted_candidate_needs_a_full_second_of_recovered_evidence() -> None:
    state = _state()
    for index in range(10):
        assert state.update(
            _observation(stamp=100.0 + index * 0.1),
            now=10.0 + index * 0.1,
        ) == []
    assert state.update(
        _observation(stamp=101.0, confidence=0.69), now=11.0
    ) == []
    for index in range(10):
        assert state.update(
            _observation(stamp=101.1 + index * 0.1),
            now=11.1 + index * 0.1,
        ) == []
    assert state.update(_observation(stamp=102.1), now=12.1) == [HAPPY_EVENT]


def test_release_boundary_and_matching_recovery() -> None:
    state = _state()
    assert _stable_expression(state) == [HAPPY_EVENT]
    invalid = _observation(stamp=101.1, expression=None)
    assert state.update(invalid, now=11.25) == [HAPPY_EVENT]
    assert state.update(invalid, now=11.749) == [HAPPY_EVENT]
    assert state.update(invalid, now=11.75) == []
    # Recovery after completed release must qualify for a new stable entry.
    assert state.update(_observation(stamp=101.2), now=11.8) == []


def test_target_epoch_mismatch_and_explicit_reset_discard_evidence() -> None:
    state = _state()
    for index in range(12):
        observation = _observation(stamp=100.0 + index * 0.1)
        observation["active_target"]["vision_epoch"] = "stale-epoch"
        assert state.update(observation, now=10.0 + index * 0.1) == []
    assert _stable_expression(state, start=20.0) == [HAPPY_EVENT]
    state.reset()
    assert state.update(_observation(stamp=200.0), now=21.1) == []


def test_visual_event_merge_preserves_pose_hand_support_and_order() -> None:
    node = object.__new__(VisionInteractionNode)
    node._facial_expression_event_state = _state()
    observation = _observation(stamp=100.0)
    observation["active_target"]["pose_action"] = "arm_raise_wave"

    events = []
    for index in range(11):
        observation = _observation(stamp=100.0 + index * 0.1)
        observation["active_target"]["pose_action"] = "arm_raise_wave"
        events = node._derive_events_with_facial_expression(
            observation,
            now=10.0 + index * 0.1,
        )
    assert events == ["EVT_VISION_MASTER", HAPPY_EVENT]

    # Expression support expires, while the independent pose source remains.
    observation = _observation(
        stamp=101.1,
        expression=None,
        valid_for=None,
    )
    observation["active_target"]["pose_action"] = "arm_raise_wave"
    assert node._derive_events_with_facial_expression(
        observation, now=11.1
    ) == ["EVT_VISION_MASTER", HAPPY_EVENT]
    assert node._derive_events_with_facial_expression(
        observation, now=11.61
    ) == ["EVT_VISION_MASTER", HAPPY_EVENT]
    assert node._facial_expression_event_state.update(
        observation, now=11.61
    ) == []


def test_hand_event_can_keep_happy_active_after_expression_release() -> None:
    node = object.__new__(VisionInteractionNode)
    node._facial_expression_event_state = _state()
    for index in range(11):
        observation = _observation(stamp=100.0 + index * 0.1)
        events = node._derive_events_with_facial_expression(
            observation, now=10.0 + index * 0.1
        )
    assert events == ["EVT_VISION_MASTER", HAPPY_EVENT]

    observation = _observation(
        stamp=101.1,
        expression=None,
        valid_for=None,
    )
    observation["hands"] = [{"hand_action": "thumbs_up"}]
    assert node._derive_events_with_facial_expression(
        observation, now=11.1
    ) == ["EVT_VISION_MASTER", HAPPY_EVENT]
    assert node._derive_events_with_facial_expression(
        observation, now=11.61
    ) == ["EVT_VISION_MASTER", HAPPY_EVENT]
    assert node._facial_expression_event_state.update(
        observation, now=11.61
    ) == []


def test_expression_appends_after_existing_events_without_changing_order() -> None:
    node = object.__new__(VisionInteractionNode)
    node._facial_expression_event_state = _state()
    for index in range(11):
        observation = _observation(stamp=100.0 + index * 0.1)
        observation["active_target"]["pose_action"] = "arms_crossed"
        observation["hands"] = [{"hand_action": "stop_gesture"}]
        events = node._derive_events_with_facial_expression(
            observation, now=10.0 + index * 0.1
        )
    assert events == [
        "EVT_VISION_MASTER",
        SAD_EVENT,
        "EVT_VISION_STOP_GESTURE",
        HAPPY_EVENT,
    ]


def test_cached_active_frame_releases_after_provider_freshness_expires() -> None:
    state = _state()
    assert _stable_expression(state) == [HAPPY_EVENT]
    # The provider ages the lifetime without giving this cached frame a new key.
    assert state.update(
        _observation(stamp=101.0, valid_for=0.1), now=11.4
    ) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=101.0, valid_for=0.0), now=11.5
    ) == [HAPPY_EVENT]
    assert state.update(
        _observation(stamp=101.0, expression=None, valid_for=None), now=12.0
    ) == []


def test_missing_policy_configuration_disables_expression_events() -> None:
    state = FacialExpressionEventState(FacialExpressionEventConfig.from_mapping(None))
    assert _stable_expression(state) == []


def test_event_policy_configuration_is_optional_and_checked_in_real_config() -> None:
    assert FacialExpressionEventConfig.from_mapping(None).enabled is False
    root = Path(__file__).resolve().parents[1]
    real_config = load_config(root / "config" / "vision.yaml")
    assert real_config["facial_expression_events"] == {
        "enabled": True,
        "minimum_confidence": 0.70,
        "stable_duration_sec": 1.0,
        "release_duration_sec": 0.5,
    }
    mock_config = load_config(root / "config" / "vision.mock.yaml")
    assert "facial_expression_events" not in mock_config


@pytest.mark.parametrize(
    "value",
    [
        {"enabled": "true"},
        {"enabled": True, "minimum_confidence": True},
        {"enabled": True, "minimum_confidence": -0.1},
        {"enabled": True, "minimum_confidence": 1.1},
        {"enabled": True, "minimum_confidence": float("nan")},
        {"enabled": True, "stable_duration_sec": 0},
        {"enabled": True, "stable_duration_sec": float("inf")},
        {"enabled": True, "release_duration_sec": -0.1},
        {"enabled": True, "release_duration_sec": True},
        {"enabled": True, "release_duration_sec": float("nan")},
    ],
)
def test_event_policy_rejects_invalid_configuration(value: dict) -> None:
    with pytest.raises(ValueError):
        FacialExpressionEventConfig.from_mapping(value)
