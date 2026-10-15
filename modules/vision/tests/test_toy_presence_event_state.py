from __future__ import annotations

import pytest

from marsdog_vision_interaction.core.held_object_pose import TOY_LABELS
from marsdog_vision_interaction.core.toy_presence_event_state import (
    EVT_VISION_TOY,
    ToyPresenceEventConfig,
    ToyPresenceEventState,
)


def _state(**config: float) -> ToyPresenceEventState:
    return ToyPresenceEventState(
        ToyPresenceEventConfig.from_mapping(config or None),
        source_freshness_sec=0.75,
        result_max_age_sec=2.0,
    )


def _result(
    sequence: int,
    at: float,
    *,
    objects: list[dict] | None = None,
    labels: list[str] | None = None,
    status: str = "ok",
    source_id: str | None = None,
    epoch: str = "camera-a",
    age: float = 0.0,
) -> tuple[dict, float]:
    return ({
        "vision_epoch": epoch,
        "source_observation_id": source_id or f"camera-frame-{sequence}",
        "source_observation_monotonic": at,
        "status": status,
        "objects": list(objects or []),
        "target_labels_valid": labels is not None,
        "target_labels": labels,
        "_age": age,
    }, at + age)


def _toy(label: str = "dog toy ball", *, confidence: float = 0.21) -> dict:
    return {
        "label": label,
        "x": 0.2,
        "y": 0.3,
        "w": 0.1,
        "h": 0.1,
        "confidence": confidence,
    }


def _feed(
    state: ToyPresenceEventState,
    sequence: int,
    at: float,
    *,
    present: bool = True,
    labels: list[str] | None = None,
    objects: list[dict] | None = None,
    status: str = "ok",
    age: float = 0.0,
    source_id: str | None = None,
    epoch: str = "camera-a",
):
    result, now = _result(
        sequence,
        at,
        objects=(objects if objects is not None else [_toy()] if present else []),
        labels=labels,
        status=status,
        age=age,
        source_id=source_id,
        epoch=epoch,
    )
    return state.update(result, now=now)


def test_toy_defaults_are_configurable_and_validated() -> None:
    config = ToyPresenceEventConfig.from_mapping(None)
    assert config.enabled is True
    assert config.enter_duration_sec == 1.0
    assert config.exit_duration_sec == 2.0
    assert config.retrigger_delay_sec == 3.0
    assert ToyPresenceEventConfig.from_mapping({
        "enter_duration_sec": 1.4,
        "exit_duration_sec": 2.5,
        "retrigger_delay_sec": 4.0,
    }).retrigger_delay_sec == 4.0
    with pytest.raises(ValueError, match="toy_presence_events.enter_duration_sec"):
        ToyPresenceEventConfig.from_mapping({"enter_duration_sec": 0})


def test_distinct_stable_toy_observations_enter_once_and_hold_one_scene_id() -> None:
    state = _state()
    assert not _feed(state, 1, 10.0).active
    assert not _feed(state, 2, 10.4).active
    entered = _feed(state, 3, 11.0, objects=[
        _toy("dog toy ball"),
        _toy("dog toy ball"),
        _toy("dog frisbee toy"),
    ])
    assert entered.active is True
    assert entered.transition == "ENTER"
    assert entered.event_id.startswith("camera-a:toy-presence:")

    held = _feed(state, 4, 11.4, objects=[
        _toy("dog frisbee toy"),
        _toy("dog tug ring toy"),
    ])
    assert held.active is True
    assert held.transition == "HOLD"
    assert held.event_id == entered.event_id


def test_repeated_source_result_and_repeated_visual_serialization_do_not_count() -> None:
    state = _state()
    first, now = _result(1, 20.0, objects=[_toy()], source_id="same-frame")
    assert not state.update(first, now=now).active
    # A new object sequence/snapshot for the identical source frame is replay.
    repeated = {**first, "snapshot_id": "visual-snapshot-99"}
    assert not state.update(repeated, now=now + 1.0).active
    assert not _feed(state, 2, 21.1).active
    assert not _feed(state, 3, 21.6).active
    entered = _feed(state, 4, 22.1)
    assert entered.active is True
    assert entered.transition == "ENTER"


def test_short_complete_negative_miss_cancels_exit_but_not_active_cycle() -> None:
    state = _state()
    for i, at in enumerate((0.0, 0.5, 1.0), 1):
        active = _feed(state, i, at)
    event_id = active.event_id
    assert active.active

    first_miss = _feed(state, 4, 1.5, present=False, labels=[])
    assert first_miss.active
    recovered = _feed(state, 5, 2.0, present=True)
    assert recovered.active
    assert recovered.event_id == event_id

    short_miss = _feed(state, 6, 2.5, present=False, labels=[])
    still_active = _feed(state, 7, 3.0, present=False, labels=[])
    assert short_miss.active and still_active.active
    assert still_active.event_id == event_id
    assert _feed(state, 8, 3.5, present=False, labels=[]).active
    assert _feed(state, 9, 4.0, present=False, labels=[]).active
    exited = _feed(state, 10, 4.5, present=False, labels=[])
    assert exited.active is False
    assert exited.transition == "EXIT"


