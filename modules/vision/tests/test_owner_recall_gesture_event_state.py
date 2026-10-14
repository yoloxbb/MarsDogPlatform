from __future__ import annotations

import pytest

from marsdog_vision_interaction.core.owner_recall_gesture_event_state import (
    OwnerRecallGestureEventConfig,
    OwnerRecallGestureEventState,
)


EVENT = "EVT_VISION_OWNER_RECALL_GESTURE"


def _observation(
    source_id: str,
    actions: tuple[str, ...] = (),
    *,
    target_id: str = "vision-1:human:7",
    track_id: int = 7,
    epoch: str = "vision-1",
    identity: str = "owner",
    identity_state: str = "confirmed_known",
    tracking_state: str = "tracking",
    age_ms: float = 0.0,
    source_age: float = 0.0,
    source_targets: list[str] | None = None,
    human_targets: list[str] | None = None,
    gesture_target_id: str | None = None,
    gesture_track_id: int | None = None,
    observation_status: str = "valid",
    gesture_valid_sides: dict[str, list[str]] | None = None,
    gesture_release_sides: dict[str, list[str]] | None = None,
) -> dict:
    target = {
        "vision_epoch": epoch,
        "target_id": target_id,
        "target_type": "human",
        "track_id": track_id,
        "identity": identity,
        "identity_state": identity_state,
        "tracking_state": tracking_state,
        "last_seen_age_ms": age_ms,
    }
    return {
        "schema_version": 1,
        "vision_epoch": epoch,
        "snapshot_id": f"{epoch}:{source_id}",
        "sequence": int(source_id.rsplit(":", 1)[-1])
        if source_id.rsplit(":", 1)[-1].isdigit()
        else 1,
        "source_observation_id": source_id,
        "observation_status": observation_status,
        "_source_observation_age_sec": source_age,
        "_source_owner_target_ids": (
            source_targets if source_targets is not None else [target_id]
        ),
        "_source_human_target_ids": (
            human_targets if human_targets is not None else [target_id]
        ),
        "human_candidates": [target],
        "active_target": dict(target),
        "_gesture_target_id": (
            gesture_target_id if gesture_target_id is not None else target_id
        ),
        "_gesture_track_id": (
            gesture_track_id if gesture_track_id is not None else track_id
        ),
        "_gesture_diagnostics": {
            "recognized_actions": [
                {"name": action} for action in actions
            ],
            "recall_gesture_evidence": {
                name: {
                    "valid_sides": (
                        list(gesture_valid_sides.get(name, []))
                        if gesture_valid_sides is not None
                        else ["left", "right"]
                    ),
                    "release_sides": (
                        list(gesture_release_sides.get(name, []))
                        if gesture_release_sides is not None
                        else list(gesture_valid_sides.get(name, []))
                        if gesture_valid_sides is not None
                        else ["left", "right"]
                    ),
                    "active_sides": (
                        ["left"] if name in actions else []
                    ),
                }
                for name in ("beckoning", "waving")
            },
            # These values are intentionally not used for event qualification.
            "raw_scores": [{"name": "waving", "score": 0.0}],
        },
    }


def _state() -> OwnerRecallGestureEventState:
    return OwnerRecallGestureEventState(OwnerRecallGestureEventConfig())


def test_beckoning_and_waving_trigger_once_and_share_an_episode() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    assert first.active
    assert first.transition == "ENTER"
    assert first.event_id

    repeated = state.update(
        _observation("frame:1", ("beckoning",)), now=1.1
    )
    assert repeated.active
    assert repeated.event_id == first.event_id

    waving = state.update(_observation("frame:2", ("waving",)), now=1.2)
    assert waving.active
    assert waving.event_id == first.event_id


@pytest.mark.parametrize("action", ["beckoning", "waving"])
def test_each_accepted_stable_action_triggers(action: str) -> None:
    snapshot = _state().update(
        _observation("frame:1", (action,)), now=1.0
    )
    assert snapshot.active
    assert snapshot.transition == "ENTER"


def test_static_raised_arm_and_unrelated_action_do_not_trigger() -> None:
    state = _state()
    for i, actions in enumerate(
        [("arms_raised",), ("jump",), ()], start=1
    ):
        snapshot = state.update(
            _observation(f"frame:{i}", actions), now=float(i)
        )
        assert not snapshot.active


