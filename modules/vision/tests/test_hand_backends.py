"""Deterministic contracts for the shared hand decoder and geometry."""

from __future__ import annotations

import math
import threading

import cv2
import numpy as np
import pytest

from marsdog_vision_interaction.providers.hand_backends.base import HandBackendError, HandResult
from marsdog_vision_interaction.providers.hand_backends.factory import create_hand_backend
from marsdog_vision_interaction.providers.hand_backends.rknn import (
    ANCHORS,
    LANDMARK_SIZE,
    RKNNHandBackend,
    _PalmDetection,
    _sample_tracking_roi,
    _weighted_nms,
    decode_palm_outputs,
    letterbox_geometry,
    project_landmarks,
)


def test_palm_anchor_order_groups_equal_stride_layers() -> None:
    assert ANCHORS.shape == (2016, 4)
    # Two stride-8 anchors per cell, followed by six stride-16 anchors per
    # cell. The first cell of the latter starts exactly at row 1152.
    assert np.allclose(ANCHORS[0], ANCHORS[1])
    assert np.allclose(ANCHORS[1152], ANCHORS[1157])
    assert not np.allclose(ANCHORS[0], ANCHORS[2])


def test_decode_converts_center_box_to_top_left_and_merges_duplicates() -> None:
    regressions = np.zeros((2016, 18), dtype=np.float32)
    scores = np.zeros((2016, 1), dtype=np.float32)
    regressions[0, 2:4] = 20.0
    scores[0] = 0.9
    regressions[1, 2:4] = 20.0
    scores[1] = 0.8
    output = decode_palm_outputs([regressions, scores], nms_threshold=0.1)
    assert len(output) == 1
    assert output[0].box[0] < ANCHORS[0, 0]
    assert output[0].box[1] < ANCHORS[0, 1]
    assert output[0].box[2] > 0


def test_projection_uses_height_for_y_and_graph_z_scale() -> None:
    matrix = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    raw = np.zeros((21, 3), dtype=np.float32)
    raw[0] = (112.0, 112.0, 1.0)
    projected = project_landmarks(matrix, raw, image_width=640, image_height=480, roi_size_px=448.0)
    assert projected[0, 0] == pytest.approx(112 / 640)
    assert projected[0, 1] == pytest.approx(112 / 480)
    assert projected[0, 2] == pytest.approx(448 / (224 * 0.4 * 640))


def test_tracking_roi_is_finite_for_rotated_landmarks() -> None:
    landmarks = np.zeros((21, 3), dtype=np.float32)
    for index in range(21):
        angle = math.radians(25)
        point = np.asarray((0.45 + 0.1 * math.cos(angle) * index / 20, 0.5 + 0.1 * math.sin(angle) * index / 20))
        landmarks[index, :2] = point
    result = HandResult(landmarks, "Left", 0.9, score=0.8, presence=0.9)
    roi, matrix, rotation, size = _sample_tracking_roi(np.zeros((480, 640, 3), np.uint8), result)
    assert roi.shape == (LANDMARK_SIZE, LANDMARK_SIZE, 3)
    assert np.isfinite(matrix).all() and np.isfinite(rotation) and size > 0


def test_task_factory_ignores_rknn_detector(monkeypatch, tmp_path) -> None:
    class FakeBackend:
        backend_name = "mediapipe"
        preprocessing_mode = "cpu"

    monkeypatch.setattr(
        "marsdog_vision_interaction.providers.hand_backends.factory.MediaPipeHandBackend",
        lambda *args, **kwargs: FakeBackend(),
    )
    backend = create_hand_backend(tmp_path / "hands.task", detector_model="palm.rknn")
    assert backend.backend_name == "mediapipe"


def test_unknown_suffix_is_explicit() -> None:
    with pytest.raises(HandBackendError, match="Unsupported hand landmark model suffix"):
        create_hand_backend("hands.bin")


def test_malformed_rga_tensor_is_fatal_and_not_retried() -> None:
    class BadPreprocessor:
        calls = 0

        def letterbox(self, frame, size):
            self.calls += 1
            return np.zeros((size, size), dtype=np.uint8)

        def close(self):
            pass

    backend = object.__new__(RKNNHandBackend)
    backend._lock = threading.RLock()
    backend._closed = False
    backend._fatal_error = None
    backend._detector = None
    backend._landmarker = None
    backend._tracks = []
    backend._rga = BadPreprocessor()
    backend._preprocessing = "rga"

    with pytest.raises(HandBackendError, match="returned"):
        backend._detector_input(np.zeros((10, 10, 3), dtype=np.uint8))

    assert backend.fatal_error is not None
    assert backend._closed
