from __future__ import annotations

import pytest

from marsdog_vision_interaction.core.owner_presence_event_state import (
    OwnerPresenceEventConfig,
    OwnerPresenceEventState,
)
from marsdog_vision_interaction.messages.visual_event_types import (
    EVT_VISION_MASTER,
)


EPOCH = "epoch-a"
TARGET_ID = f"{EPOCH}:human:7"


def _observation(
    sequence: int,
    *,
    epoch: str = EPOCH,
    identity: str = "owner",
    identity_state: str = "confirmed_known",
    tracking_state: str = "tracking",
    owner_in_source: bool = True,
    status: str = "valid",
    source_id: str | None = None,
    source_age: float = 0.0,
) -> dict:
    target_id = f"{epoch}:human:7"
    return {
        "vision_epoch": epoch,
        "snapshot_id": f"{epoch}:{sequence}",
        "observation_status": status,
        "source_observation_id": source_id or f"source:{epoch}:{sequence}",
        "_source_observation_age_sec": source_age,
        "_source_owner_target_ids": [target_id] if owner_in_source else [],
        "human_candidates": [{
            "vision_epoch": epoch,
            "target_id": target_id,
            "track_id": 7,
            "face_track_id": 17,
            "identity": identity,
            "identity_state": identity_state,
            "tracking_state": tracking_state,
        }],
    }


def _state() -> OwnerPresenceEventState:
    return OwnerPresenceEventState(
        OwnerPresenceEventConfig.from_mapping({
            "enabled": True,
            "enter_duration_sec": 1.0,
            "exit_duration_sec": 2.0,
            "retrigger_delay_sec": 3.0,
        }),
        source_freshness_sec=0.5,
    )


def _feed_owner_until_enter(
    state: OwnerPresenceEventState,
    *,
    start: float = 10.0,
    first_sequence: int = 1,
) -> tuple[float, str]:
    result = None
    for index in range(6):
        now = start + index * 0.2
        result = state.update(
            _observation(first_sequence + index), now=now
        )
        if result.transition == "ENTER":
            return now, result.event_id
    raise AssertionError("owner presence did not ENTER within 1.0 seconds")


def test_enter_requires_full_stability_duration_and_emits_once() -> None:
    state = _state()
    assert state.update(_observation(1), now=10.0).active is False
    assert state.update(_observation(2), now=10.2).active is False
    assert state.update(_observation(3), now=10.4).active is False
    assert state.update(_observation(4), now=10.6).active is False
    assert state.update(_observation(5), now=10.8).active is False

    entered = state.update(_observation(6), now=11.0)
    assert entered.active is True
    assert entered.transition == "ENTER"
    assert entered.event_id.startswith("epoch-a:owner-presence:")

    held = state.update(_observation(7), now=11.2)
    assert held.active is True
    assert held.transition == "HOLD"
    assert held.event_id == entered.event_id


@pytest.mark.parametrize(
    "changes",
    [
        {"identity": "family_member_1"},
        {"identity": "stranger"},
        {"identity_state": "unverified"},
        {"identity_state": "candidate_known"},
        {"tracking_state": "temporarily_lost"},
        {"tracking_state": "lost"},
        {"owner_in_source": False},
    ],
)
def test_only_current_confirmed_owner_can_enter(changes: dict) -> None:
    state = _state()
    for index in range(8):
        result = state.update(
            _observation(index + 1, **changes),
            now=10.0 + index * 0.2,
        )
        assert result.active is False


def test_valid_short_miss_holds_then_two_seconds_of_misses_exits() -> None:
    state = _state()
    enter_time, event_id = _feed_owner_until_enter(state)

    # A short valid negative starts EXIT, but the owner returns before T_exit.
    assert state.update(
        _observation(20, owner_in_source=False), now=enter_time + 0.2
    ).active
    assert state.update(
        _observation(21, owner_in_source=False), now=enter_time + 0.4
    ).active
    restored = state.update(_observation(22), now=enter_time + 0.6)
    assert restored.active
    assert restored.event_id == event_id

    result = None
    for index in range(11):
        result = state.update(
            _observation(30 + index, owner_in_source=False),
            now=enter_time + 0.8 + index * 0.2,
        )
        if result.transition == "EXIT":
            break
    assert result is not None
    assert result.transition == "EXIT"
    assert result.active is False
    assert result.event_id == ""