def test_only_unique_current_confirmed_owner_and_same_gesture_target_trigger() -> None:
    negative = [
        _observation("familiar:1", ("beckoning",), identity="family_member_1"),
        _observation("stranger:1", ("waving",), identity="unknown", identity_state="confirmed_unknown"),
        _observation("unconfirmed:1", ("beckoning",), identity_state="candidate"),
        _observation("lost:1", ("waving",), tracking_state="temporarily_lost"),
        _observation("expired:1", ("beckoning",), age_ms=500.0),
        _observation("not-source:1", ("waving",), source_targets=[]),
        _observation("wrong-gesture-target:1", ("beckoning",), gesture_target_id="other"),
        _observation("wrong-gesture-track:1", ("waving",), gesture_track_id=99),
    ]
    for observation in negative:
        assert not _state().update(observation, now=1.0).active


def test_ambiguous_owner_targets_fail_closed() -> None:
    observation = _observation("frame:1", ("beckoning",))
    second = dict(observation["human_candidates"][0])
    second.update(target_id="vision-1:human:8", track_id=8)
    observation["human_candidates"].append(second)
    observation["_source_owner_target_ids"].append(second["target_id"])
    assert not _state().update(observation, now=1.0).active


def test_valid_release_exits_once_then_new_gesture_gets_a_new_instance() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    assert first.active

    repeated_release = state.update(_observation("frame:1"), now=1.1)
    assert repeated_release.active
    assert repeated_release.event_id == first.event_id

    released = state.update(_observation("frame:2"), now=1.2)
    assert not released.active
    assert released.transition == "EXIT"

    next_gesture = state.update(
        _observation("frame:3", ("waving",)), now=1.3
    )
    assert next_gesture.active
    assert next_gesture.event_id != first.event_id


@pytest.mark.parametrize(
    "invalid_update",
    [
        {"observation_status": "invalid"},
        {"source_age": 0.51},
        {"age_ms": 500.0},
    ],
)
def test_invalid_or_expired_observations_never_release_or_rearm(
    invalid_update: dict,
) -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    invalid = _observation("frame:2", **invalid_update)
    invalid["_gesture_diagnostics"]["recognized_actions"] = []
    held = state.update(invalid, now=1.2)
    assert held.active
    assert held.event_id == first.event_id

    still_active = state.update(
        _observation("frame:3", ("beckoning",)), now=1.3
    )
    assert still_active.active
    assert still_active.event_id == first.event_id


@pytest.mark.parametrize("action", ["beckoning", "waving"])
def test_missing_gesture_source_does_not_release_a_stable_event(action: str) -> None:
    state = _state()
    first = state.update(_observation("frame:1", (action,)), now=1.0)
    missed_hand = _observation(
        "frame:2",
        gesture_valid_sides={
            "beckoning": [] if action == "beckoning" else ["left", "right"],
            "waving": [] if action == "waving" else ["left", "right"],
        },
    )
    missed_hand["_gesture_diagnostics"]["recognized_actions"] = []

    held = state.update(missed_hand, now=1.1)
    assert held.active
    assert held.event_id == first.event_id

    confirmed_clear = _observation("frame:3")
    released = state.update(confirmed_clear, now=1.2)
    assert not released.active
    assert released.transition == "EXIT"


def test_topic_gap_and_missing_current_owner_do_not_count_as_release() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("waving",)), now=1.0)
    missing = _observation(
        "frame:2",
        source_targets=[],
        human_targets=[],
        gesture_release_sides={"beckoning": [], "waving": ["left", "right"]},
    )
    held = state.update(missing, now=10.0)
    assert held.active
    assert held.event_id == first.event_id

    released = state.update(_observation("frame:3"), now=10.1)
    assert not released.active
    assert released.transition == "EXIT"


def test_action_source_gap_cannot_release_even_if_current_landmarks_return() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    after_gap = _observation(
        "frame:2",
        gesture_release_sides={"beckoning": [], "waving": ["left", "right"]},
    )
    cleared = state.update(after_gap, now=1.6)
    assert cleared.active
    assert cleared.event_id == first.event_id

    confirmed = state.update(_observation("frame:3"), now=1.7)
    assert not confirmed.active
    assert confirmed.transition == "EXIT"


def test_retained_other_recall_label_with_invalid_source_is_not_release() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    retained = _observation(
        "frame:2", ("waving",),
        gesture_valid_sides={"beckoning": ["left", "right"], "waving": []},
    )
    retained["_gesture_diagnostics"]["recall_gesture_evidence"]["waving"][
        "active_sides"
    ] = []
    held = state.update(retained, now=1.1)
    assert held.active
    assert held.event_id == first.event_id


