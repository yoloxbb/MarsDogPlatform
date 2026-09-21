from __future__ import annotations

import numpy as np
import pytest

from marsdog_vision_interaction.providers import vision_observation as module
from marsdog_vision_interaction.providers.pose_backends.base import PoseResult
from marsdog_vision_interaction.providers.vision_observation import VisionObservationProvider
from marsdog_vision_interaction.providers.pose_backends.base import PoseBackendError
from marsdog_vision_interaction.core.visual_target_manager import VisualTargetManager
from marsdog_vision_interaction.core.held_object_pose import _wrist_points
from marsdog_vision_interaction.messages.visual_event import normalize_visual_event
from marsdog_vision_interaction.providers.gesture_pose_engine import (
    BehaviorEngine,
    LandmarkFrame,
)


class _FakePoseBackend:
    backend_name = "rknn"
    keypoint_format = "coco_17"
    fatal_error = None

    def __init__(self) -> None:
        self.closed = False

    def process(self, frame: np.ndarray) -> list[PoseResult]:
        points = np.zeros((17, 3), dtype=np.float32)
        points[:, :2] = 0.5
        points[:, 2] = 0.9
        return [PoseResult(np.asarray((0.1, 0.2, 0.3, 0.6), dtype=np.float32), 0.88, points)]

    def close(self) -> None:
        self.closed = True


def test_provider_routes_rknn_model_and_publishes_native_coco(monkeypatch) -> None:
    fake = _FakePoseBackend()
    monkeypatch.setattr(module, "create_pose_backend", lambda *args, **kwargs: fake)
    provider = VisionObservationProvider({
        "pose_model_variant": "rknn",
        "pose_models": {"rknn": "/tmp/yolov8n-pose-fp16.rknn"},
        "max_num_poses": 2,
    })
    assert provider._pose_backend_kind == "rknn"
    provider._pose_backend = fake
    humans = provider._detect_pose_rknn(np.zeros((100, 120, 3), dtype=np.uint8), 120, 100)
    assert humans[0]["keypoint_format"] == "coco_17"
    assert [point["id"] for point in humans[0]["keypoints"]] == list(range(17))
    assert humans[0]["keypoints"][0]["z"] is None
    behavior = humans[0]["_behavior_landmarks"]
    assert len(behavior) == 33
    assert behavior[15].visibility == pytest.approx(0.9)
    assert behavior[15].z is None


def test_provider_rejects_unknown_pose_model_suffix() -> None:
    provider = VisionObservationProvider({"pose_model": "/tmp/pose.onnx"})
    assert provider._pose_backend_kind == "unsupported"
    provider.start()
    assert provider.pose_model_status["ready"] is False
    assert provider._pose_landmarker is None
    provider.stop()


def test_direct_pose_model_path_overrides_variant_and_reports_actual_mode() -> None:
    task = VisionObservationProvider({
        "pose_model_variant": "rknn",
        "pose_model": "/tmp/pose_landmarker_full.task",
        "pose_models": {"rknn": "/tmp/pose.rknn"},
    })
    assert task._pose_backend_kind == "mediapipe"
    assert task._pose_model_variant == "full"
    assert task._landmarker_diagnostics()["running_mode"] == "video"
    rknn = VisionObservationProvider({
        "pose_model_variant": "lite",
        "pose_model": "/tmp/pose.rknn",
    })
    assert rknn._pose_backend_kind == "rknn"
    assert rknn._pose_model_variant == "rknn"
    assert rknn._landmarker_diagnostics()["running_mode"] == "image"


