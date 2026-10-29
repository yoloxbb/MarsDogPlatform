from __future__ import annotations

import pytest

from marsdog_vision_interaction.core.presence_event_state import (
    PresenceEventConfig,
    PresenceEventState,
)
from marsdog_vision_interaction.core.facial_expression_event_state import (
    HAPPY_EVENT,
    SAD_EVENT,
    FacialExpressionEventConfig,
    FacialExpressionEventState,
)
from marsdog_vision_interaction.nodes.vision_interaction_node import (
    _merge_event_source_evidence,
    _pose_event_source_evidence,
)


def _state() -> PresenceEventState:
    return PresenceEventState(
        PresenceEventConfig(),
        event_tag="master-happy",
        source_target_ids_key="_source_human_event_target_ids",
        identities={"owner", "unknown"},
        identity_state={"confirmed_known", "confirmed_unknown"},
        evidence_state_key="_merged_evidence",
        source_freshness_sec=0.5,
    )


def _observation(sequence: int, evidence: str) -> dict:
    return {
        "vision_epoch": "epoch-a",
        "observation_status": "valid",
        "source_observation_id": f"source:{sequence}",
        "_source_observation_age_sec": 0.0,
        "_source_human_event_target_ids": [],
        "_merged_evidence": evidence,
    }


@pytest.mark.parametrize(
    ("face_evidence", "pose_evidence"),
    [
        ("unknown", "negative"),  # invalid/missing face, valid pose negative
        ("negative", "unknown"),  # valid face negative, invalid/missing pose
    ],
)
def test_unknown_source_breaks_exit_continuity_but_keeps_active_cycle(
    face_evidence: str,
    pose_evidence: str,
) -> None:
    state = _state()
    entered = None
    for index in range(6):
        entered = state.update(
            _observation(index + 1, "positive"),
            now=10.0 + index * 0.2,
        )
    assert entered is not None and entered.transition == "ENTER"
    event_id = entered.event_id

    mixed = _merge_event_source_evidence(face_evidence, pose_evidence)
    assert mixed == "unknown"
    held = state.update(_observation(7, mixed), now=11.2)
    assert held.active and held.transition == "HOLD"
    assert held.event_id == event_id

    # An unknown source just before T_exit clears the accumulated negatives.
    for index, now in enumerate((11.4, 11.8, 12.2, 12.6, 13.0, 13.2), 8):
        first_negative = state.update(
            _observation(index, "negative"), now=now
        )
    assert first_negative.active and first_negative.event_id == event_id
    interrupted = state.update(_observation(14, mixed), now=13.3)
    assert interrupted.active and interrupted.event_id == event_id

    # Only a fresh, continuous interval with both sources negative exits.
    exited = None
    for index, now in enumerate(
        (13.5, 13.9, 14.3, 14.7, 15.1, 15.5, 15.6), 15
    ):
        exited = state.update(
            _observation(index, "negative"), now=now
        )
        if exited.transition == "EXIT":
            break
    assert exited is not None
    assert exited.transition == "EXIT"
    assert exited.event_id == event_id


def test_positive_source_wins_while_another_source_is_unknown() -> None:
    assert _merge_event_source_evidence("positive", "unknown") == "positive"
    assert _merge_event_source_evidence(None, "negative") == "negative"
    assert _merge_event_source_evidence(None, None) == "unknown"


def test_unknown_source_breaks_pending_entry_continuity() -> None:
    state = _state()
    assert not state.update(_observation(1, "positive"), now=20.0).active
    assert not state.update(_observation(2, "positive"), now=20.4).active
    mixed = _merge_event_source_evidence("unknown", "negative")
    assert not state.update(_observation(3, mixed), now=20.5).active

    assert not state.update(_observation(4, "positive"), now=20.7).active
    assert not state.update(_observation(5, "positive"), now=21.1).active
    assert not state.update(_observation(6, "positive"), now=21.5).active
    entered = state.update(_observation(7, "positive"), now=21.71)
    assert entered.transition == "ENTER"


@pytest.mark.parametrize("event_name", [HAPPY_EVENT, SAD_EVENT])
@pytest.mark.parametrize(
    ("identity", "identity_state"),
    [("family_member_1", "confirmed_known"), ("unknown", "confirmed_unknown")],
)
def test_non_owner_pose_cycle_exits_with_face_source_inapplicable(
    event_name: str, identity: str, identity_state: str,
) -> None:
    state = _state()
    face = FacialExpressionEventState(FacialExpressionEventConfig(enabled=True))
    event_id = ""
    for index in range(18):
        observation = _observation(index, "unknown")
        observation["_source_human_target_ids"] = ["target-1"]
        observation["active_target"] = {
            "target_id": "target-1", "vision_epoch": "epoch-a",
            "identity": identity, "identity_state": identity_state,
            "tracking_state": "tracking",
        }
        pose_events = {event_name} if index < 6 else set()
        face_evidence = face.evidence_for_event(observation, event_name)
        assert face_evidence is None
        observation["_merged_evidence"] = _merge_event_source_evidence(
            _pose_event_source_evidence(observation, event_name, pose_events),
            face_evidence,
        )
        snapshot = state.update(observation, now=10.0 + index * 0.2)
        if snapshot.transition == "ENTER":
            event_id = snapshot.event_id
        if snapshot.transition == "EXIT":
            assert snapshot.event_id == event_id
            break
    else:
        pytest.fail("a valid non-owner pose clear must reach EXIT")
    assert event_id


def test_missing_owner_face_keeps_cycle_after_legacy_source_release() -> None:
    state = _state()
    face = FacialExpressionEventState(FacialExpressionEventConfig(enabled=True))
    event_id = ""
    for index in range(25):
        observation = _observation(index, "unknown")
        observation["header"] = {"stamp": 100.0 + index * 0.2, "frame_id": "camera"}
        observation["active_target"] = {
            "vision_epoch": "epoch-a", "identity": "owner",
            "identity_state": "confirmed_known", "tracking_state": "tracking",
            "face_track_id": 7,
        } if index < 6 else {}
        observation["faces"] = [{
            "track_id": 7,
            "facial_expression": {"expression": "happy", "confidence": 0.9},
        }] if index < 6 else []
        observation["facial_expression_valid_for_sec"] = 0.5 if index < 6 else 0.0
        face.update(observation, now=10.0 + index * 0.2)
        evidence = face.evidence_for_event(observation, HAPPY_EVENT)
        assert evidence == ("positive" if index < 6 else "unknown")
        observation["_merged_evidence"] = _merge_event_source_evidence("negative", evidence)
        snapshot = state.update(observation, now=10.0 + index * 0.2)
        if snapshot.transition == "ENTER":
            event_id = snapshot.event_id
        if index >= 6:
            assert snapshot.active and snapshot.event_id == event_id
    assert event_id
    assert face._active is None  # source release cannot retire the public cycle