def test_only_complete_negative_label_scope_advances_exit() -> None:
    state = _state()
    for i, at in enumerate((10.0, 10.5, 11.0), 1):
        active = _feed(state, i, at)
    assert active.active

    # An empty filtered result that excludes a supported toy is unknown.
    partial = [label for label in sorted(TOY_LABELS) if label != "dog toy ball"]
    unknown = _feed(state, 4, 11.5, present=False, labels=partial)
    assert unknown.active
    assert unknown.event_id == active.event_id
    # A single complete negative starts a new exit interval after unknown.
    negative = _feed(state, 5, 12.0, present=False, labels=[])
    assert negative.active
    assert negative.event_id == active.event_id


@pytest.mark.parametrize(
    ("status", "age", "labels"),
    [
        ("error", 0.0, []),
        ("stopped", 0.0, []),
        ("ok", 2.1, []),
        ("ok", 0.0, ["dog tug ring toy"]),
    ],
)
def test_unknown_or_stale_results_never_prove_toy_absence(
    status: str,
    age: float,
    labels: list[str],
) -> None:
    state = _state()
    for i, at in enumerate((1.0, 1.5, 2.0), 1):
        active = _feed(state, i, at)
    unknown = _feed(
        state,
        4,
        2.5,
        present=False,
        labels=labels,
        status=status,
        age=age,
    )
    assert unknown.active
    assert unknown.event_id == active.event_id
    # Unknown breaks pending EXIT; a fresh complete negative starts it anew.
    assert _feed(state, 5, 3.0, present=False, labels=[]).active


def test_invalid_inference_breaks_pending_entry_and_preserves_active_event() -> None:
    pending = _state()
    assert not _feed(pending, 1, 0.0).active
    assert not _feed(pending, 2, 0.5, status="error").active
    assert not _feed(pending, 3, 1.0).active
    assert not _feed(pending, 4, 1.5).active
    entered = _feed(pending, 5, 2.0)
    assert entered.active

    unknown = _feed(pending, 5, 2.5, status="error", present=False)
    assert unknown.active
    assert unknown.event_id == entered.event_id


def test_exit_starts_cooldown_then_requires_a_full_new_entry_interval() -> None:
    state = _state()
    for i, at in enumerate((0.0, 0.5, 1.0), 1):
        active = _feed(state, i, at)
    assert active.active
    assert _feed(state, 4, 1.5, present=False, labels=[]).active
    assert _feed(state, 5, 2.0, present=False, labels=[]).active
    assert _feed(state, 6, 2.5, present=False, labels=[]).active
    assert _feed(state, 7, 3.0, present=False, labels=[]).active
    assert _feed(state, 8, 3.5, present=False, labels=[]).transition == "EXIT"

    assert not _feed(state, 7, 5.0, present=True).active  # cooldown
    assert not _feed(state, 9, 6.4, present=True).active
    assert not _feed(state, 10, 7.0, present=True).active
    assert not _feed(state, 11, 7.5, present=True).active
    entered = _feed(state, 12, 8.0, present=True)
    assert entered.active
    assert entered.transition == "ENTER"
    assert entered.event_id != active.event_id


def test_unheld_toys_are_positive_without_people_or_identity_fields() -> None:
    state = _state()
    result = _feed(
        state,
        1,
        40.0,
        objects=[_toy("dog tug ring toy")],
        labels=["dog tug ring toy"],
    )
    assert not result.active
    assert not _feed(
        state,
        2,
        40.5,
        objects=[_toy("dog tug ring toy")],
        labels=["dog tug ring toy"],
    ).active
    entered = _feed(
        state,
        3,
        41.0,
        objects=[_toy("dog tug ring toy")],
        labels=["dog tug ring toy"],
    )
    assert entered.active
    assert entered.event_id


def test_non_toy_labels_and_malformed_boxes_do_not_create_presence() -> None:
    state = _state()
    food = _toy("dog bowl")
    malformed = {**_toy(), "w": 0.0}
    for sequence, at in enumerate((50.0, 50.5, 51.0, 51.5), 1):
        assert not _feed(
            state,
            sequence,
            at,
            objects=[food, malformed],
            labels=[],
        ).active


@pytest.mark.parametrize("invalid_objects", [
    [None],
    [{**_toy(), "confidence": float("nan")}],
    [{**_toy(), "w": 0.0}],
    [{**_toy("dog bowl"), "x": float("inf")}],
])
def test_malformed_results_are_unknown_and_cannot_complete_exit(
    invalid_objects: list,
) -> None:
    state = _state()
    for sequence, at in enumerate((10.0, 10.5, 11.0), 1):
        active = _feed(state, sequence, at)
    assert active.active
    assert _feed(state, 4, 11.5, present=False, labels=[]).active
    for sequence, at in enumerate((12.0, 12.5, 13.0, 13.5, 14.0), 5):
        unknown = _feed(
            state, sequence, at, objects=invalid_objects, labels=[]
        )
        assert unknown.active
        assert unknown.event_id == active.event_id
    # The first complete negative after invalid evidence starts EXIT anew.
    assert _feed(state, 10, 14.5, present=False, labels=[]).active