def test_retrigger_waits_three_seconds_after_exit_then_requires_full_entry() -> None:
    state = _state()
    enter_time, _ = _feed_owner_until_enter(state)

    result = None
    for index in range(11):
        result = state.update(
            _observation(20 + index, owner_in_source=False),
            now=enter_time + index * 0.2,
        )
    assert result is not None and result.transition == "EXIT"
    actual_exit_time = enter_time + 2.0

    # Owner can be seen during cooldown but contributes no entry duration.
    for index in range(15):
        result = state.update(
            _observation(40 + index), now=actual_exit_time + 0.2 + index * 0.2
        )
        assert result.active is False

    # At/after cooldown, first fresh owner source starts a new T_enter interval.
    cooldown_end = actual_exit_time + 3.0
    first = state.update(_observation(60), now=cooldown_end)
    assert first.active is False
    for index in range(1, 5):
        assert state.update(
            _observation(60 + index), now=cooldown_end + index * 0.2
        ).active is False
    entered = state.update(
        _observation(65), now=cooldown_end + 1.0
    )
    assert entered.transition == "ENTER"
    assert entered.event_id != ""


def test_repeated_source_snapshot_does_not_advance_entry_or_repeat_enter() -> None:
    state = _state()
    same_source = _observation(1, source_id="same-frame")
    assert not state.update(same_source, now=10.0).active
    for index in range(1, 7):
        repeated = dict(same_source)
        repeated["snapshot_id"] = f"{EPOCH}:{index + 1}"
        assert not state.update(repeated, now=10.0 + index * 0.2).active

    # A new source starts the interval from scratch after repeated snapshots.
    for index in range(6):
        result = state.update(
            _observation(index + 2), now=12.0 + index * 0.2
        )
    assert result.transition == "ENTER"


@pytest.mark.parametrize(
    "status,age",
    [("invalid", 0.0), ("valid", 0.5001)],
)
def test_invalid_or_expired_observation_is_not_a_negative(status: str, age: float) -> None:
    state = _state()
    enter_time, event_id = _feed_owner_until_enter(state)
    for index in range(20):
        invalid = _observation(
            30 + index,
            owner_in_source=False,
            status=status,
            source_age=age,
        )
        result = state.update(invalid, now=enter_time + 0.2 + index * 0.2)
        assert result.active
        assert result.event_id == event_id
    assert result.transition == "HOLD"


def test_invalid_observation_breaks_pending_entry_and_exit_continuity() -> None:
    state = _state()
    assert not state.update(_observation(1), now=10.0).active
    assert not state.update(_observation(2), now=10.2).active
    invalid = _observation(3, status="invalid", owner_in_source=False)
    assert not state.update(invalid, now=10.4).active
    assert not state.update(_observation(4), now=10.6).active
    assert not state.update(_observation(5), now=11.4).active

    enter_time, event_id = _feed_owner_until_enter(state, start=12.0, first_sequence=10)
    negative = state.update(
        _observation(30, owner_in_source=False), now=enter_time + 0.2
    )
    assert negative.active
    invalid_active = state.update(
        _observation(31, owner_in_source=False, status="invalid"),
        now=enter_time + 0.4,
    )
    assert invalid_active.active
    assert invalid_active.event_id == event_id
    first_negative_after_recovery = state.update(
        _observation(32, owner_in_source=False), now=enter_time + 0.6
    )
    assert first_negative_after_recovery.active
    assert first_negative_after_recovery.event_id == event_id


def test_epoch_change_resets_pending_timers_but_keeps_active_instance() -> None:
    state = _state()
    assert not state.update(_observation(1), now=10.0).active
    assert not state.update(_observation(2), now=10.4).active
    assert not state.update(_observation(1, epoch="epoch-b"), now=10.6).active
    for index in range(1, 5):
        assert not state.update(
            _observation(index + 1, epoch="epoch-b"),
            now=10.6 + index * 0.2,
        ).active
    entered = state.update(
        _observation(6, epoch="epoch-b"), now=11.6
    )
    assert entered.transition == "ENTER"
    active_id = entered.event_id

    epoch_hold = state.update(
        _observation(1, epoch="epoch-c"), now=11.8
    )
    assert epoch_hold.active
    assert epoch_hold.event_id == active_id


def test_owner_config_defaults_to_recommended_values() -> None:
    config = OwnerPresenceEventConfig.from_mapping(None)
    assert config.enabled is True
    assert config.enter_duration_sec == 1.0
    assert config.exit_duration_sec == 2.0
    assert config.retrigger_delay_sec == 3.0
    assert EVT_VISION_MASTER == "EVT_VISION_MASTER"


@pytest.mark.parametrize(
    "value",
    [
        {"enter_duration_sec": 0},
        {"exit_duration_sec": float("nan")},
        {"retrigger_delay_sec": True},
        {"enabled": "yes"},
    ],
)
def test_owner_config_rejects_invalid_values(value: dict) -> None:
    with pytest.raises(ValueError):
        OwnerPresenceEventConfig.from_mapping(value)
