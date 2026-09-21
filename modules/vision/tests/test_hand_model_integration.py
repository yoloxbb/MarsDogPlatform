"""Provider-level contracts for the format-selected hand backend."""

from __future__ import annotations

import numpy as np

from marsdog_vision_interaction.providers import vision_observation
from marsdog_vision_interaction.providers.hand_backends.base import HandResult
from marsdog_vision_interaction.providers.hand_backends import factory as hand_factory


def _hand(x: float, handedness: str = "Left") -> HandResult:
    points = np.zeros((21, 3), dtype=np.float32)
    points[:, 0] = x
    points[:, 1] = 0.23456789
    points[:, 2] = -0.07654321
    return HandResult(
        landmarks=points,
        handedness=handedness,
        handedness_score=0.97,
        score=0.93,
        presence=0.91,
    )


class _SequenceBackend:
    backend_name = "rknn"
    preprocessing_mode = "rga"

    def __init__(self, outputs=None, fatal_error=None) -> None:
        self.outputs = list(outputs or [])
        self._fatal_error = fatal_error
        self.closed = 0
        self.calls = 0

    @property
    def fatal_error(self):
        return self._fatal_error

    def process(self, frame, *, mode=None, timestamp_ms=None):
        del frame, mode, timestamp_ms
        self.calls += 1
        if self.outputs:
            return self.outputs.pop(0)
        return []

    def close(self):
        self.closed += 1


def test_provider_preserves_internal_landmarks_while_rounding_public_payload() -> None:
    provider = vision_observation.VisionObservationProvider({
        "hand_landmark_model": "",
        "mediapipe_model": "",
        "face_detect_model": "",
        "stereo_enabled": False,
    })
    backend = _SequenceBackend([[_hand(0.123456789)]])
    provider._hand_backend = backend
    provider.hand_model_status = {"ready": True, "backend": "rknn"}

    hands = provider._detect_hands(
        np.zeros((32, 48, 3), dtype=np.uint8), 48, 32, 100
    )

    assert hands[0]["landmarks"][0]["x"] == 0.1235
    assert hands[0]["landmarks"][0]["y"] == 0.2346
    internal = hands[0]["_behavior_landmarks"][0]
    assert internal.x != hands[0]["landmarks"][0]["x"]
    assert internal.x == np.float32(0.123456789)
    assert internal.y == np.float32(0.23456789)


def test_provider_reports_hand_loss_reentry_and_second_hand_without_stale_rows() -> None:
    provider = vision_observation.VisionObservationProvider({
        "hand_landmark_model": "",
        "mediapipe_model": "",
        "face_detect_model": "",
        "stereo_enabled": False,
    })
    backend = _SequenceBackend([
        [_hand(0.2)],
        [],
        [_hand(0.21)],
        [_hand(0.22), _hand(0.72, "Right")],
    ])
    provider._hand_backend = backend
    provider.hand_model_status = {"ready": True, "backend": "rknn"}
    frame = np.zeros((32, 48, 3), dtype=np.uint8)

    counts = [len(provider._detect_hands(frame, 48, 32, stamp)) for stamp in range(4)]

    assert counts == [1, 0, 1, 2]
    assert backend.calls == 4


def test_provider_disables_fatal_hand_backend_and_does_not_retry() -> None:
    provider = vision_observation.VisionObservationProvider({
        "hand_landmark_model": "",
        "mediapipe_model": "",
        "face_detect_model": "",
        "stereo_enabled": False,
    })
    backend = _SequenceBackend(fatal_error="RKNN runtime released")
    provider._hand_backend = backend
    provider.hand_model_status = {"ready": True, "backend": "rknn"}
    frame = np.zeros((16, 16, 3), dtype=np.uint8)

    assert provider._detect_hands(frame, 16, 16, 1) == []
    assert provider._hand_backend is None
    assert provider.hand_model_status == {
        "ready": False,
        "backend": "rknn",
        "fatal": True,
        "error": "RKNN runtime released",
    }
    assert backend.closed == 1
    assert provider._detect_hands(frame, 16, 16, 2) == []
    assert backend.calls == 1
    assert backend.closed == 1


def test_provider_starts_and_releases_rknn_hand_backend_once(monkeypatch) -> None:
    backend = _SequenceBackend()
    calls = []

    def create_backend(path, **kwargs):
        calls.append((path, kwargs))
        return backend

    monkeypatch.setattr(vision_observation, "create_hand_backend", create_backend)
    provider = vision_observation.VisionObservationProvider({
        "hand_landmark_model": "hand_landmarks.rknn",
        "hand_detect_model": "hand_detector.rknn",
        "hand_rknn": {"preprocessing": "rga", "detection_interval": 5},
        "mediapipe_model": "",
        "face_detect_model": "",
        "stereo_enabled": False,
    })

    provider.start()
    assert provider.available
    assert provider.hand_model_status == {
        "ready": True,
        "backend": "rknn",
        "preprocessing": "rga",
    }
    assert calls[0][0] == "hand_landmarks.rknn"
    assert calls[0][1]["detector_model"] == "hand_detector.rknn"
    assert calls[0][1]["preprocessing"] == "rga"
    provider.stop()
    provider.stop()
    assert backend.closed == 1


def test_provider_task_model_keeps_mediapipe_rollback_with_rknn_detector(monkeypatch) -> None:
    backend = _SequenceBackend()
    backend.backend_name = "mediapipe"
    backend.preprocessing_mode = "cpu"
    calls = []

    def make_mediapipe(path, **kwargs):
        calls.append((path, kwargs))
        return backend

    monkeypatch.setattr(hand_factory, "MediaPipeHandBackend", make_mediapipe)
    provider = vision_observation.VisionObservationProvider({
        "hand_landmark_model": "hand_landmarker.task",
        "hand_detect_model": "hand_detector.rknn",
        "mediapipe_model": "",
        "face_detect_model": "",
        "stereo_enabled": False,
    })

    provider.start()
    assert provider.hand_model_status["backend"] == "mediapipe"
    assert len(calls) == 1
    assert str(calls[0][0]) == "hand_landmarker.task"
    assert calls[0][1] == {
        "running_mode": "video",
        "score_threshold": 0.5,
        "presence_threshold": 0.5,
        "max_hands": 2,
    }
    provider.stop()
    assert backend.closed == 1
