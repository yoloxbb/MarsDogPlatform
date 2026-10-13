from __future__ import annotations

import pytest

from marsdog_vision_interaction.core.owner_posture_event_state import (
    OwnerPostureEventConfig,
    OwnerPostureEventState,
)
from marsdog_vision_interaction.messages.visual_event_types import (
    EVT_VISION_OWNER_BEND_SQUAT,
)


EPOCH = "epoch-a"


def _observation(
    sequence: int,
    *,
    epoch: str = EPOCH,
    pose: str = "bend_over",
    identity: str = "owner",
    identity_state: str = "confirmed_known",
    tracking_state: str = "tracking",
    source_owner: bool = True,
    source_human: bool = True,
    target_track: int = 7,
    status: str = "valid",
    source_id: str | None = None,
    source_age: float = 0.0,
) -> dict:
    target_id = f"{epoch}:human:{target_track}"
    return {
        "vision_epoch": epoch,
        "snapshot_id": f"{epoch}:{sequence}",
        "sequence": sequence,
        "observation_status": status,
        "source_observation_id": source_id or f"source:{epoch}:{sequence}",
        "_source_observation_age_sec": source_age,
        "_source_owner_target_ids": [target_id] if source_owner else [],
        "_source_human_target_ids": [target_id] if source_human else [],
        "human_candidates": [{
            "vision_epoch": epoch,
            "target_id": target_id,
            "track_id": target_track,
            "target_type": "human",
            "identity": identity,
            "identity_state": identity_state,
            "tracking_state": tracking_state,
            "pose_action": pose,
            "last_seen_age_ms": 0.0,
        }],
    }


def _state() -> OwnerPostureEventState:
    return OwnerPostureEventState(
        OwnerPostureEventConfig.from_mapping({
            "enabled": True,
            "enter_duration_sec": 1.0,
        }),
        source_freshness_sec=0.5,
    )


def _enter(
    state: OwnerPostureEventState,
    *,
    start: float = 10.0,
    first_sequence: int = 1,
    epoch: str = EPOCH,
    target_track: int = 7,
    pose: str = "bend_over",
) -> tuple[float, str]:
    result = None
    for index in range(6):
        now = start + index * 0.2
        result = state.update(
            _observation(
                first_sequence + index,
                epoch=epoch,
                target_track=target_track,
                pose=pose,
            ),
            now=now,
        )
        if result.transition == "ENTER":
            return now, result.event_id
    raise AssertionError("owner posture did not ENTER within 1.0 seconds")


def test_only_current_confirmed_owner_with_stable_pose_can_enter() -> None:
    changes = [
        {"identity": "family_member_1"},
        {"identity": "unknown", "identity_state": "confirmed_unknown"},
        {"identity_state": "unverified"},
        {"identity_state": "candidate_known"},
        {"tracking_state": "temporarily_lost"},
        {"tracking_state": "lost"},
        {"source_owner": False},
    ]
    for change in changes:
        state = _state()
        for index in range(8):
            result = state.update(
                _observation(index + 1, **change),
                now=10.0 + index * 0.2,
            )
            assert result.active is False


@pytest.mark.parametrize("pose", ["bend_over", "squat_down"])
def test_distinct_pose_observations_enter_once_and_hold_same_instance(
    pose: str,
) -> None:
    state = _state()
    for index in range(5):
        result = state.update(
            _observation(index + 1, pose=pose),
            now=10.0 + index * 0.2,
        )
        assert result.active is False
    entered = state.update(
        _observation(6, pose=pose), now=11.0
    )
    assert entered.transition == "ENTER"
    assert entered.active
    assert entered.event_id.startswith("epoch-a:owner-posture:")

    # Bend/squat may alternate inside the same smoothed posture cycle.
    held = state.update(
        _observation(7, pose="squat_down" if pose == "bend_over" else "bend_over"),
        now=11.2,
    )
    assert held.transition == "HOLD"
    assert held.event_id == entered.event_id
    assert state.update(
        _observation(8, pose=pose), now=11.4
    ).event_id == entered.event_id


