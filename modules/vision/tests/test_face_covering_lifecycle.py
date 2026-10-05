"""Temporal regression tests for the face-covering lifecycle.

The lifecycle consumes an already-classified current-frame category.  These
tests inject that category at the detector boundary so timing behavior stays
independent from pose/hand geometry fixtures.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from marsdog_vision_interaction.providers.gesture_pose_engine import (
    ActionName,
    BehaviorEngine,
    FaceCoveringConfig,
    FaceCoveringDetector,
    FaceCoveringEvidence,
    LandmarkFrame,
)


@pytest.mark.parametrize("value", (0.0, -1.0, float("nan"), float("inf")))
@pytest.mark.parametrize(
    "field",
    ("activation_s", "exit_s", "unknown_grace_s"),
)
def test_face_covering_config_requires_finite_positive_durations(
    field: str,
    value: float,
) -> None:
    values = {
        "activation_s": 3.0,
        "exit_s": 1.0,
        "unknown_grace_s": 0.5,
    }
    values[field] = value

    with pytest.raises(ValueError, match=f"{field} must be finite and positive"):
        FaceCoveringConfig(**values)


def _evidence(category: str) -> FaceCoveringEvidence:
    covering = category == "cover"
    away = category == "away"
    clear = category == "clear"
    return FaceCoveringEvidence(
        category=category,
        score=0.9 if covering else 0.0,
        region_source="test",
        left_source="test",
        right_source="test",
        left_cover_score=0.9 if covering else 0.0,
        right_cover_score=0.9 if covering else 0.0,
        left_away_score=0.9 if away else 0.0,
        right_away_score=0.9 if away else 0.0,
        current_face=clear,
        transition_reason=f"test_{category}",
    )


def _frame(now: float, category: str) -> SimpleNamespace:
    return SimpleNamespace(
        category=category,
        inference=SimpleNamespace(
            captured=SimpleNamespace(monotonic_ns=int(round(now * 1_000_000_000))),
        ),
    )


def _detector(monkeypatch: pytest.MonkeyPatch) -> FaceCoveringDetector:
    detector = FaceCoveringDetector()

    def evaluate(frame: SimpleNamespace, _now: float) -> FaceCoveringEvidence:
        return _evidence(frame.category)

    monkeypatch.setattr(detector, "_evaluate", evaluate)
    return detector


def _feed(
    detector: FaceCoveringDetector,
    times: list[float],
    category: str = "cover",
) -> list[FaceCoveringEvidence]:
    return [detector.update(_frame(now, category)) for now in times]


@pytest.mark.parametrize(
    "times",
    (
        [0.0, 0.10, 0.20, 0.30, 0.75, 1.20, 1.69, 2.18, 2.67, 2.999, 3.0],
        [10.0, 10.37, 10.74, 11.11, 11.49, 11.87, 12.24, 12.62, 13.0],
    ),
)
def test_cover_activates_at_three_seconds_of_supported_time(
    monkeypatch: pytest.MonkeyPatch,
    times: list[float],
) -> None:
    detector = _detector(monkeypatch)

    for now in times[:-1]:
        detector.update(_frame(now, "cover"))
        assert detector.active is False

    detector.update(_frame(times[-1], "cover"))
    assert detector.active is True
    diagnostics = detector.diagnostics()
    assert diagnostics["activation_threshold_s"] == 3.0
    assert diagnostics["activation_dwell_s"] >= 3.0


def test_short_unknown_pauses_and_preserves_candidate_dwell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)

    detector.update(_frame(0.0, "cover"))
    detector.update(_frame(0.49, "cover"))
    detector.update(_frame(0.70, "unknown"))
    detector.update(_frame(1.19, "cover"))
    detector.update(_frame(1.68, "cover"))
    detector.update(_frame(2.17, "cover"))
    detector.update(_frame(2.66, "cover"))
    detector.update(_frame(3.15, "cover"))
    detector.update(_frame(3.64, "cover"))
    detector.update(_frame(3.70, "cover"))

    assert detector.active is True


def test_unknown_longer_than_grace_resets_on_recovery_without_timeout_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)

    detector.update(_frame(0.0, "cover"))
    detector.update(_frame(0.49, "cover"))
    detector.update(_frame(0.70, "unknown"))
    detector.update(_frame(1.10, "unknown"))
    recovered = detector.update(_frame(1.21, "cover"))

    assert recovered.category == "cover"
    assert detector.active is False
    diagnostics = detector.diagnostics()
    assert diagnostics["state"] == "candidate"
    assert diagnostics["onset_s"] == pytest.approx(1.21)
    assert diagnostics["activation_dwell_s"] == pytest.approx(0.0)
    assert diagnostics["activation_dwell_s"] == pytest.approx(0.0)


def test_long_sampling_gap_cannot_supply_activation_dwell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)

    detector.update(_frame(0.0, "cover"))
    detector.update(_frame(1.0, "cover"))
    gap = detector.update(_frame(3.1, "cover"))

    assert gap.category == "unknown"
    assert gap.transition_reason == "evidence_gap"
    assert detector.active is False


def test_timestamp_restart_invalidates_cached_geometry_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)
    detector.update(_frame(2.0, "cover"))
    detector._cached_region = (0.5, 0.2, 0.2, "pose", False)
    detector._cached_region_at_s = 2.0
    detector._cached_torso = (0.5, 0.3, 0.2)
    observed: list[object] = []

    def evaluate(frame: SimpleNamespace, _now: float) -> FaceCoveringEvidence:
        observed.append(detector._cached_region)
        return _evidence(frame.category)

    monkeypatch.setattr(detector, "_evaluate", evaluate)
    detector.update(_frame(1.0, "cover"))

    assert observed == [None]
    assert detector.diagnostics()["state"] == "candidate"


def _activate(detector: FaceCoveringDetector) -> None:
    for now in (0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8, 3.0):
        detector.update(_frame(now, "cover"))
    assert detector.active is True


def test_hands_away_requires_one_continuous_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)
    _activate(detector)

    detector.update(_frame(3.4, "away"))
    assert detector.active is True
    detector.update(_frame(3.8, "away"))
    assert detector.active is True
    detector.update(_frame(4.2, "away"))
    ended = detector.update(_frame(4.4, "away"))

    assert ended.category == "away"
    assert detector.active is False
    assert detector.diagnostics()["transition_reason"] == "hands_away"


def test_clear_face_requires_one_continuous_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)
    _activate(detector)

    detector.update(_frame(3.4, "clear"))
    assert detector.active is True
    detector.update(_frame(3.8, "clear"))
    detector.update(_frame(4.2, "clear"))
    ended = detector.update(_frame(4.4, "clear"))

    assert ended.category == "clear"
    assert detector.active is False
    assert detector.diagnostics()["transition_reason"] == "face_uncovered"


def test_exit_timers_do_not_alternate_or_survive_a_brief_recover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)
    _activate(detector)

    # Neither end condition reaches one second when the evidence alternates.
    detector.update(_frame(3.4, "away"))
    detector.update(_frame(3.8, "clear"))
    detector.update(_frame(4.2, "away"))
    detector.update(_frame(4.6, "clear"))
    assert detector.active is True

    # A brief re-cover cancels both provisional exit timers.
    detector.update(_frame(5.0, "cover"))
    detector.update(_frame(5.4, "away"))
    detector.update(_frame(5.8, "away"))
    detector.update(_frame(6.2, "away"))
    assert detector.active is True
    detector.update(_frame(6.4, "away"))
    assert detector.active is False


def test_unknown_is_not_an_explicit_end_but_timeout_clears_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)
    _activate(detector)

    detector.update(_frame(3.4, "unknown"))
    assert detector.active is True
    detector.update(_frame(3.8, "unknown"))
    timed_out = detector.update(_frame(4.2, "unknown"))

    assert timed_out.category == "unknown"
    assert detector.active is False
    assert detector.diagnostics()["transition_reason"] == "evidence_timeout"


@pytest.mark.parametrize("recovery", ("away", "clear"))
def test_long_unknown_cannot_recover_into_an_exit_timer(
    monkeypatch: pytest.MonkeyPatch,
    recovery: str,
) -> None:
    detector = _detector(monkeypatch)
    _activate(detector)

    detector.update(_frame(3.4, "unknown"))
    detector.update(_frame(3.8, "unknown"))
    recovered = detector.update(_frame(3.91, recovery))

    assert recovered.category == recovery
    assert detector.active is False
    diagnostics = detector.diagnostics()
    assert diagnostics["state"] == "idle"
    assert diagnostics["transition_reason"] == "evidence_timeout"
    assert diagnostics["exit_away_dwell_s"] == 0.0
    assert diagnostics["exit_clear_dwell_s"] == 0.0


def test_absent_target_clears_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _detector(monkeypatch)
    _activate(detector)

    absent = detector.update(_frame(3.1, "absent"))

    assert absent.category == "absent"
    assert detector.active is False
    assert detector.diagnostics()["transition_reason"] == "target_absent"


def test_no_pose_with_unspecified_target_is_unknown_in_behavior_engine() -> None:
    engine = BehaviorEngine()

    result = engine.update(
        LandmarkFrame(
            monotonic_s=1.0,
            pose_landmarks=None,
            left_hand=None,
            right_hand=None,
            target_present=None,
        )
    )

    assert result.face_covering_detector["category"] == "unknown"
    assert ActionName.FACE_COVERING not in {action.name for action in result.actions}


def test_behavior_engine_reset_requires_three_seconds_on_reentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = BehaviorEngine()
    detector = engine._recognizer._face_covering

    def evaluate(frame: object, _now: float) -> FaceCoveringEvidence:
        data = frame.inference.data  # type: ignore[attr-defined]
        return _evidence("cover" if data.target_present is True else "unknown")

    monkeypatch.setattr(detector, "_evaluate", evaluate)

    for now in (0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8, 3.0):
        result = engine.update(
            LandmarkFrame(monotonic_s=now, target_present=True)
        )
    assert ActionName.FACE_COVERING in {action.name for action in result.actions}

    engine.reset()
    # BehaviorEngine.reset() replaces the recognizer, so re-install the
    # sensor-boundary stub on the fresh detector instance.
    detector = engine._recognizer._face_covering
    monkeypatch.setattr(detector, "_evaluate", evaluate)
    for now in (10.0, 10.4, 10.8, 11.2, 11.6, 12.0, 12.4, 12.8):
        result = engine.update(
            LandmarkFrame(monotonic_s=now, target_present=True)
        )
        assert ActionName.FACE_COVERING not in {action.name for action in result.actions}
    result = engine.update(LandmarkFrame(monotonic_s=13.0, target_present=True))
    assert ActionName.FACE_COVERING in {action.name for action in result.actions}
