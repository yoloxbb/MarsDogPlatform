from __future__ import annotations

import numpy as np
import pytest
import threading

from marsdog_vision_interaction.providers.pose_backends.contract import (
    COCO_17,
    MEDIAPIPE_33,
    keypoint_ids,
    normalize_keypoint_format,
)
from marsdog_vision_interaction.providers.pose_backends.rknn import (
    OUTPUT_WIDTH,
    RKNNPoseBackend,
    _profile_for_model,
    decode_yolov8_pose_outputs,
    letterbox_frame,
    undo_letterbox,
)


def _output(*rows: tuple[float, float, float, float, float]) -> np.ndarray:
    values = np.zeros((1, OUTPUT_WIDTH, 8400), dtype=np.float32)
    for index, row in enumerate(rows):
        values[0, :5, index] = row
        values[0, 5:, index] = np.tile(
            np.asarray((320.0, 320.0, 0.9), dtype=np.float32), 17
        )
    return values


def test_yolov8_decoder_filters_and_suppresses_overlapping_people() -> None:
    detections = decode_yolov8_pose_outputs(
        _output(
            (320.0, 320.0, 200.0, 400.0, 0.9),
            (321.0, 321.0, 200.0, 400.0, 0.8),
            (80.0, 80.0, 50.0, 60.0, 0.1),
        ),
        score_threshold=0.3,
        nms_threshold=0.45,
        max_num_poses=4,
    )
    assert len(detections) == 1
    assert detections[0].score == pytest.approx(0.9)
    assert detections[0].keypoints.shape == (17, 3)


def test_yolov8_decoder_rejects_malformed_output_shape() -> None:
    with pytest.raises(RuntimeError, match="output shape"):
        decode_yolov8_pose_outputs(np.zeros((1, OUTPUT_WIDTH * 8400), dtype=np.float32))
    with pytest.raises(RuntimeError, match="output shape"):
        decode_yolov8_pose_outputs(np.zeros((1, 8400, OUTPUT_WIDTH), dtype=np.float32))


def test_yolov8_decoder_handles_empty_and_separate_people() -> None:
    assert decode_yolov8_pose_outputs(_output()) == []
    detections = decode_yolov8_pose_outputs(_output(
        (100.0, 300.0, 100.0, 200.0, 0.9),
        (500.0, 300.0, 100.0, 200.0, 0.8),
    ))
    assert len(detections) == 2
    assert detections[0].box[0] < detections[1].box[0]
    assert len(decode_yolov8_pose_outputs(_output(
        (100.0, 300.0, 100.0, 200.0, 0.9),
        (500.0, 300.0, 100.0, 200.0, 0.8),
    ), max_num_poses=1)) == 1


def test_letterbox_inversion_uses_source_geometry() -> None:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    tensor, geometry = letterbox_frame(frame)
    assert tensor.shape == (640, 640, 3)
    assert tensor[0, 0, 0] == 114
    detections = decode_yolov8_pose_outputs(
        _output((320.0, 320.0, 200.0, 300.0, 0.9)),
        score_threshold=0.3,
    )
    undo_letterbox(detections[0], width=640, height=480, geometry=geometry)
    assert detections[0].keypoints[0, :2] == pytest.approx((0.5, 0.5))
    assert detections[0].box[2:] == pytest.approx((0.3125, 0.625))


def test_letterbox_inversion_uses_rounded_axis_dimensions() -> None:
    frame = np.zeros((337, 503, 3), dtype=np.uint8)
    _, geometry = letterbox_frame(frame[:, ::-1])
    _, resized_width, resized_height, pad_x, pad_y = geometry
    detections = decode_yolov8_pose_outputs(_output((
        pad_x + resized_width * 0.5,
        pad_y + resized_height * 0.5,
        resized_width * 0.4,
        resized_height * 0.6,
        0.9,
    )))
    undo_letterbox(detections[0], width=503, height=337, geometry=geometry)
    assert detections[0].box == pytest.approx((0.3, 0.2, 0.4, 0.6), abs=1e-5)
    assert detections[0].keypoints[0, :2] == pytest.approx(
        ((320 - pad_x) / resized_width, (320 - pad_y) / resized_height)
    )


def test_profile_rejects_unverified_artifact(tmp_path) -> None:
    model = tmp_path / "renamed.rknn"
    model.write_bytes(b"not the verified model")
    with pytest.raises(RuntimeError, match="Unverified RKNN pose model"):
        _profile_for_model(model, {"profile": "yolov8n_pose_fp16"})


def test_fatal_output_releases_runtime_once() -> None:
    class Runtime:
        releases = 0

        def inference(self, **kwargs):
            return [np.zeros((1, 3, 8400), dtype=np.float32)]

        def release(self):
            self.releases += 1

    backend = RKNNPoseBackend.__new__(RKNNPoseBackend)
    backend._lock = threading.RLock()
    runtime = Runtime()
    backend._runtime = runtime
    backend._closed = False
    backend._fatal_error = None
    backend._score_threshold = 0.3
    backend._nms_threshold = 0.45
    backend._max_num_poses = 4
    with pytest.raises(RuntimeError, match="output shape"):
        backend.process(np.zeros((33, 51, 3), dtype=np.uint8))
    assert backend.fatal_error
    assert backend._runtime is None
    backend.close()
    assert runtime.releases == 1


def test_public_keypoint_format_maps_and_legacy_default() -> None:
    assert normalize_keypoint_format(None) == MEDIAPIPE_33
    assert keypoint_ids(COCO_17, "wrist") == (9, 10)
    assert keypoint_ids(MEDIAPIPE_33, "torso") == (11, 12, 23, 24)
    with pytest.raises(ValueError):
        normalize_keypoint_format("unknown")