def test_repeated_snapshot_does_not_advance_time_or_repeat_candidate() -> None:
    state = _state()
    first = _observation(1, source_id="same-source")
    assert not state.update(first, now=10.0).active
    for index in range(1, 8):
        duplicate = dict(first)
        duplicate["snapshot_id"] = f"snapshot-{index}"
        duplicate["sequence"] = index
        assert not state.update(duplicate, now=10.0 + index * 0.2).active

    # The first new source frame starts the interval; duplicates contributed no
    # timing evidence.
    for index in range(6):
        result = state.update(
            _observation(index + 2), now=12.0 + index * 0.2
        )
    assert result.transition == "ENTER"


def test_only_same_target_public_pose_release_rearms_and_next_cycle_gets_new_id() -> None:
    state = _state()
    enter_time, first_id = _enter(state)

    # A transient raw miss is hidden by the existing GesturePose public
    # hysteresis, so the public label remains active and this cycle stays held.
    held = state.update(
        _observation(20, pose="bend_over"), now=enter_time + 0.2
    )
    assert held.active
    assert held.event_id == first_id

    released = state.update(
        _observation(21, pose=""), now=enter_time + 0.4
    )
    assert released.transition == "EXIT"
    assert not released.active
    assert released.event_id == ""

    second_enter_time, second_id = _enter(
        state, start=enter_time + 0.6, first_sequence=30
    )
    assert second_enter_time == pytest.approx(enter_time + 1.6)
    assert second_id != first_id


@pytest.mark.parametrize(
    "status,age",
    [
        ("invalid", 0.0),
        ("valid", 0.5001),
        ("valid", -0.1),
    ],
)
def test_invalid_inference_and_expired_data_preserve_active_cycle(
    status: str,
    age: float,
) -> None:
    state = _state()
    enter_time, event_id = _enter(state)
    for index in range(5):
        invalid = _observation(
            20 + index,
            pose="",
            status=status,
            source_age=age,
        )
        held = state.update(
            invalid, now=enter_time + 0.2 + index * 0.2
        )
        assert held.active
        assert held.event_id == event_id

    recovered = state.update(
        _observation(30, pose="bend_over"), now=enter_time + 1.4
    )
    assert recovered.transition == "HOLD"
    assert recovered.event_id == event_id


def test_retained_only_row_does_not_release_and_identity_loss_latches_until_pose_release() -> None:
    state = _state()
    enter_time, event_id = _enter(state)

    retained_only = _observation(
        20,
        identity="family_member_1",
        source_owner=False,
        source_human=False,
    )
    held = state.update(retained_only, now=enter_time + 0.2)
    assert held.active
    assert held.event_id == event_id

    current_identity_loss = _observation(
        21,
        identity="family_member_1",
        source_owner=False,
        source_human=True,
    )
    exited = state.update(current_identity_loss, now=enter_time + 0.4)
    assert exited.transition == "EXIT"
    assert not exited.active

    recovered_same_pose = state.update(
        _observation(22), now=enter_time + 0.6
    )
    assert not recovered_same_pose.active
    assert recovered_same_pose.event_id == ""

    cleared_pose = state.update(
        _observation(23, pose=""), now=enter_time + 0.8
    )
    assert not cleared_pose.active
    reentered_at, new_id = _enter(
        state, start=enter_time + 1.0, first_sequence=30
    )
    assert reentered_at == pytest.approx(enter_time + 2.0)
    assert new_id != event_id


def test_short_source_gap_preserves_active_cycle_but_restarts_pending_entry() -> None:
    pending = _state()
    assert not pending.update(_observation(1), now=10.0).active
    assert not pending.update(_observation(2), now=10.2).active
    assert not pending.update(_observation(3), now=11.0).active
    for index in range(5):
        assert not pending.update(
            _observation(4 + index), now=11.0 + index * 0.2
        ).active
    assert pending.update(_observation(9), now=12.0).transition == "ENTER"

    state = _state()
    enter_time, event_id = _enter(state)
    invalid = _observation(
        40,
        pose="",
        status="invalid",
        source_owner=False,
    )
    assert state.update(invalid, now=enter_time + 0.2).event_id == event_id
    recovered = state.update(
        _observation(41, pose="bend_over"),
        now=enter_time + 1.0,
    )
    assert recovered.transition == "HOLD"
    assert recovered.event_id == event_id


