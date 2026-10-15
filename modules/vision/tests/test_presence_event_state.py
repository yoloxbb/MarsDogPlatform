from __future__ import annotations

import pytest

from marsdog_vision_interaction.core.presence_event_state import (
    PresenceEventConfig,
    PresenceEventState,
)


FAMILY = "EVT_VISION_FAMILY_PRESENT"
STRANGER = "EVT_VISION_STRANGER"


def _state(event_name: str) -> PresenceEventState:
    if event_name == FAMILY:
        tag = "family-presence"
        evidence_key = "_source_family_target_ids"
        identity = "family_member_2"
        identity_state = "confirmed_known"
    else:
        tag = "stranger-presence"
        evidence_key = "_source_stranger_target_ids"
        identity = "unknown"
        identity_state = "confirmed_unknown"
    return PresenceEventState(
        PresenceEventConfig.from_mapping(
            None,
            section_name="presence_events",
        ),
        event_tag=tag,
        source_target_ids_key=evidence_key,
        identities={identity} if identity == "unknown" else {
            "family_member_1", "family_member_2",
            "family_member_3", "family_member_4",
        },
        identity_state=identity_state,
        source_freshness_sec=0.5,
    )


def _observation(
    event_name: str,
    sequence: int,
    *,
    identity: str | None = None,
    identity_state: str | None = None,
    tracking_state: str = "tracking",
    present: bool = True,
    status: str = "valid",
    source_id: str | None = None,
    epoch: str = "epoch-a",
) -> dict:
    if event_name == FAMILY:
        evidence_key = "_source_family_target_ids"
        default_identity = "family_member_2"
        default_state = "confirmed_known"
        tag = "family"
    else:
        evidence_key = "_source_stranger_target_ids"
        default_identity = "unknown"
        default_state = "confirmed_unknown"
        tag = "stranger"
    target_id = f"{epoch}:human:{sequence}"
    return {
        "vision_epoch": epoch,
        "snapshot_id": f"{epoch}:{sequence}",
        "observation_status": status,
        "source_observation_id": source_id or f"source:{tag}:{sequence}",
        "_source_observation_age_sec": 0.0,
        evidence_key: [target_id] if present else [],
        "human_candidates": [{
            "vision_epoch": epoch,
            "target_id": target_id,
            "track_id": sequence,
            "face_track_id": sequence + 100,
            "identity": identity or default_identity,
            "identity_state": identity_state or default_state,
            "tracking_state": tracking_state,
        }],
    }


@pytest.mark.parametrize("event_name", [FAMILY, STRANGER])
def test_presence_enters_once_and_holds_a_category_scoped_id(event_name: str) -> None:
    state = _state(event_name)
    for index in range(6):
        result = state.update(
            _observation(event_name, index + 1),
            now=10.0 + index * 0.2,
        )
    assert result.active is True
    assert result.transition == "ENTER"
    assert result.event_id.startswith("epoch-a:")

    held = state.update(_observation(event_name, 7), now=11.2)
    assert held.active is True
    assert held.transition == "HOLD"
    assert held.event_id == result.event_id


@pytest.mark.parametrize(
    ("event_name", "identity", "identity_state", "tracking_state"),
    [
        (FAMILY, "owner", "confirmed_known", "tracking"),
        (FAMILY, "family_member_1", "candidate_known", "tracking"),
        (FAMILY, "family_member_1", "confirmed_known", "temporarily_lost"),
        (STRANGER, "family_member_1", "confirmed_known", "tracking"),
        (STRANGER, "unknown", "unknown_candidate", "tracking"),
        (STRANGER, "unknown", "confirmed_unknown", "temporarily_lost"),
    ],
)
def test_presence_rejects_wrong_identity_or_untracked_target(
    event_name: str,
    identity: str,
    identity_state: str,
    tracking_state: str,
) -> None:
    state = _state(event_name)
    for index in range(8):
        result = state.update(
            _observation(
                event_name,
                index + 1,
                identity=identity,
                identity_state=identity_state,
                tracking_state=tracking_state,
            ),
            now=10.0 + index * 0.2,
        )
        assert result.active is False


@pytest.mark.parametrize("event_name", [FAMILY, STRANGER])
@pytest.mark.parametrize("identity", [[], {}, 42])
def test_presence_rejects_non_string_identity(event_name: str, identity) -> None:
    state = _state(event_name)
    for index in range(8):
        observation = _observation(event_name, index + 1)
        observation["human_candidates"][0]["identity"] = identity
        assert state.update(observation, now=10.0 + index * 0.2).active is False


@pytest.mark.parametrize("event_name", [FAMILY, STRANGER])
def test_duplicate_source_and_invalid_observation_do_not_advance_or_exit(
    event_name: str,
) -> None:
    state = _state(event_name)
    first = _observation(event_name, 1, source_id="same-source")
    assert state.update(first, now=10.0).active is False
    repeated = dict(first, snapshot_id="epoch-a:2")
    assert state.update(repeated, now=11.0).active is False

    # The long gap causes the next distinct valid source to restart T_enter.
    assert state.update(_observation(event_name, 3), now=11.2).active is False
    entered = None
    for index in range(5):
        entered = state.update(
            _observation(event_name, 4 + index),
            now=11.4 + index * 0.2,
        )
    assert entered is not None and entered.transition == "ENTER"

    invalid = state.update(
        _observation(event_name, 20, status="invalid", present=False),
        now=12.6,
    )
    assert invalid.active is True
    assert invalid.event_id == entered.event_id


def test_family_and_stranger_have_independent_active_cycles() -> None:
    family_state = _state(FAMILY)
    stranger_state = _state(STRANGER)
    family_event = None
    stranger_event = None
    for index in range(6):
        now = 10.0 + index * 0.2
        family_event = family_state.update(
            _observation(FAMILY, index + 1), now=now
        )
        stranger_event = stranger_state.update(
            _observation(STRANGER, index + 1), now=now
        )
    assert family_event is not None and family_event.active
    assert stranger_event is not None and stranger_event.active
    assert family_event.event_id != stranger_event.event_id


@pytest.mark.parametrize("section", ["family_presence_events", "stranger_presence_events"])
def test_presence_configuration_defaults_and_validation(section: str) -> None:
    config = PresenceEventConfig.from_mapping(None, section_name=section)
    assert config.enabled is True
    assert config.enter_duration_sec == 1.0
    assert config.exit_duration_sec == 2.0
    assert config.retrigger_delay_sec == 3.0

    with pytest.raises(ValueError, match=section):
        PresenceEventConfig.from_mapping(
            {"enter_duration_sec": 0},
            section_name=section,
        )