def test_target_switch_cannot_reuse_old_event_or_trigger_until_new_target_clears() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    switched = state.update(
        _observation(
            "frame:2",
            ("waving",),
            target_id="vision-1:human:8",
            track_id=8,
        ),
        now=1.1,
    )
    assert not switched.active
    assert switched.transition == "EXIT"

    cleared = state.update(
        _observation(
            "frame:3", target_id="vision-1:human:8", track_id=8
        ),
        now=1.2,
    )
    assert not cleared.active
    assert cleared.transition == "REARM"

    next_gesture = state.update(
        _observation(
            "frame:4",
            ("waving",),
            target_id="vision-1:human:8",
            track_id=8,
        ),
        now=1.3,
    )
    assert next_gesture.active
    assert next_gesture.event_id != first.event_id


def test_epoch_change_needs_new_epoch_clear_observation_before_rearming() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    switched = state.update(
        _observation("frame:1", ("waving",), epoch="vision-2", target_id="vision-2:human:7"),
        now=1.1,
    )
    assert not switched.active
    assert switched.transition == "EXIT"

    cleared = state.update(
        _observation("frame:2", epoch="vision-2", target_id="vision-2:human:7"),
        now=1.2,
    )
    assert not cleared.active
    assert cleared.transition == "REARM"

    next_gesture = state.update(
        _observation("frame:3", ("beckoning",), epoch="vision-2", target_id="vision-2:human:7"),
        now=1.3,
    )
    assert next_gesture.active
    assert next_gesture.event_id != first.event_id


def test_identity_loss_retires_event_but_does_not_rearm_on_lost_identity() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    lost = state.update(
        _observation(
            "frame:2",
            identity="family_member_1",
            identity_state="confirmed_known",
        ),
        now=1.1,
    )
    assert not lost.active
    assert lost.transition == "EXIT"

    owner_clear = state.update(_observation("frame:3"), now=1.2)
    assert not owner_clear.active
    assert owner_clear.transition == "REARM"

    new_gesture = state.update(
        _observation("frame:4", ("waving",)), now=1.3
    )
    assert new_gesture.active
    assert new_gesture.event_id != first.event_id


@pytest.mark.parametrize("context_change", ["target_switch", "identity_loss"])
def test_owner_context_change_retires_old_instance_without_gesture_diagnostics(
    context_change: str,
) -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    assert first.active
    changed = _observation("frame:2")
    if context_change == "target_switch":
        changed = _observation(
            "frame:2", target_id="vision-1:human:8", track_id=8,
        )
    else:
        changed["human_candidates"][0]["identity"] = "family_member_1"
        changed["active_target"]["identity"] = "family_member_1"
    changed.pop("_gesture_diagnostics")
    retired = state.update(changed, now=1.1)
    assert not retired.active
    assert retired.transition == "EXIT"

    owner_target = (
        {"target_id": "vision-1:human:8", "track_id": 8}
        if context_change == "target_switch" else {}
    )
    continued = state.update(
        _observation("frame:3", ("beckoning",), **owner_target), now=1.2,
    )
    assert not continued.active
    cleared = state.update(_observation("frame:4", **owner_target), now=1.3)
    assert cleared.transition == "REARM"
    next_cycle = state.update(
        _observation("frame:5", ("beckoning",), **owner_target), now=1.4,
    )
    assert next_cycle.active
    assert next_cycle.event_id != first.event_id


def test_missing_or_malformed_stable_diagnostics_cannot_release() -> None:
    state = _state()
    first = state.update(_observation("frame:1", ("beckoning",)), now=1.0)
    no_diagnostics = _observation("frame:2")
    no_diagnostics.pop("_gesture_diagnostics")
    assert state.update(no_diagnostics, now=1.1).event_id == first.event_id

    malformed = _observation("frame:3")
    malformed["_gesture_diagnostics"]["recognized_actions"] = ["waving"]
    assert state.update(malformed, now=1.2).event_id == first.event_id


def test_owner_config_validates_enabled_type_only() -> None:
    assert OwnerRecallGestureEventConfig.from_mapping(None).enabled
    assert not OwnerRecallGestureEventConfig.from_mapping({"enabled": False}).enabled
    with pytest.raises(ValueError):
        OwnerRecallGestureEventConfig.from_mapping({"enabled": 1})