def test_fatal_pose_does_not_retry_or_fall_back_to_mediapipe() -> None:
    class FatalBackend(_FakePoseBackend):
        def __init__(self):
            super().__init__()
            self.calls = 0
            self.closes = 0
            self.fatal_error = None

        def process(self, frame):
            self.calls += 1
            self.fatal_error = "bad output"
            raise PoseBackendError("bad output")

        def close(self):
            self.closes += 1

    provider = VisionObservationProvider({"pose_model": "/tmp/pose.rknn"})
    backend = FatalBackend()
    provider._pose_backend = backend
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    assert provider._detect_pose_rknn(frame, 120, 100) == []
    assert provider.pose_model_status["ready"] is False
    assert provider.pose_model_status["fatal"] is True
    assert provider._pose_backend is None
    assert provider._detect_pose_rknn(frame, 120, 100) == []
    assert backend.calls == backend.closes == 1
    assert provider._pose_landmarker is None


def test_coco_public_points_reach_target_event_and_wrist_association() -> None:
    points = [
        {"id": index, "x": x, "y": y, "confidence": 0.9, "presence": 0.9}
        for index, x, y in (
            (5, 0.3, 0.2), (6, 0.7, 0.2),
            (11, 0.4, 0.6), (12, 0.6, 0.6),
            (9, 0.35, 0.4), (10, 0.65, 0.4),
        )
    ]
    human = {
        "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8,
        "confidence": 0.9, "keypoint_format": "coco_17", "keypoints": points,
    }
    manager = VisualTargetManager()
    candidates = manager._build_candidates([human], [])
    assert candidates[0]["body_center"] == pytest.approx((0.5, 0.4))
    assert candidates[0]["keypoint_format"] == "coco_17"
    event = normalize_visual_event({
        "humans": [human],
        "human_candidates": [{**human, "body_center": [0.5, 0.4]}],
        "active_target": {"keypoint_format": "coco_17", "keypoints": points},
    })
    for value in (event["humans"][0], event["human_candidates"][0], event["active_target"]):
        assert value["keypoint_format"] == "coco_17"
        assert value["keypoints"] == points
    wrists = _wrist_points(event["active_target"], [])
    assert {kind for kind, _point in wrists} == {"pose_left_wrist", "pose_right_wrist"}


def test_coco_behavior_landmarks_keep_depth_unavailable_and_rules_run() -> None:
    points = [
        {"id": index, "x": 0.5, "y": 0.3 + index * 0.02,
         "confidence": 0.9, "presence": 0.9}
        for index in range(17)
    ]
    pose = VisionObservationProvider._coco_behavior_landmarks(points)
    assert pose[15].z is None
    assert pose[15].visibility == pytest.approx(0.9)
    assert pose[17].visibility == 0.0
    result = BehaviorEngine().update(LandmarkFrame(monotonic_s=1.0, pose_landmarks=pose))
    assert result.features.pose is not None
    assert result.features.pose.left_elbow_angle_3d_degrees is None
    assert result.features.pose.left_thigh_depth_ratio is None


def test_pose_quality_uses_active_keypoint_denominator() -> None:
    provider = VisionObservationProvider({"pose_model": "/tmp/pose.rknn"})
    provider._record_pose_quality([{
        "confidence": 0.9,
        "keypoints": [
            {"id": index, "confidence": 0.9, "presence": 0.9}
            for index in range(17)
        ],
    }])
    assert provider._pose_keypoint_valid[-1] == pytest.approx(1.0)
    task = VisionObservationProvider({"pose_model": "/tmp/pose_landmarker_lite.task"})
    task._record_pose_quality([{
        "confidence": 0.9,
        "keypoints": [
            {"id": index, "confidence": 0.9, "presence": 0.9}
            for index in range(33)
        ],
    }])
    assert task._pose_keypoint_valid[-1] == pytest.approx(1.0)


def test_stop_leaves_pose_context_open_if_worker_does_not_stop(monkeypatch) -> None:
    provider = VisionObservationProvider({"pose_model": "/tmp/pose.rknn"})
    backend = _FakePoseBackend()
    provider._pose_backend = backend
    monkeypatch.setattr(provider, "_stop_inference_worker", lambda: False)
    provider.stop()
    assert backend.closed is False
    assert provider._pose_backend is backend
