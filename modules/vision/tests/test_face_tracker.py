"""Regression tests for face-track identity lifecycle."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from marsdog_vision_interaction.providers.face_tracker import (
    FaceRecognitionThrottle,
)
from marsdog_vision_interaction.providers.vision_observation import (
    VisionObservationProvider,
)


def _throttle(
    *,
    known_inactive_reverify_sec: float = 8.0,
    unknown_inactive_reverify_sec: float = 1.5,
) -> FaceRecognitionThrottle:
    return FaceRecognitionThrottle(
        face_recognizer=object(),
        min_face_score=0.85,
        min_face_size_px=40,
        known_inactive_reverify_sec=known_inactive_reverify_sec,
        unknown_inactive_retry_sec=unknown_inactive_reverify_sec,
        confirm_known_count=2,
        confirm_unknown_count=4,
    )


def _confirm_owner(throttle: FaceRecognitionThrottle, track_id: int = 7) -> None:
    throttle.mark_seen(track_id, np.array([10, 10, 90, 90]), 100.0)
    throttle.update_identity(track_id, "owner", 0.95, 100.0)
    throttle.mark_seen(track_id, np.array([10, 10, 90, 90]), 101.0)
    throttle.update_identity(track_id, "owner", 0.95, 101.0)
    state = throttle.get_track_state(track_id)
    assert state is not None
    assert (state.identity, state.identity_state) == (
        "owner",
        "confirmed_known",
    )


def test_reappeared_track_forces_recognition_and_clears_old_identity() -> None:
    throttle = _throttle()
    _confirm_owner(throttle)

    throttle.mark_missing_except(set(), 102.0)
    reappeared = throttle.mark_seen(
        7, np.array([10, 10, 90, 90]), 102.1
    )

    assert reappeared is True
    assert throttle.should_recognize(
        7, 0.95, 80, 80, False, 102.1, force=reappeared
    )
    state = throttle.get_track_state(7)
    assert state is not None
    assert (state.identity, state.identity_state, state.identity_confidence) == (
        "unknown",
        "unverified",
        0.0,
    )


def test_reappeared_track_accepts_family_without_owner_votes() -> None:
    throttle = _throttle()
    _confirm_owner(throttle)

    throttle.mark_missing_except(set(), 102.0)
    reappeared = throttle.mark_seen(
        7, np.array([10, 10, 90, 90]), 102.1
    )
    assert throttle.should_recognize(
        7, 0.95, 80, 80, False, 102.1, force=reappeared
    )
    throttle.update_identity(7, "family_member_1", 0.91, 102.1)
    state = throttle.get_track_state(7)
    assert state is not None
    assert (state.identity, state.identity_state) == (
        "family_member_1",
        "candidate_known",
    )

    throttle.mark_seen(7, np.array([10, 10, 90, 90]), 102.2)
    throttle.update_identity(7, "family_member_1", 0.92, 102.2)
    assert state.identity == "family_member_1"
    assert state.identity_state == "confirmed_known"


def test_unknown_result_clears_previous_confirmed_identity() -> None:
    throttle = _throttle()
    _confirm_owner(throttle)

    throttle.mark_missing_except(set(), 102.0)
    reappeared = throttle.mark_seen(
        7, np.array([10, 10, 90, 90]), 102.1
    )
    assert throttle.should_recognize(
        7, 0.95, 80, 80, False, 102.1, force=reappeared
    )
    throttle.update_identity(7, "unknown", 0.12, 102.1)
    state = throttle.get_track_state(7)
    assert state is not None
    assert (state.identity, state.identity_state, state.identity_confidence) == (
        "unknown",
        "unknown_candidate",
        0.0,
    )


def test_visible_track_keeps_normal_known_throttle() -> None:
    throttle = _throttle()
    _confirm_owner(throttle)

    throttle.mark_missing_except({7}, 102.0)
    reappeared = throttle.mark_seen(
        7, np.array([10, 10, 90, 90]), 102.1
    )
    assert reappeared is False
    assert not throttle.should_recognize(
        7, 0.95, 80, 80, False, 102.1, force=reappeared
    )


class _Detector:
    def __init__(self, results: Iterator[np.ndarray | None]) -> None:
        self._results = results

    def setInputSize(self, size: tuple[int, int]) -> None:
        _ = size

    def detect(self, frame: np.ndarray) -> tuple[None, np.ndarray | None]:
        _ = frame
        result = next(self._results)
        return None, result


class _Tracker:
    def update(
        self, detections: np.ndarray, scores: np.ndarray,
    ) -> np.ndarray:
        _ = scores
        if len(detections) == 0:
            return np.array([], dtype=np.int32)
        return np.full(len(detections), 7, dtype=np.int32)


def test_provider_reidentifies_same_face_track_after_empty_inference() -> None:
    face = np.array(
        [[10, 10, 80, 80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.95]],
        dtype=np.float32,
    )
    provider = VisionObservationProvider({"det_threshold": 0.3})
    provider._face_detector = _Detector(iter((face, face, None, face)))
    provider._face_tracker = _Tracker()
    provider._face_rec_throttle = _throttle(
        known_inactive_reverify_sec=0.0,
        unknown_inactive_reverify_sec=0.0,
    )
    provider._face_rec_model = object()
    identities = iter(("owner", "owner", "family_member_1"))
    provider._run_sface = lambda frame, detected_face, **kwargs: (
        next(identities), 0.9
    )
    frame = np.zeros((120, 120, 3), dtype=np.uint8)

    first = provider._detect_faces(frame, 120, 120)
    second = provider._detect_faces(frame, 120, 120)
    missing = provider._detect_faces(frame, 120, 120)
    replacement = provider._detect_faces(frame, 120, 120)

    assert first[0]["recognized_user"] == "owner"
    assert second[0]["recognized_user"] == "owner"
    assert missing == []
    assert replacement[0]["recognized_user"] == "family_member_1"
    assert replacement[0]["identity_state"] == "candidate_known"