def test_target_and_epoch_changes_discard_old_cycle_context() -> None:
    state = _state()
    enter_time, old_id = _enter(state)

    switched = state.update(
        _observation(20, target_track=8), now=enter_time + 0.2
    )
    assert not switched.active
    assert switched.event_id == ""
    second = _enter(
        state,
        start=enter_time + 0.4,
        first_sequence=30,
        target_track=8,
    )
    assert second[1] != old_id

    epoch_change = state.update(
        _observation(
            1,
            epoch="epoch-b",
            target_track=8,
        ),
        now=second[0] + 0.2,
    )
    assert not epoch_change.active
    assert epoch_change.event_id == ""
    third = _enter(
        state,
        start=second[0] + 0.4,
        first_sequence=2,
        epoch="epoch-b",
        target_track=8,
    )
    assert third[1] != second[1]


def test_invalid_new_epoch_does_not_clear_active_cycle() -> None:
    state = _state()
    enter_time, event_id = _enter(state)

    invalid_epoch = state.update(
        _observation(1, epoch="epoch-b", status="invalid"),
        now=enter_time + 0.2,
    )
    assert invalid_epoch.active
    assert invalid_epoch.event_id == event_id

    first_valid_new_epoch = state.update(
        _observation(2, epoch="epoch-b"),
        now=enter_time + 0.4,
    )
    assert not first_valid_new_epoch.active
    assert first_valid_new_epoch.event_id == ""

    _, new_id = _enter(
        state,
        start=enter_time + 0.4,
        first_sequence=3,
        epoch="epoch-b",
    )
    assert new_id != event_id


@pytest.mark.parametrize("age_ms", [500.0, 501.0, -1.0, float("nan"), True, None])
def test_expired_or_invalid_target_age_cannot_enter_or_release(age_ms) -> None:
    pending = _state()
    for index in range(7):
        observation = _observation(100 + index)
        observation["human_candidates"][0]["last_seen_age_ms"] = age_ms
        assert not pending.update(observation, now=10.0 + index * 0.2).active

    active = _state()
    entered_at, event_id = _enter(active)
    released = _observation(20, pose="")
    released["human_candidates"][0]["last_seen_age_ms"] = age_ms
    assert active.update(released, now=entered_at + 0.2).event_id == event_id

    # An expired identity change is not valid evidence that ends this cycle.
    lost = _observation(21, identity="family_member_1", source_owner=False)
    lost["human_candidates"][0]["last_seen_age_ms"] = age_ms
    assert active.update(lost, now=entered_at + 0.4).event_id == event_id


@pytest.mark.parametrize("pose", [[], {}, None, 7])
def test_malformed_pose_cannot_enter_or_release_active_cycle(pose) -> None:
    pending = _state()
    for index in range(7):
        assert not pending.update(
            _observation(100 + index, pose=pose), now=10.0 + index * 0.2
        ).active

    active = _state()
    entered_at, event_id = _enter(active)
    assert active.update(
        _observation(20, pose=pose), now=entered_at + 0.2
    ).event_id == event_id


@pytest.mark.parametrize(
    "value",
    [
        {"enter_duration_sec": 0},
        {"enter_duration_sec": float("nan")},
        {"enter_duration_sec": True},
        {"enabled": "yes"},
    ],
)
def test_owner_posture_config_rejects_invalid_values(value: dict) -> None:
    with pytest.raises(ValueError):
        OwnerPostureEventConfig.from_mapping(value)


def test_event_name_is_distinct_from_action_and_presence_events() -> None:
    assert EVT_VISION_OWNER_BEND_SQUAT == "EVT_VISION_OWNER_BEND_SQUAT"
    assert EVT_VISION_OWNER_BEND_SQUAT != "ACT_OWNER_APPROACH_RESPONSE"
