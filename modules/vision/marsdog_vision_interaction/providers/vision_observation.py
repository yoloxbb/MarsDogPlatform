"""Observation vision provider — face detection + selectable pose + hands.

Continuous detection at observation rate, caching the latest result.

Models:
  - YuNet             face detection (OpenCV ONNX or RKNN FP16)
  - MediaPipe PoseLandmarker  (33-point pose + human detection, Lite/Full)
  - YOLOv8 Pose RKNN          (17-point COCO pose + human detection)
  - MediaPipe HandLandmarker or RKNN palm + landmark graphs

Model format selects the runtime; timing depends on the active models/device.
"""

from __future__ import annotations

from collections import deque
import copy
import logging
from pathlib import Path
import threading
import time
from typing import Any

import numpy as np

from marsdog_vision_interaction.providers.base import BaseProvider
from marsdog_vision_interaction.providers.face_backends import (
    create_face_detector,
    create_face_recognizer,
)
from marsdog_vision_interaction.providers.gesture_pose_engine import (
    HandLandmark,
    HandLandmarkSet,
    PoseLandmark,
    PoseLandmarkSet,
    hand_landmarks_from_objects,
    pose_landmarks_from_objects,
)
from marsdog_vision_interaction.providers.pose_action import PoseActionClassifier
from marsdog_vision_interaction.utils.logging_utils import vision_timing_trace
from marsdog_vision_interaction.utils.stereo_view import select_camera_view
from marsdog_vision_interaction.providers.hand_backends import (
    HandResult,
    create_hand_backend,
)
from marsdog_vision_interaction.providers.pose_backends import (
    COCO_TO_MEDIAPIPE,
    PoseBackendError,
    create_pose_backend,
)

logger = logging.getLogger(__name__)

_FACE_INPUT_SIZE = (320, 320)

class VisionObservationProvider(BaseProvider):
    """Continuous vision — YuNet face + MediaPipe pose + hands.

    Accepts camera frames from the bridge node via process_frame().
    Runs detection according to ``inference_frame_stride`` and caches the result.
    get_observation() returns the latest cached dict.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)

        self._face_detect_model = config.get("face_detect_model", "")
        self._pose_model_variant = str(config.get("pose_model_variant", "lite")).strip().lower()
        pose_models = config.get("pose_models", {})
        configured_pose_model = config.get("pose_model", "") or config.get("mediapipe_model", "")
        if isinstance(pose_models, dict):
            configured_pose_model = config.get("pose_model", "") or pose_models.get(
                self._pose_model_variant, configured_pose_model
            )
        self._pose_model_path = str(configured_pose_model or "")
        # Kept as an alias for existing integrations and tests.
        self._mediapipe_model = self._pose_model_path
        if self._pose_model_variant not in {"lite", "full", "heavy", "rknn"}:
            self._pose_model_variant = self._infer_pose_model_variant(
                self._pose_model_path
            )
        pose_suffix = Path(self._pose_model_path).suffix.lower()
        self._pose_backend_kind = {
            ".rknn": "rknn",
            ".task": "mediapipe",
        }.get(pose_suffix, "unsupported")
        # An explicit path overrides the variant mapping; report the actual
        # selected model instead of the launch variant left in configuration.
        if config.get("pose_model"):
            self._pose_model_variant = (
                "rknn" if pose_suffix == ".rknn"
                else self._infer_pose_model_variant(self._pose_model_path)
            )
        self._landmarker_running_mode = str(
            config.get("landmarker_running_mode", "video")
        ).strip().lower()
        if self._landmarker_running_mode not in {"image", "video"}:
            logger.warning(
                "Invalid landmarker_running_mode=%r; falling back to video",
                self._landmarker_running_mode,
            )
            self._landmarker_running_mode = "video"
        self._hand_landmark_model = config.get(
            "hand_landmark_model",
            "models/vision/hand_landmarker.task",
        )
        self._hand_detect_model = config.get("hand_detect_model", "")
        hand_rknn_config = config.get("hand_rknn", {})
        if not isinstance(hand_rknn_config, dict):
            hand_rknn_config = {}
        self._hand_rknn_config = hand_rknn_config
        self._hand_preprocessing = str(
            hand_rknn_config.get("preprocessing", config.get("hand_preprocessing", "cpu"))
        ).strip().lower()
        self._hand_detection_interval = max(
            1, int(hand_rknn_config.get("detection_interval", 5))
        )
        self._hand_score_threshold = float(
            hand_rknn_config.get("score_threshold", config.get("hand_score_threshold", 0.30))
        )
        self._hand_presence_threshold = float(
            hand_rknn_config.get("presence_threshold", config.get("hand_presence_threshold", 0.50))
        )
        self._det_threshold = float(config.get("det_threshold", 0.5))
        self._nms_threshold = float(config.get("nms_threshold", 0.45))
        self._show_all_detections = bool(
            config.get("show_all_detections", False)
        )
        self._pose_confidence_threshold = float(
            config.get("pose_confidence_threshold", 0.5),
        )
        self._max_num_poses = max(1, int(config.get("max_num_poses", 4)))
        self._hand_idle_inference_stride = max(
            1, int(config.get("hand_idle_inference_stride", 2))
        )
        self._hand_active_hold_inferences = max(
            0, int(config.get("hand_active_hold_inferences", 8))
        )
        self._hand_schedule_counter = 0
        self._hand_active_remaining = 0
        self._hand_inference_count = 0
        # A stride of 2 means frames 1, 3, 5... run the complete face/pose/hand
        # pipeline while the frames in between are deliberately dropped.  The
        # camera callback still receives every frame, so stream freshness is
        # independent from inference load.
        self._inference_frame_stride = max(
            1, int(config.get("inference_frame_stride", 1))
        )
        self._received_frame_count = 0
        self._inference_candidate_count = 0
        self._inferred_frame_count = 0
        self._replaced_pending_frame_count = 0
        self._landmarker_timestamp_ms = 0
        metric_window_size = max(
            10, int(config.get("landmarker_metric_window_size", 150))
        )
        self._landmarker_times: deque[float] = deque(
            maxlen=metric_window_size
        )
        self._pipeline_latency_ms: deque[float] = deque(
            maxlen=metric_window_size
        )
        self._pose_latency_ms: deque[float] = deque(
            maxlen=metric_window_size
        )
        self._hand_latency_ms: deque[float] = deque(
            maxlen=metric_window_size
        )
        self._pose_detected: deque[float] = deque(
            maxlen=metric_window_size
        )
        self._pose_keypoint_valid: deque[float] = deque(
            maxlen=metric_window_size
        )
        self._pose_critical_valid: deque[float] = deque(
            maxlen=metric_window_size
        )
        self._hand_detected: deque[float] = deque(
            maxlen=metric_window_size
        )
        self._hand_landmarker_times: deque[float] = deque(
            maxlen=metric_window_size
        )

        # Stereo fusion — single-target constraint for binocular cameras
        self._stereo_enabled = bool(config.get("stereo_enabled", True))
        self._stereo_view = str(config.get("stereo_view", "left")).lower()
        self._stereo_min_aspect_ratio = max(
            1.0, float(config.get("stereo_min_aspect_ratio", 2.2))
        )
        if self._stereo_view not in ("left", "right"):
            logger.warning(
                "Invalid stereo_view=%r; falling back to left",
                self._stereo_view,
            )
            self._stereo_view = "left"
        self._single_target = bool(config.get("single_target_mode", True))
        self._last_input_layout: tuple[int, int, bool] | None = None

        # Vision task control — individual tasks can be toggled at runtime
        # via the HTTP task endpoint (useful for enrollment scenarios)
        self.task_face_enabled = True
        self.task_pose_enabled = True
        self.task_hand_enabled = True

        # Detectors
        self._face_detector: Any = None   # OpenCV-compatible face detector
        self._pose_landmarker: Any = None  # MediaPipe PoseLandmarker
        self._pose_backend: Any = None     # RKNN YOLOv8 Pose backend
        self.pose_model_status: dict[str, Any] = {}
        self._hand_landmarker: Any = None  # mediapipe HandLandmarker
        self._hand_backend: Any = None
        self.hand_model_status: dict[str, Any] = {}

        # Face tracking + throttled recognition
        self._face_tracker: Any = None     # FaceByteTracker
        self._face_rec_throttle: Any = None  # FaceRecognitionThrottle
        self._face_rec_model: Any = None   # alignCrop + feature + close
        self.face_model_status: dict[str, dict[str, Any]] = {}
        self._use_byte_track: bool = bool(config.get("face_tracking", {}).get("use_bytetrack", True))

        # One deterministic temporal GesturePose engine is retained per stable
        # visual target ID.  Its defaults come from the standalone reference.
        self._action_classifier = PoseActionClassifier(
            window_size=int(config.get("action_window_size", 30)),
            track_timeout_sec=float(config.get("action_track_timeout_sec", 3.0)),
        )

        # Cache
        self._lock = threading.Lock()
        self._frame_condition = threading.Condition(self._lock)
        self._latest_frame: np.ndarray | None = None
        self._pending_frame: np.ndarray | None = None
        self._pending_frame_stamp: float = 0.0
        self._pending_frame_id: str = "camera_link"
        self._pending_source_metadata: dict[str, Any] | None = None
        self._cached_observation: dict[str, Any] = {}
        self._inference_lock = threading.RLock()
        self._worker_stop = False
        self._worker: threading.Thread | None = None

    @staticmethod
    def _infer_pose_model_variant(model_path: str) -> str:
        name = Path(model_path).name.lower()
        for variant in ("heavy", "full", "lite"):
            if variant in name:
                return variant
        return "custom"

    def _reset_landmarker_metrics(self) -> None:
        self._landmarker_timestamp_ms = 0
        for values in (
            self._landmarker_times,
            self._pipeline_latency_ms,
            self._pose_latency_ms,
            self._hand_latency_ms,
            self._pose_detected,
            self._pose_keypoint_valid,
            self._pose_critical_valid,
            self._hand_detected,
            self._hand_landmarker_times,
        ):
            values.clear()
        self._hand_schedule_counter = 0
        self._hand_active_remaining = 0
        self._hand_inference_count = 0

    def _next_landmarker_timestamp(self) -> int:
        timestamp_ms = time.monotonic_ns() // 1_000_000
        if timestamp_ms <= self._landmarker_timestamp_ms:
            timestamp_ms = self._landmarker_timestamp_ms + 1
        self._landmarker_timestamp_ms = timestamp_ms
        return timestamp_ms

    def _run_landmarker(
        self,
        landmarker: Any,
        image: Any,
        timestamp_ms: int,
    ) -> Any:
        if self._landmarker_running_mode == "video":
            return landmarker.detect_for_video(image, timestamp_ms)
        return landmarker.detect(image)

    @staticmethod
    def _average(values: deque[float]) -> float | None:
        return sum(values) / len(values) if values else None

    @staticmethod
    def _percentile(values: deque[float], percentile: float) -> float | None:
        if not values:
            return None
        return float(np.percentile(np.asarray(values), percentile))

    def _landmarker_diagnostics(self) -> dict[str, Any]:
        effective_fps = 0.0
        if (
            len(self._landmarker_times) >= 2
            and self._landmarker_times[-1] > self._landmarker_times[0]
        ):
            effective_fps = (
                (len(self._landmarker_times) - 1)
                / (self._landmarker_times[-1] - self._landmarker_times[0])
            )
        hand_effective_fps = 0.0
        if (
            len(self._hand_landmarker_times) >= 2
            and self._hand_landmarker_times[-1]
            > self._hand_landmarker_times[0]
        ):
            hand_effective_fps = (
                (len(self._hand_landmarker_times) - 1)
                / (
                    self._hand_landmarker_times[-1]
                    - self._hand_landmarker_times[0]
                )
            )

        def rounded(value: float | None) -> float | None:
            return round(value, 3) if value is not None else None

        return {
            "pose_backend": self._pose_backend_kind,
            "pose_model_variant": self._pose_model_variant,
            "pose_model_file": Path(self._pose_model_path).name,
            "pose_model_status": dict(self.pose_model_status),
            "keypoint_format": (
                "coco_17" if self._pose_backend_kind == "rknn" else "mediapipe_33"
            ),
            "keypoint_count": 17 if self._pose_backend_kind == "rknn" else 33,
            "running_mode": (
                self._landmarker_running_mode
                if self._pose_backend_kind == "mediapipe"
                else "image" if self._pose_backend_kind == "rknn" else "n/a"
            ),
            "inference_frame_stride": self._inference_frame_stride,
            "received_frames": self._received_frame_count,
            "inference_candidates": self._inference_candidate_count,
            "inferred_frames": self._inferred_frame_count,
            "replaced_pending_frames": self._replaced_pending_frame_count,
            "window_frames": len(self._landmarker_times),
            "effective_inference_fps": round(effective_fps, 3),
            "pipeline_avg_ms": rounded(
                self._average(self._pipeline_latency_ms)
            ),
            "pipeline_p95_ms": rounded(
                self._percentile(self._pipeline_latency_ms, 95.0)
            ),
            "pose": {
                "avg_ms": rounded(self._average(self._pose_latency_ms)),
                "p95_ms": rounded(
                    self._percentile(self._pose_latency_ms, 95.0)
                ),
                "detection_rate": rounded(
                    self._average(self._pose_detected)
                ),
                "keypoint_valid_ratio": rounded(
                    self._average(self._pose_keypoint_valid)
                ),
                "critical_keypoint_valid_ratio": rounded(
                    self._average(self._pose_critical_valid)
                ),
            },
            "hand": {
                "backend": (
                    getattr(self._hand_backend, "backend_name", "mediapipe")
                    if self._hand_backend is not None
                    else ("unavailable" if self.hand_model_status else "disabled")
                ),
                "preprocessing": (
                    getattr(self._hand_backend, "preprocessing_mode", "cpu")
                    if self._hand_backend is not None
                    else None
                ),
                "status": dict(self.hand_model_status),
                "idle_inference_stride": self._hand_idle_inference_stride,
                "inference_runs": self._hand_inference_count,
                "effective_inference_fps": round(hand_effective_fps, 3),
                "avg_ms": rounded(self._average(self._hand_latency_ms)),
                "p95_ms": rounded(
                    self._percentile(self._hand_latency_ms, 95.0)
                ),
                "detection_rate": rounded(
                    self._average(self._hand_detected)
                ),
            },
        }

    def _record_pose_quality(self, humans: list[dict[str, Any]]) -> None:
        if not humans:
            self._pose_detected.append(0.0)
            self._pose_keypoint_valid.append(0.0)
            self._pose_critical_valid.append(0.0)
            return
        self._pose_detected.append(1.0)
        best = max(
            humans,
            key=lambda human: float(human.get("confidence", 0.0)),
        )
        keypoints = {
            int(point.get("id", -1)): point
            for point in best.get("keypoints", [])
            if isinstance(point, dict)
        }

        def valid(point: dict[str, Any] | None) -> bool:
            if not point:
                return False
            return min(
                float(point.get("confidence", 0.0)),
                float(point.get("presence", 1.0)),
            ) >= self._pose_confidence_threshold

        keypoint_count = 17 if self._pose_backend_kind == "rknn" else 33
        all_valid = [valid(keypoints.get(index)) for index in range(keypoint_count)]
        critical_indices = (
            (0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)
            if self._pose_backend_kind == "rknn"
            else (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26)
        )
        critical_valid = [valid(keypoints.get(index)) for index in critical_indices]
        self._pose_keypoint_valid.append(sum(all_valid) / len(all_valid))
        self._pose_critical_valid.append(
            sum(critical_valid) / len(critical_valid)
        )

    # ── Lifecycle ──────────────────────────────────────────────

    def start(self) -> None:
        if self.available:
            return
        if self._worker is not None and self._worker.is_alive():
            logger.error("Cannot restart vision while the previous inference worker is stopping")
            return
        if (
            self._face_detector is not None
            or self._face_rec_model is not None
            or self._hand_backend is not None
            or self._pose_backend is not None
        ):
            self.stop()
        self.face_model_status = {}
        self._received_frame_count = 0
        self._inference_candidate_count = 0
        self._inferred_frame_count = 0
        self._replaced_pending_frame_count = 0
        self.pose_model_status = {}
        self._reset_landmarker_metrics()
        try:
            total = 3  # face + pose + hand
            loaded = 0

            # YuNet face detector
            if self._face_detect_model:
                try:
                    self._face_detector = create_face_detector(
                        self._face_detect_model,
                        input_size=_FACE_INPUT_SIZE,
                        score_threshold=self._det_threshold,
                        nms_threshold=self._nms_threshold,
                        top_k=5000,
                        rknn_config=self.config.get("face_detect_rknn"),
                        runtime_library=self.config.get("rknn_runtime_library", ""),
                    )
                    loaded += 1
                    self.face_model_status["yunet"] = {"ready": True}
                    logger.info("YuNet loaded: %s", self._face_detect_model)
                except Exception as exc:
                    self.face_model_status["yunet"] = {"ready": False, "error": str(exc)}
                    logger.error("YuNet failed: %s", exc)
            else:
                total -= 1

            # Suffix-selected human pose backend.  A failed RKNN setup remains
            # unavailable and is never replaced by a CPU model implicitly.
            if self._pose_model_path:
                if self._pose_backend_kind == "rknn":
                    try:
                        self._pose_backend = create_pose_backend(
                            self._pose_model_path,
                            rknn_config=self.config.get("pose_rknn"),
                            runtime_library=self.config.get("rknn_runtime_library", ""),
                            score_threshold=self._det_threshold,
                            nms_threshold=self._nms_threshold,
                            max_num_poses=self._max_num_poses,
                        )
                        self.pose_model_status = {
                            "ready": True,
                            "backend": "rknn",
                            "keypoint_format": "coco_17",
                        }
                        loaded += 1
                        logger.info(
                            "RKNN YOLOv8 Pose loaded: model=%s profile=%s",
                            self._pose_model_path,
                            getattr(self._pose_backend, "profile_name", ""),
                        )
                    except Exception as exc:
                        self.pose_model_status = {
                            "ready": False,
                            "backend": "rknn",
                            "keypoint_format": "coco_17",
                            "error": str(exc),
                        }
                        logger.error("RKNN pose backend failed: %s", exc)
                elif self._pose_backend_kind == "mediapipe":
                    try:
                        import mediapipe as mp
                        from mediapipe.tasks.python import vision
                        from mediapipe.tasks.python.vision import RunningMode

                        running_mode = (
                            RunningMode.VIDEO
                            if self._landmarker_running_mode == "video"
                            else RunningMode.IMAGE
                        )
                        options = vision.PoseLandmarkerOptions(
                            base_options=mp.tasks.BaseOptions(
                                model_asset_path=self._pose_model_path,
                            ),
                            running_mode=running_mode,
                            num_poses=self._max_num_poses,
                            min_pose_detection_confidence=self._det_threshold,
                            min_pose_presence_confidence=self._det_threshold,
                            min_tracking_confidence=0.5,
                        )
                        self._pose_landmarker = vision.PoseLandmarker.create_from_options(
                            options,
                        )
                        self.pose_model_status = {
                            "ready": True,
                            "backend": "mediapipe",
                            "keypoint_format": "mediapipe_33",
                        }
                        loaded += 1
                        logger.info(
                            "MediaPipe PoseLandmarker loaded: variant=%s mode=%s model=%s",
                            self._pose_model_variant,
                            self._landmarker_running_mode,
                            self._pose_model_path,
                        )
                    except Exception as exc:
                        self.pose_model_status = {
                            "ready": False,
                            "backend": "mediapipe",
                            "keypoint_format": "mediapipe_33",
                            "error": str(exc),
                        }
                        logger.warning("MediaPipe PoseLandmarker failed: %s", exc)
                else:
                    self.pose_model_status = {
                        "ready": False,
                        "backend": "unsupported",
                        "error": (
                            f"Unsupported pose model suffix "
                            f"{Path(self._pose_model_path).suffix!r}; expected .task or .rknn"
                        ),
                    }
                    logger.error("%s", self.pose_model_status["error"])
            else:
                total -= 1

            # Format-selected hand backend (MediaPipe .task rollback or RKNN
            # palm + landmark .rknn pair).  The suffix is intentionally the
            # only selector; a failed RKNN setup never silently falls back to
            # CPU inference.
            if self._hand_landmark_model:
                try:
                    self._hand_backend = create_hand_backend(
                        self._hand_landmark_model,
                        detector_model=self._hand_detect_model or None,
                        running_mode=self._landmarker_running_mode,
                        rknn_config=self._hand_rknn_config,
                        runtime_library=self.config.get("rknn_runtime_library", ""),
                        score_threshold=(
                            0.5 if str(self._hand_landmark_model).lower().endswith(".task")
                            else self._hand_score_threshold
                        ),
                        nms_threshold=float(self._hand_rknn_config.get("nms_threshold", 0.30)),
                        presence_threshold=self._hand_presence_threshold,
                        detection_interval=self._hand_detection_interval,
                        preprocessing=self._hand_preprocessing,
                        max_hands=2,
                    )
                    loaded += 1
                    self.hand_model_status = {
                        "ready": True,
                        "backend": self._hand_backend.backend_name,
                        "preprocessing": self._hand_backend.preprocessing_mode,
                    }
                    logger.info(
                        "Hand backend loaded: backend=%s mode=%s model=%s preprocessing=%s",
                        self._hand_backend.backend_name,
                        self._landmarker_running_mode,
                        self._hand_landmark_model,
                        self._hand_backend.preprocessing_mode,
                    )
                except Exception as exc:
                    self.hand_model_status = {"ready": False, "error": str(exc)}
                    logger.error("Hand backend failed: %s", exc)
            else:
                total -= 1

            # ── ByteTrack face tracker ──
            if self._use_byte_track:
                try:
                    from marsdog_vision_interaction.providers.face_tracker import FaceByteTracker
                    ft_cfg = self.config.get("face_tracking", {})
                    self._face_tracker = FaceByteTracker(
                        track_activation_threshold=float(ft_cfg.get("track_activation_threshold", 0.25)),
                        lost_track_buffer=int(ft_cfg.get("lost_track_buffer", 30)),
                        minimum_matching_threshold=float(ft_cfg.get("minimum_matching_threshold", 0.8)),
                        minimum_consecutive_frames=int(ft_cfg.get("minimum_consecutive_frames", 2)),
                    )
                    loaded += 1; total += 1
                    logger.info("ByteTrack face tracker initialized")
                except Exception as exc:
                    logger.warning("ByteTrack init failed: %s — tracking disabled", exc)
                    self._use_byte_track = False

            # ── SFace recognizer for throttled recognition ──
            face_rec_model_path = self.config.get("face_recogn_model", "")
            face_rec_cfg = self.config.get("face_recognition_throttle", {})
            if face_rec_model_path:
                try:
                    self._face_rec_model = create_face_recognizer(
                        face_rec_model_path,
                        rknn_config=self.config.get("face_recogn_rknn"),
                        runtime_library=self.config.get("rknn_runtime_library", ""),
                    )
                    from marsdog_vision_interaction.providers.face_tracker import FaceRecognitionThrottle
                    self._face_rec_throttle = FaceRecognitionThrottle(
                        face_recognizer=self._face_rec_model,
                        min_face_score=float(face_rec_cfg.get("min_face_score", 0.85)),
                        min_face_size_px=int(face_rec_cfg.get("min_face_size_px", 40)),
                        unknown_active_retry_sec=float(face_rec_cfg.get("unknown_active_retry_sec", 0.5)),
                        unknown_inactive_retry_sec=float(face_rec_cfg.get("unknown_inactive_retry_sec", 1.5)),
                        known_active_reverify_sec=float(face_rec_cfg.get("known_active_reverify_sec", 3.0)),
                        known_inactive_reverify_sec=float(face_rec_cfg.get("known_inactive_reverify_sec", 8.0)),
                        confirm_known_count=int(face_rec_cfg.get("confirm_known_count", 2)),
                        confirm_unknown_count=int(face_rec_cfg.get("confirm_unknown_count", 4)),
                        sface_cosine_threshold=float(face_rec_cfg.get("sface_cosine_threshold", 0.36)),
                    )
                    loaded += 1
                    self.face_model_status["sface"] = {"ready": True}
                    logger.info("SFace recognition throttle initialized")
                except Exception as exc:
                    self._close_face_model(self._face_rec_model)
                    self._face_rec_model = None
                    self._face_rec_throttle = None
                    self.face_model_status["sface"] = {"ready": False, "error": str(exc)}
                    logger.error("SFace recognizer init failed: %s", exc)
                total += 1

            if loaded > 0:
                self.available = True
                self._start_inference_worker()
                logger.info(
                    "VisionObservationProvider started — %d/%d models loaded; "
                    "inference_frame_stride=%d; max_num_poses=%d; "
                    "hand_idle_stride=%d; latest-frame worker=enabled",
                    loaded,
                    total,
                    self._inference_frame_stride,
                    self._max_num_poses,
                    self._hand_idle_inference_stride,
                )
                if any(not state["ready"] for state in self.face_model_status.values()):
                    logger.error("Face models partially unavailable: %s", self.face_model_status)
            else:
                self.available = False
                logger.warning("VisionObservationProvider — no models, unavailable")

        except Exception as exc:
            self.available = False
            logger.warning("VisionObservationProvider start failed: %s", exc, exc_info=True)
            self.stop()

    @staticmethod
    def _close_face_model(model: Any) -> None:
        close = getattr(model, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.exception("Face model release failed")

    def _disable_fatal_face_model(self, role: str, model: Any) -> bool:
        """Remove an adapter that released its runtime after a fatal error.

        Ordinary bad frames and alignment failures keep their existing fallback
        behavior. RKNN adapters expose ``fatal_error`` only after their runtime
        has been released, so this transition is performed once and subsequent
        frames skip the dead model without repeating error logs.
        """

        error = getattr(model, "fatal_error", None)
        if not error:
            return False
        status = self.face_model_status.setdefault(role, {})
        already_reported = (
            status.get("ready") is False
            and status.get("fatal") is True
            and status.get("error") == str(error)
        )
        status.update({"ready": False, "fatal": True, "error": str(error)})
        if role == "yunet" and self._face_detector is model:
            self._face_detector = None
        elif role == "sface" and self._face_rec_model is model:
            self._face_rec_model = None
            clear_states = getattr(
                self._face_rec_throttle, "clear_identity_states", None
            )
            if callable(clear_states):
                clear_states()
        self._close_face_model(model)
        if not already_reported:
            logger.error("Face model became unavailable: role=%s error=%s", role, error)
        return True

    def _disable_fatal_hand_model(self, model: Any) -> bool:
        """Mark a released RKNN hand backend unavailable exactly once."""

        error = getattr(model, "fatal_error", None)
        if not error:
            return False
        already_reported = (
            self.hand_model_status.get("ready") is False
            and self.hand_model_status.get("fatal") is True
            and self.hand_model_status.get("error") == str(error)
        )
        self.hand_model_status.update({"ready": False, "fatal": True, "error": str(error)})
        if self._hand_backend is model:
            self._hand_backend = None
        try:
            model.close()
        except Exception:
            logger.exception("Hand backend release failed")
        if not already_reported:
            logger.error("Hand model became unavailable: %s", error)
        return True

    def _disable_fatal_pose_model(self, model: Any) -> bool:
        """Mark a released RKNN pose runtime unavailable exactly once."""

        error = getattr(model, "fatal_error", None)
        if not error:
            return False
        already_reported = (
            self.pose_model_status.get("ready") is False
            and self.pose_model_status.get("fatal") is True
            and self.pose_model_status.get("error") == str(error)
        )
        self.pose_model_status.update({
            "ready": False,
            "fatal": True,
            "backend": self._pose_backend_kind,
            "keypoint_format": "coco_17",
            "error": str(error),
        })
        if self._pose_backend is model:
            self._pose_backend = None
        try:
            model.close()
        except Exception:
            logger.exception("Pose backend release failed")
        if not already_reported:
            logger.error("Pose model became unavailable: %s", error)
        return True

    def stop(self) -> None:
        self.available = False
        if not self._stop_inference_worker():
            logger.error(
                "Inference worker did not stop; leaving model handles intact "
                "to avoid closing them during an active inference"
            )
            return
        self._action_classifier.reset()
        with self._inference_lock:
            self._close_face_model(self._face_detector)
            self._close_face_model(self._face_rec_model)
            self._face_detector = None
            self._face_tracker = None
            self._face_rec_throttle = None
            self._face_rec_model = None
            self.face_model_status = {}
            if self._hand_backend is not None:
                try:
                    self._hand_backend.close()
                except Exception:
                    logger.exception("Hand backend release failed")
                self._hand_backend = None
            self.hand_model_status = {}
            if self._pose_backend is not None:
                try:
                    self._pose_backend.close()
                except Exception:
                    logger.exception("Pose backend release failed")
                self._pose_backend = None
            self.pose_model_status = {}
        if self._pose_landmarker is not None:
            try:
                self._pose_landmarker.close()
            except Exception:
                pass
            self._pose_landmarker = None
        if self._hand_landmarker is not None:
            try:
                self._hand_landmarker.close()
            except Exception:
                pass
            self._hand_landmarker = None
        with self._lock:
            self._latest_frame = None
            self._pending_frame = None
            self._pending_source_metadata = None
            self._cached_observation = {}
        self._received_frame_count = 0
        self._inference_candidate_count = 0
        self._inferred_frame_count = 0
        self._replaced_pending_frame_count = 0
        self._reset_landmarker_metrics()
        logger.info("VisionObservationProvider stopped")

    # ── Frame injection ────────────────────────────────────────

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        stamp: float = 0.0,
        frame_id: str = "camera_link",
        source_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Queue only the newest eligible frame for the inference worker.

        The ROS camera callback must stay short: while inference is busy, a
        newer eligible frame replaces the single pending frame instead of
        building latency in a FIFO queue.
        """
        if not self.available:
            return
        with self._frame_condition:
            self._received_frame_count += 1
            if (self._received_frame_count - 1) % self._inference_frame_stride:
                return
            self._inference_candidate_count += 1
            if self._pending_frame is not None:
                self._replaced_pending_frame_count += 1
            self._pending_frame = frame
            self._pending_frame_stamp = float(stamp or time.time())
            self._pending_frame_id = str(frame_id or "camera_link")
            self._pending_source_metadata = copy.deepcopy(source_metadata)
            self._frame_condition.notify()

    def _start_inference_worker(self) -> None:
        with self._frame_condition:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker_stop = False
            self._pending_frame = None
            self._pending_frame_stamp = 0.0
            self._pending_frame_id = "camera_link"
            self._pending_source_metadata = None
            self._worker = threading.Thread(
                target=self._inference_worker_loop,
                name="vision-latest-frame-inference",
                daemon=True,
            )
            self._worker.start()

    def _stop_inference_worker(self) -> bool:
        with self._frame_condition:
            self._worker_stop = True
            self._pending_frame = None
            self._pending_frame_stamp = 0.0
            self._pending_source_metadata = None
            self._frame_condition.notify_all()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=5.0)
        stopped = worker is None or not worker.is_alive()
        if stopped:
            with self._frame_condition:
                self._worker = None
        return stopped

    def _inference_worker_loop(self) -> None:
        while True:
            with self._frame_condition:
                self._frame_condition.wait_for(
                    lambda: self._worker_stop or self._pending_frame is not None
                )
                if self._worker_stop:
                    return
                frame = self._pending_frame
                frame_stamp = self._pending_frame_stamp
                frame_id = self._pending_frame_id
                source_metadata = copy.deepcopy(self._pending_source_metadata)
                self._pending_frame = None
                self._pending_frame_stamp = 0.0
                self._pending_source_metadata = None
            if frame is None:
                continue
            try:
                with self._inference_lock:
                    if source_metadata is None:
                        # Preserve the lightweight test/provider override
                        # contract used by legacy callers.
                        obs = self._process_frame_impl(frame)
                    else:
                        obs = self._process_frame_impl(
                            frame,
                            source_metadata=source_metadata,
                        )
                obs["header"] = {
                    "stamp": float(frame_stamp or time.time()),
                    "frame_id": str(frame_id or "camera_link"),
                }
                with self._lock:
                    self._latest_frame = frame
                    self._cached_observation = obs
                    self._inferred_frame_count += 1
            except Exception as exc:
                logger.error("Frame processing error: %s", exc, exc_info=True)

    def run_inference_exclusive(self, operation: Any) -> Any:
        """Run an operation while the shared YuNet/SFace models are idle."""
        with self._inference_lock:
            return operation()

    @staticmethod
    def _human_candidate_matches(
        humans: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
    ) -> dict[int, dict[str, Any]]:
        """Associate current raw pose boxes with distinct manager tracks."""
        pairs: list[tuple[float, int, int]] = []
        for human_index, human in enumerate(humans):
            if not isinstance(human, dict):
                continue
            try:
                source_bbox = tuple(
                    float(human.get(key, 0.0))
                    for key in ("x", "y", "w", "h")
                )
            except (TypeError, ValueError):
                continue
            for candidate_index, candidate in enumerate(candidates):
                values = candidate.get("bbox", ())
                if not isinstance(values, (list, tuple)) or len(values) < 4:
                    continue
                try:
                    distance = sum(
                        (first - float(second)) ** 2
                        for first, second in zip(source_bbox, values[:4])
                    )
                except (TypeError, ValueError):
                    continue
                pairs.append((distance, human_index, candidate_index))

        matches: dict[int, dict[str, Any]] = {}
        used_candidates: set[int] = set()
        for _distance, human_index, candidate_index in sorted(pairs):
            if human_index in matches or candidate_index in used_candidates:
                continue
            matches[human_index] = candidates[candidate_index]
            used_candidates.add(candidate_index)
        return matches

    @staticmethod
    def _debug_human_overlays(
        humans: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        active: Any,
        pose_key: str,
        pose_label: str,
    ) -> list[dict[str, Any]]:
        """Sanitize current pose detections for the optional debug contract."""
        overlays: list[dict[str, Any]] = []
        active_track_id = int(getattr(active, "track_id", 0) or 0)
        matches = VisionObservationProvider._human_candidate_matches(
            humans, candidates
        )
        for human_index, human in enumerate(humans):
            if not isinstance(human, dict):
                continue
            candidate = matches.get(human_index)
            try:
                track_id = int(human.get("track_id", -1))
            except (TypeError, ValueError):
                track_id = -1
            if candidate is not None:
                try:
                    candidate_track_id = int(candidate.get("track_id", -1))
                except (TypeError, ValueError):
                    candidate_track_id = -1
                if candidate_track_id >= 0:
                    track_id = candidate_track_id
            is_active = track_id > 0 and track_id == active_track_id
            overlay = {
                "track_id": track_id,
                "x": round(float(human.get("x", 0.0)), 4),
                "y": round(float(human.get("y", 0.0)), 4),
                "w": round(float(human.get("w", 0.0)), 4),
                "h": round(float(human.get("h", 0.0)), 4),
                "confidence": round(float(human.get("confidence", 0.0)), 4),
                "pose_state": str(human.get("pose_state", "")),
                "pose_action": pose_key if is_active else "",
                "pose_action_label": pose_label if is_active else "",
                "keypoint_format": str(
                    human.get("keypoint_format", "mediapipe_33")
                ),
                "keypoints": copy.deepcopy(human.get("keypoints", [])),
            }
            overlays.append(overlay)
        return overlays

    @staticmethod
    def _debug_face_overlays(
        faces: list[dict[str, Any]],
        active: Any,
        target_is_current: bool,
    ) -> list[dict[str, Any]]:
        """Sanitize current face detections for the optional debug contract."""
        try:
            active_face_track_id = int(getattr(active, "face_track_id", -1))
        except (TypeError, ValueError):
            active_face_track_id = -1
        overlays: list[dict[str, Any]] = []
        for face in faces:
            if not isinstance(face, dict):
                continue
            try:
                track_id = int(face.get("track_id", -1))
            except (TypeError, ValueError):
                track_id = -1
            is_active = (
                target_is_current
                and track_id > 0
                and track_id == active_face_track_id
            )
            overlays.append({
                "track_id": track_id,
                "x": round(float(face.get("x", 0.0)), 4),
                "y": round(float(face.get("y", 0.0)), 4),
                "w": round(float(face.get("w", 0.0)), 4),
                "h": round(float(face.get("h", 0.0)), 4),
                "confidence": round(float(face.get("confidence", 0.0)), 4),
                "recognized_user": str(face.get("recognized_user", "")),
                "identity_confidence": round(
                    float(face.get("identity_confidence", 0.0)), 4
                ),
                "identity_state": str(
                    face.get("identity_state", "unverified")
                ),
                "quality": round(float(face.get("quality", 0.0)), 4),
                "active": is_active,
            })
        return overlays

    def _process_frame_impl(
        self,
        frame: np.ndarray,
        *,
        source_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Select one stereo eye and run all 2D models on that view.

        All 2D vision models (YuNet face, MediaPipe pose) operate on the
        configured eye only. Coordinates remain normalized to that single
        view, so x=0.5 always means straight ahead for the selected camera.
        """
        if not self._stereo_enabled:
            obs = self._run_inference(frame, detect_faces=True)
            selected_frame = frame
            stereo_split = False
        else:
            selected_frame, stereo_split = select_camera_view(
                frame,
                stereo_enabled=True,
                view=self._stereo_view,
                min_aspect_ratio=self._stereo_min_aspect_ratio,
            )
            input_height, input_width = frame.shape[:2]
            layout = (input_width, input_height, stereo_split)
            if layout != self._last_input_layout:
                if stereo_split:
                    logger.info(
                        "Stereo input %dx%d detected; using %s eye %dx%d",
                        input_width, input_height, self._stereo_view,
                        selected_frame.shape[1], selected_frame.shape[0],
                    )
                else:
                    logger.warning(
                        "Input %dx%d is not side-by-side stereo (ratio %.2f < %.2f); "
                        "using the complete frame",
                        input_width, input_height, input_width / input_height,
                        self._stereo_min_aspect_ratio,
                    )
                self._last_input_layout = layout
            obs = self._run_inference(selected_frame, detect_faces=True)

        # Feed every body into the process-wide tracker.  The manager retains a
        # legacy active target but exposes all tracks for downstream policy.
        from marsdog_vision_interaction.fusion.stereo_fusion import get_target_manager

        mgr = get_target_manager()
        localization_source = copy.deepcopy(source_metadata)
        if localization_source is not None:
            localization_source.update({
                "source_width": int(frame.shape[1]),
                "source_height": int(frame.shape[0]),
                "view_width": int(selected_frame.shape[1]),
                "view_height": int(selected_frame.shape[0]),
                "view_split": bool(stereo_split),
            })
        mgr.update_vision(
            humans=obs.get("humans", []),
            faces=obs.get("faces", []),
            source_metadata=localization_source,
        )
        target_snapshot = mgr.get_snapshot()
        active = target_snapshot["active_target"]
        active_dict = active.to_dict()
        human_candidates = target_snapshot["human_candidates"]
        target_is_current = active_dict["tracking_state"] == "tracking"

        # Run the temporal action engine only for the human selected by the
        # stable target manager.  Hand-to-person association is not available
        # from MediaPipe Tasks, so hands are used only in single-target mode.
        target_human = self._match_active_human(active.bbox, obs.get("humans", []))
        pose_landmarks = (
            target_human.get("_behavior_landmarks")
            if target_human is not None and target_is_current
            else None
        )
        left_hand, right_hand = self._behavior_hands(obs.get("hands", []))
        action_result = self._action_classifier.update(
            track_id=active.track_id if active.track_id > 0 else 0,
            pose_landmarks=pose_landmarks,
            left_hand=left_hand if pose_landmarks is not None else None,
            right_hand=right_hand if pose_landmarks is not None else None,
            face_observed=(
                bool(active.face_confidence > 0.0 and target_is_current)
                if self.task_face_enabled
                else None
            ),
            now=time.monotonic(),
        )
        action_result["landmarker"] = obs.get(
            "_landmarker_diagnostics", {}
        )
        inference_sequence = self._inferred_frame_count + 1
        gesture_track_id = active.track_id if active.track_id > 0 else 0
        vision_timing_trace(
            node="vision_observation",
            module="gesture_pose",
            stage="feature_extraction",
            latency_ms=float(action_result.get("feature_ms", 0.0) or 0.0),
            inference_sequence=inference_sequence,
            track_id=gesture_track_id,
        )
        vision_timing_trace(
            node="vision_observation",
            module="gesture_pose",
            stage="action_recognition",
            latency_ms=float(
                action_result.get("recognition_ms", 0.0) or 0.0
            ),
            inference_sequence=inference_sequence,
            track_id=gesture_track_id,
            primary_action=str(action_result.get("primary_action", "")),
        )
        pose_key = str(action_result.get("pose_action", ""))
        pose_label = str(action_result.get("pose_action_label", ""))
        hand_key = str(action_result.get("hand_action", ""))
        hand_label = str(action_result.get("hand_action_label", ""))
        active_dict["pose_action"] = pose_key
        active_dict["pose_action_label"] = pose_label
        for candidate in human_candidates:
            if candidate.get("target_id") == active.target_id:
                candidate["pose_action"] = pose_key
                candidate["pose_action_label"] = pose_label

        # Build unified output (matches the bridge's expected format)
        humans_out = []
        if active.confidence > 0 and target_is_current:
            humans_out = [{
                "x": round(active.bbox[0], 4),
                "y": round(active.bbox[1], 4),
                "w": round(active.bbox[2], 4),
                "h": round(active.bbox[3], 4),
                "confidence": round(active.confidence, 4),
                "pose_state": active.pose_state,
                "pose_action": pose_key,
                "pose_action_label": pose_label,
                "keypoint_format": active.keypoint_format,
                "keypoints": active.keypoints,
                "track_id": active.track_id,
            }]

        faces_out = []
        if active.face_confidence > 0 and target_is_current:
            faces_out = [{
                "track_id": active.face_track_id,
                "x": round(active.face_bbox[0], 4),
                "y": round(active.face_bbox[1], 4),
                "w": round(active.face_bbox[2], 4),
                "h": round(active.face_bbox[3], 4),
                "confidence": round(active.face_confidence, 4),
                "recognized_user": active.identity,
                "identity_confidence": round(active.identity_confidence, 4),
                "identity_state": active.identity_state,
                "quality": round(active.face_confidence, 4),
            }]
        else:
            # Keep any detected faces even if not yet bound to a human
            for f in obs.get("faces", []):
                faces_out.append({
                    "track_id": int(f.get("track_id", -1)),
                    "x": round(f.get("x", 0), 4),
                    "y": round(f.get("y", 0), 4),
                    "w": round(f.get("w", 0), 4),
                    "h": round(f.get("h", 0), 4),
                    "confidence": round(f.get("confidence", 0), 4),
                    "recognized_user": f.get("recognized_user", ""),
                    "identity_confidence": round(
                        f.get("identity_confidence", 0), 4,
                    ),
                    "identity_state": f.get(
                        "identity_state", "unverified",
                    ),
                    "quality": round(f.get("quality", 0), 4),
                })

        # Attach hand action labels to each hand
        hands_out = []
        for h in obs.get("hands", []):
            hands_out.append({
                "handedness": h.get("handedness", ""),
                "hand_action": hand_key,
                "hand_action_label": hand_label,
                "landmarks": h.get("landmarks", []),
            })

        result = {
            "vision_epoch": target_snapshot["vision_epoch"],
            "active_target": active_dict,
            "human_candidates": human_candidates,
            "faces": faces_out,
            "humans": humans_out,
            "hands": hands_out,
            "tracked_objects": obs.get("tracked_objects", []),
            "_gesture_diagnostics": action_result,
        }
        if self._show_all_detections:
            result["debug_humans"] = self._debug_human_overlays(
                obs.get("humans", []),
                human_candidates,
                active,
                pose_key,
                pose_label,
            )
            result["debug_faces"] = self._debug_face_overlays(
                obs.get("faces", []),
                active,
                target_is_current,
            )
        return result

    @staticmethod
    def _match_active_human(
        active_bbox: tuple[float, float, float, float],
        humans: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not humans or active_bbox[2] <= 0.0 or active_bbox[3] <= 0.0:
            return None

        def distance(human: dict[str, Any]) -> float:
            bbox = (
                float(human.get("x", 0.0)),
                float(human.get("y", 0.0)),
                float(human.get("w", 0.0)),
                float(human.get("h", 0.0)),
            )
            return sum((first - second) ** 2 for first, second in zip(active_bbox, bbox))

        return min(humans, key=distance)

    @staticmethod
    def _behavior_hands(
        hands: list[dict[str, Any]],
    ) -> tuple[HandLandmarkSet | None, HandLandmarkSet | None]:
        left: HandLandmarkSet | None = None
        right: HandLandmarkSet | None = None
        for hand in hands:
            landmarks = hand.get("_behavior_landmarks")
            if not isinstance(landmarks, tuple):
                continue
            side = str(hand.get("handedness", "")).strip().lower()
            if side == "left" and left is None:
                left = landmarks
            elif side == "right" and right is None:
                right = landmarks
        return left, right

    @staticmethod
    def _select_stereo_view(
        frame: np.ndarray,
        view: str = "left",
        min_aspect_ratio: float = 2.2,
    ) -> np.ndarray:
        """Select one eye for stereo input, preserving normal mono frames."""
        selected, _ = select_camera_view(
            frame,
            stereo_enabled=True,
            view=view,
            min_aspect_ratio=min_aspect_ratio,
        )
        return selected

    @staticmethod
    def _scale_obs_to_region(
        obs: dict[str, Any],
        ox: float, oy: float, ow: float, oh: float,
    ) -> None:
        """Scale normalized coordinates from a sub-region to full-frame space.

        Args:
            obs: Observation dict with faces/humans in sub-region coords.
            ox, oy: Offset of sub-region in full frame (normalized 0-1).
            ow, oh: Size of sub-region relative to full frame.
        """
        for det_list in (obs.get("faces", []), obs.get("humans", [])):
            for det in det_list:
                det["x"] = round(ox + float(det.get("x", 0)) * ow, 4)
                det["y"] = round(oy + float(det.get("y", 0)) * oh, 4)
                det["w"] = round(float(det.get("w", 0)) * ow, 4)
                det["h"] = round(float(det.get("h", 0)) * oh, 4)
                for kp in det.get("keypoints", []):
                    kp["x"] = round(ox + float(kp.get("x", 0)) * ow, 4)
                    kp["y"] = round(oy + float(kp.get("y", 0)) * oh, 4)

        # Scale hand landmarks (left half → full frame)
        for hand in obs.get("hands", []):
            for lm in hand.get("landmarks", []):
                lm["x"] = round(ox + float(lm.get("x", 0)) * ow, 4)
                lm["y"] = round(oy + float(lm.get("y", 0)) * oh, 4)

    # ── Public API ─────────────────────────────────────────────

    def get_observation(self) -> dict[str, Any]:
        with self._lock:
            if self._cached_observation:
                return copy.deepcopy(self._cached_observation)
        return {}

    def check_person(self) -> dict[str, Any]:
        obs = self.get_observation()
        candidates = [
            item
            for item in obs.get("human_candidates", [])
            if isinstance(item, dict)
            and item.get("tracking_state") == "tracking"
        ]
        if candidates:
            active = obs.get("active_target", {})
            return {
                "present": True,
                "count": len(candidates),
                "identity": str(active.get("identity", "unknown")),
                "target": dict(active) if isinstance(active, dict) else {},
            }
        humans = obs.get("humans", [])
        return {"present": len(humans) > 0, "count": len(humans)}

    def enroll_face(self, face_image: Any = None) -> dict[str, Any]:
        _ = face_image
        return {"success": True, "user_id": "mock_user_001"}

    def recognize_face(self, face_image: Any = None) -> dict[str, Any]:
        _ = face_image
        return {"user_id": "unknown", "confidence": 0.0}

    # ── Inference ──────────────────────────────────────────────

    def _run_inference(
        self, frame: np.ndarray, detect_faces: bool = True,
    ) -> dict[str, Any]:
        """Run YuNet + MediaPipe on a single frame.

        Args:
            frame: BGR numpy array.
            detect_faces: If False, skip YuNet (e.g. right stereo half).

        Returns normalized coordinates [0-1] relative to the input frame.
        Caller is responsible for mapping to full-frame space if needed.
        """
        h, w = frame.shape[:2]
        started_at = time.perf_counter()
        inference_sequence = self._inferred_frame_count + 1
        timestamp_ms = self._next_landmarker_timestamp()
        faces = (
            self._detect_faces(
                frame,
                w,
                h,
                inference_sequence=inference_sequence,
            )
            if (detect_faces and self.task_face_enabled)
            else []
        )
        pose_started_at = time.perf_counter()
        humans = []
        if self.task_pose_enabled:
            if self._pose_backend_kind == "rknn":
                humans = self._detect_pose_rknn(frame, w, h)
            elif self._pose_backend_kind == "mediapipe":
                humans = self._detect_pose_mediapipe(frame, w, h, timestamp_ms)
        pose_ms = (time.perf_counter() - pose_started_at) * 1000.0
        if self.task_pose_enabled and (
            self._pose_landmarker is not None or self._pose_backend is not None
        ):
            vision_timing_trace(
                node="vision_observation",
                module=("pose_rknn" if self._pose_backend_kind == "rknn" else "pose_landmarker"),
                stage="inference",
                latency_ms=pose_ms,
                inference_sequence=inference_sequence,
                detection_count=len(humans),
                model_variant=self._pose_model_variant,
                backend=self._pose_backend_kind,
            )
        run_hands = (
            self.task_hand_enabled
            and (self._hand_backend is not None or self._hand_landmarker is not None)
            and self._hand_inference_is_due()
        )
        hands: list[dict[str, Any]] = []
        hand_ms: float | None = None
        if run_hands:
            hand_started_at = time.perf_counter()
            hands = self._detect_hands(frame, w, h, timestamp_ms)
            hand_ms = (time.perf_counter() - hand_started_at) * 1000.0
            vision_timing_trace(
                node="vision_observation",
                module="hand_landmarker",
                stage="inference",
                latency_ms=hand_ms,
                inference_sequence=inference_sequence,
                detection_count=len(hands),
            )
            self._hand_inference_count += 1
            self._hand_landmarker_times.append(time.monotonic())
            if hands:
                self._hand_active_remaining = self._hand_active_hold_inferences
            elif self._hand_active_remaining > 0:
                self._hand_active_remaining -= 1
        pipeline_ms = (time.perf_counter() - started_at) * 1000.0
        self._landmarker_times.append(time.monotonic())
        if self.task_pose_enabled and (
            self._pose_landmarker is not None or self._pose_backend is not None
        ):
            self._pose_latency_ms.append(pose_ms)
            self._record_pose_quality(humans)
        if hand_ms is not None:
            self._hand_latency_ms.append(hand_ms)
            self._hand_detected.append(1.0 if hands else 0.0)
        self._pipeline_latency_ms.append(pipeline_ms)
        vision_timing_trace(
            node="vision_observation",
            module="continuous_vision",
            stage="pipeline",
            latency_ms=pipeline_ms,
            inference_sequence=inference_sequence,
            face_count=len(faces),
            human_count=len(humans),
            hand_count=len(hands),
        )

        return {
            "faces": faces,
            "humans": humans,
            "hands": hands,
            "tracked_objects": [],
            "_landmarker_diagnostics": self._landmarker_diagnostics(),
        }

    def _hand_inference_is_due(self) -> bool:
        self._hand_schedule_counter += 1
        if self._hand_active_remaining > 0:
            return True
        return (
            (self._hand_schedule_counter - 1)
            % self._hand_idle_inference_stride
            == 0
        )

    # ── YuNet face detection ───────────────────────────────────

    def _detect_faces(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
        *,
        inference_sequence: int = 0,
    ) -> list[dict[str, Any]]:
        if self._face_detector is None:
            self._mark_face_tracks_missing()
            return []

        try:
            detect_started = time.perf_counter()
            try:
                self._face_detector.setInputSize((w, h))
                _, results = self._face_detector.detect(frame)
            except Exception:
                vision_timing_trace(
                    node="vision_observation",
                    module="face_detection",
                    stage="yunet_inference",
                    latency_ms=(time.perf_counter() - detect_started) * 1000.0,
                    result="failure",
                    inference_sequence=inference_sequence,
                    detection_count=0,
                )
                raise
            vision_timing_trace(
                node="vision_observation",
                module="face_detection",
                stage="yunet_inference",
                latency_ms=(time.perf_counter() - detect_started) * 1000.0,
                inference_sequence=inference_sequence,
                detection_count=0 if results is None else len(results),
            )
            faces = []
            if results is None or len(results) == 0:
                # Feed empty detections to tracker to keep state consistent
                if self._face_tracker is not None:
                    self._update_face_tracker(
                        np.empty((0, 4), dtype=np.float32),
                        np.empty((0,), dtype=np.float32),
                        inference_sequence=inference_sequence,
                    )
                self._mark_face_tracks_missing()
                return []

            # Build face list with xyxy for tracking
            detections_xyxy = []
            detections_scores = []
            face_data = []
            for det in results:
                fx, fy, fw, fh = float(det[0]), float(det[1]), float(det[2]), float(det[3])
                # FaceDetectorYN layout is bbox(4), five landmarks(10),
                # confidence(1). det[4] is a landmark coordinate, not score.
                conf = float(det[-1])
                if conf < self._det_threshold:
                    continue
                x1, y1, x2, y2 = fx, fy, fx + fw, fy + fh
                detections_xyxy.append([x1, y1, x2, y2])
                detections_scores.append(conf)
                face_data.append({
                    "x": round(fx / w, 4), "y": round(fy / h, 4),
                    "w": round(fw / w, 4), "h": round(fh / h, 4),
                    "confidence": round(conf, 4),
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,  # pixel coords for tracking
                    "_yunet_detection": np.asarray(det, dtype=np.float32),
                })

            if not face_data:
                if self._face_tracker is not None:
                    self._update_face_tracker(
                        np.empty((0, 4), dtype=np.float32),
                        np.empty((0,), dtype=np.float32),
                        inference_sequence=inference_sequence,
                    )
                self._mark_face_tracks_missing()
                return []

            # ── ByteTrack ──
            track_ids = None
            if self._face_tracker is not None:
                xyxy_arr = np.array(detections_xyxy, dtype=np.float32)
                scores_arr = np.array(detections_scores, dtype=np.float32)
                track_ids = self._update_face_tracker(
                    xyxy_arr,
                    scores_arr,
                    inference_sequence=inference_sequence,
                )

            if self._face_rec_throttle is not None:
                visible_track_ids = {
                    int(track_id)
                    for track_id in (track_ids if track_ids is not None else [])
                    if int(track_id) >= 0
                }
                self._face_rec_throttle.mark_missing_except(
                    visible_track_ids, time.time()
                )

            # ── Throttled SFace recognition ──
            now = time.time()
            sface_disabled = bool(
                self.face_model_status.get("sface", {}).get("fatal", False)
            )
            for i, fd in enumerate(face_data):
                tid = int(track_ids[i]) if track_ids is not None and i < len(track_ids) else -1
                fd["track_id"] = tid
                fd["identity_state"] = "unverified"
                fd["identity_confidence"] = 0.0
                fd["recognized_user"] = ""

                if tid < 0:
                    continue

                # Update tracker with current bbox
                bw = int(fd["x2"] - fd["x1"])
                bh = int(fd["y2"] - fd["y1"])

                if self._face_rec_throttle is not None and not sface_disabled:
                    reappeared = self._face_rec_throttle.mark_seen(
                        tid, np.array(detections_xyxy[i]), now
                    )

                    # Check if we should recognize this face now
                    # is_active = this is the active target
                    is_active = False  # will be refined later in fusion
                    if self._face_rec_throttle.should_recognize(
                        tid, fd["confidence"], bw, bh, is_active, now,
                        force=reappeared,
                    ):
                        identity, identity_conf = self._run_sface(
                            frame,
                            fd,
                            inference_sequence=inference_sequence,
                        )
                        self._face_rec_throttle.update_identity(tid, identity, identity_conf, now)

                        sface_disabled = bool(
                            self.face_model_status.get("sface", {}).get("fatal", False)
                        )

                # Read current track state
                track_state = self._face_rec_throttle.get_track_state(tid) if self._face_rec_throttle else None
                if track_state is not None:
                    fd["recognized_user"] = track_state.identity if track_state.is_known else ""
                    fd["identity_confidence"] = round(track_state.identity_confidence, 4)
                    fd["identity_state"] = track_state.identity_state

                # Quality score: face_score * size_ratio
                quality = fd["confidence"]
                fd["quality"] = round(quality, 4)

            # Remove internal pixel fields
            if self.face_model_status.get("sface", {}).get("fatal", False):
                clear_states = getattr(
                    self._face_rec_throttle, "clear_identity_states", None
                )
                if callable(clear_states):
                    clear_states()
                for fd in face_data:
                    fd["recognized_user"] = ""
                    fd["identity_confidence"] = 0.0
                    fd["identity_state"] = "unverified"
            for fd in face_data:
                fd.pop("x1", None); fd.pop("y1", None); fd.pop("x2", None); fd.pop("y2", None)
                fd.pop("_yunet_detection", None)

            logger.debug(
                "YuNet: %d raw, %d passed, track_ids=%s",
                len(results), len(face_data),
                [f["track_id"] for f in face_data] if face_data else [],
            )
            faces = face_data
            return faces

        except Exception as exc:
            if self._disable_fatal_face_model("yunet", self._face_detector):
                self._mark_face_tracks_missing()
                return []
            self._mark_face_tracks_missing()
            logger.debug("Face detection error: %s", exc)
            return []

    def _mark_face_tracks_missing(self) -> None:
        """Fail closed when a processed inference has no usable face result."""
        if self._face_rec_throttle is not None:
            self._face_rec_throttle.mark_missing_except(set(), time.time())

    def _update_face_tracker(
        self,
        xyxy: np.ndarray,
        scores: np.ndarray,
        *,
        inference_sequence: int,
    ) -> Any:
        """Run one ByteTrack update and expose only its compute duration."""
        started = time.perf_counter()
        try:
            track_ids = self._face_tracker.update(xyxy, scores)
        except Exception:
            vision_timing_trace(
                node="vision_observation",
                module="face_tracking",
                stage="bytetrack_update",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                result="failure",
                inference_sequence=inference_sequence,
                detection_count=len(xyxy),
                track_count=0,
            )
            raise
        valid_track_count = sum(
            1 for value in track_ids if int(value) >= 0
        )
        vision_timing_trace(
            node="vision_observation",
            module="face_tracking",
            stage="bytetrack_update",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            inference_sequence=inference_sequence,
            detection_count=len(xyxy),
            track_count=valid_track_count,
        )
        return track_ids

    def _run_sface(
        self,
        frame: np.ndarray,
        face: dict[str, Any],
        *,
        inference_sequence: int = 0,
    ) -> tuple[str, float]:
        """Run SFace recognition on a single face ROI.

        Returns (identity, confidence) tuple.
        """
        if self._face_rec_model is None or self._face_rec_throttle is None:
            return ("unknown", 0.0)
        if self._face_rec_throttle.enrolled_count == 0:
            return ("unknown", 0.0)

        started = time.perf_counter()
        result = "failure"
        reason_code = "recognition_error"
        traced_identity = "unknown"
        traced_score = 0.0
        try:
            x1, y1 = int(face["x1"]), int(face["y1"])
            x2, y2 = int(face["x2"]), int(face["y2"])
            h_img, w_img = frame.shape[:2]
            x1 = max(0, x1); y1 = max(0, y1)
            x2 = min(w_img, x2); y2 = min(h_img, y2)
            if x2 <= x1 or y2 <= y1:
                reason_code = "invalid_face_roi"
                return ("unknown", 0.0)

            # alignCrop requires the original 15-value YuNet detection row.
            # Fall back to the bounded ROI when alignment is unavailable.
            aligned = None
            yunet_detection = face.get("_yunet_detection")
            if yunet_detection is not None:
                try:
                    aligned = self._face_rec_model.alignCrop(
                        frame, yunet_detection,
                    )
                except Exception as exc:
                    logger.debug("SFace alignCrop failed, using ROI: %s", exc)
            if aligned is None or aligned.size == 0:
                aligned = frame[y1:y2, x1:x2]
                if aligned.size == 0:
                    reason_code = "empty_face_roi"
                    return ("unknown", 0.0)

            feature = self._face_rec_model.feature(aligned)
            if feature is None:
                reason_code = "feature_unavailable"
                return ("unknown", 0.0)

            # Compare against enrolled embeddings
            best_name = "unknown"
            best_score = 0.0
            for name, templates in self._face_rec_throttle._enrolled_embeddings.items():
                for emb in templates:
                    score = self._cosine_sim(feature, emb)
                    if score > best_score:
                        best_score = score
                        best_name = name

            threshold = self._face_rec_throttle._cosine_threshold
            result = "success"
            if best_score >= threshold:
                reason_code = "matched"
                traced_identity = best_name
                traced_score = round(float(best_score), 4)
                return (best_name, round(float(best_score), 4))
            reason_code = "no_match"
            traced_score = round(float(best_score), 4)
            return ("unknown", round(float(best_score), 4))

        except Exception as exc:
            if self._disable_fatal_face_model("sface", self._face_rec_model):
                reason_code = "model_fatal"
                result = "failure"
                return ("unknown", 0.0)
            logger.debug("SFace recognition error: %s", exc)
            return ("unknown", 0.0)
        finally:
            vision_timing_trace(
                node="vision_observation",
                module="face_recognition",
                stage="sface_inference",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                result=result,
                force=True,
                inference_sequence=inference_sequence,
                track_id=int(face.get("track_id", -1) or -1),
                identity=traced_identity,
                confidence=traced_score,
                reason_code=reason_code,
            )

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        a_f = a.ravel().astype(np.float64)
        b_f = b.ravel().astype(np.float64)
        dot = np.dot(a_f, b_f)
        norm = np.linalg.norm(a_f) * np.linalg.norm(b_f)
        return float(dot / norm) if norm > 1e-8 else 0.0

    def sync_enrolled_to_throttle(self) -> None:
        """Copy enrolled embeddings from FaceRecognitionProvider to throttle."""
        if self._face_rec_throttle is None:
            return
        with self._inference_lock:
            self._sync_enrolled_to_throttle_locked()

    def _sync_enrolled_to_throttle_locked(self) -> None:
        if self._face_rec_model is None or self._face_rec_throttle is None:
            return
        try:
            from marsdog_vision_interaction.core.face_enrollment_manager import EnrollmentManager
            import cv2
            names = EnrollmentManager.list_enrolled_faces()
            enrolled: dict[str, list[np.ndarray]] = {}
            for name in names:
                paths = EnrollmentManager.get_face_paths(name)
                for p_str in paths:
                    from pathlib import Path
                    if not Path(p_str).exists():
                        continue
                    img = cv2.imread(p_str)
                    if img is None:
                        continue
                    feature = self._face_rec_model.feature(img)
                    if feature is not None:
                        enrolled.setdefault(name, []).append(feature.ravel())
            self._face_rec_throttle.set_enrolled_embeddings(enrolled)
            if enrolled:
                logger.info("Throttle synced: %d enrolled faces", len(enrolled))
        except Exception as exc:
            if self._disable_fatal_face_model("sface", self._face_rec_model):
                return
            logger.debug("Throttle sync error: %s", exc)

    # ── MediaPipe PoseLandmarker ───────────────────────────────

    @staticmethod
    def _coco_behavior_landmarks(keypoints: list[dict[str, Any]]) -> PoseLandmarkSet:
        """Expand native COCO points into the action engine's 33-slot tuple."""

        by_id = {
            int(point.get("id", -1)): point
            for point in keypoints
            if isinstance(point, dict)
        }
        absent = PoseLandmark(
            x=0.0,
            y=0.0,
            z=None,
            visibility=0.0,
            presence=0.0,
        )
        output = [absent for _ in range(33)]
        for coco_id, mediapipe_id in COCO_TO_MEDIAPIPE.items():
            point = by_id.get(coco_id)
            if point is None:
                continue
            try:
                confidence = max(0.0, min(1.0, float(point.get("confidence", 0.0))))
                presence = max(0.0, min(1.0, float(point.get("presence", confidence))))
                z_value = point.get("z")
                z = float(z_value) if z_value is not None else None
                output[mediapipe_id] = PoseLandmark(
                    x=float(point.get("x", 0.0)),
                    y=float(point.get("y", 0.0)),
                    z=z,
                    visibility=confidence,
                    presence=presence,
                )
            except (TypeError, ValueError):
                continue
        return tuple(output)

    def _detect_pose_rknn(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
    ) -> list[dict[str, Any]]:
        """Run YOLOv8 Pose on the NPU and publish native COCO IDs."""

        backend = self._pose_backend
        if backend is None:
            return []
        try:
            detections = backend.process(frame)
            humans: list[dict[str, Any]] = []
            for detection in detections:
                box = np.asarray(detection.box, dtype=np.float32).reshape(4)
                points = np.asarray(detection.keypoints, dtype=np.float32).reshape(17, 3)
                if not np.isfinite(box).all() or not np.isfinite(points).all():
                    continue
                raw_keypoints = [
                    {
                        "id": index,
                        "x": float(point[0]),
                        "y": float(point[1]),
                        "z": None,
                        "confidence": float(point[2]),
                        "presence": float(point[2]),
                    }
                    for index, point in enumerate(points)
                ]
                keypoints = [
                    {
                        **point,
                        "x": round(point["x"], 4),
                        "y": round(point["y"], 4),
                        "confidence": round(point["confidence"], 4),
                        "presence": round(point["presence"], 4),
                    }
                    for point in raw_keypoints
                ]
                humans.append({
                    "x": round(float(box[0]), 4),
                    "y": round(float(box[1]), 4),
                    "w": round(float(box[2]), 4),
                    "h": round(float(box[3]), 4),
                    "confidence": round(float(detection.score), 4),
                    "pose_state": self._classify_pose_coco(raw_keypoints),
                    "keypoint_format": "coco_17",
                    "keypoints": keypoints,
                    "_behavior_landmarks": self._coco_behavior_landmarks(raw_keypoints),
                })
            return humans
        except PoseBackendError as exc:
            self._disable_fatal_pose_model(backend)
            logger.error("RKNN pose inference failed; CPU pose fallback disabled: %s", exc)
            return []
        except Exception as exc:
            # A provider bug or malformed adapter result must not repeatedly
            # call a potentially dead NPU context on subsequent frames.
            self.pose_model_status.update({"ready": False, "fatal": True, "error": str(exc)})
            try:
                backend.close()
            except Exception:
                logger.exception("Pose backend release failed")
            self._pose_backend = None
            logger.error("RKNN pose processing failed; CPU pose fallback disabled: %s", exc)
            return []

    @staticmethod
    def _classify_pose_coco(keypoints: list[dict[str, Any]]) -> str:
        """Classify a coarse state from native COCO points."""

        points = {int(point["id"]): point for point in keypoints}
        try:
            shoulder_y = (float(points[5]["y"]) + float(points[6]["y"])) / 2.0
            hip_y = (float(points[11]["y"]) + float(points[12]["y"])) / 2.0
            knee_y = (float(points[13]["y"]) + float(points[14]["y"])) / 2.0
            if min(float(points[index]["confidence"]) for index in (5, 6, 11, 12)) < 0.2:
                return "unknown"
            torso_len = abs(hip_y - shoulder_y)
            if torso_len < 0.02:
                return "unknown"
            if hip_y > shoulder_y + torso_len * 0.3:
                return "standing" if knee_y > hip_y else "sitting"
            return "lying"
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return "unknown"

    def _detect_pose_mediapipe(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
        timestamp_ms: int,
    ) -> list[dict[str, Any]]:
        """Run MediaPipe PoseLandmarker — combined human detection + 33-point pose.

        Returns:
            List of human dicts with bbox, confidence, pose_state, keypoints.
        """
        if self._pose_landmarker is None:
            return []

        try:
            import mediapipe as mp
            import cv2

            # MediaPipe expects RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb,
            )

            result = self._run_landmarker(
                self._pose_landmarker,
                mp_image,
                timestamp_ms,
            )

            if not result.pose_landmarks:
                return []

            humans = []
            for landmarks in result.pose_landmarks:
                if len(landmarks) == 0:
                    continue

                # Compute bounding box from landmarks
                xs = [lm.x for lm in landmarks if lm.visibility > 0.1]
                ys = [lm.y for lm in landmarks if lm.visibility > 0.1]
                vs = [lm.visibility for lm in landmarks]

                if not xs or not ys:
                    continue

                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                avg_vis = sum(vs) / len(vs)

                bw = max_x - min_x
                bh = max_y - min_y

                if bw < 0.01 or bh < 0.01:
                    continue

                # Map 33 landmarks to keypoints
                keypoints = []
                for i, lm in enumerate(landmarks):
                    keypoints.append({
                        "id": i,
                        "x": round(float(lm.x), 4),
                        "y": round(float(lm.y), 4),
                        "z": round(float(lm.z), 4),
                        "confidence": round(float(lm.visibility), 4),
                        "presence": round(float(getattr(lm, "presence", 1.0)), 4),
                    })

                # Classify pose state from key landmarks
                pose_state = self._classify_pose(landmarks)

                humans.append({
                    "x": round(min_x, 4),
                    "y": round(min_y, 4),
                    "w": round(bw, 4),
                    "h": round(bh, 4),
                    "confidence": round(float(avg_vis), 4),
                    "pose_state": pose_state,
                    "keypoint_format": "mediapipe_33",
                    "keypoints": keypoints,
                    "_behavior_landmarks": pose_landmarks_from_objects(landmarks),
                })

            return humans

        except Exception as exc:
            logger.debug("MediaPipe pose error: %s", exc)
            return []

    # ── MediaPipe HandLandmarker ──────────────────────────────

    def _detect_hands(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
        timestamp_ms: int,
    ) -> list[dict[str, Any]]:
        """Run MediaPipe HandLandmarker — 21-point hand keypoints.

        Returns:
            List of hand dicts with handedness and landmarks.
            Coordinates normalized [0-1] relative to input frame.
        """
        if self._hand_backend is not None:
            try:
                results = self._hand_backend.process(
                    frame,
                    mode=self._landmarker_running_mode,
                    timestamp_ms=timestamp_ms,
                )
                if self._hand_backend.fatal_error:
                    self._disable_fatal_hand_model(self._hand_backend)
                    return []
                hands: list[dict[str, Any]] = []
                for result in results:
                    if not isinstance(result, HandResult):
                        continue
                    rows = result.as_observation()
                    rows["landmarks"] = [
                        {
                            "id": int(point["id"]),
                            "x": round(float(point["x"]), 4),
                            "y": round(float(point["y"]), 4),
                            "z": round(float(point["z"]), 4),
                        }
                        for point in rows["landmarks"]
                    ]
                    rows["_behavior_landmarks"] = tuple(
                        HandLandmark(
                            x=float(point[0]),
                            y=float(point[1]),
                            z=float(point[2]),
                        )
                        for point in result.landmarks
                    )
                    hands.append(rows)
                return hands[:2]
            except Exception as exc:
                if self._disable_fatal_hand_model(self._hand_backend):
                    return []
                logger.debug("Hand backend error: %s", exc)
                return []
        if self._hand_landmarker is None:
            return []

        try:
            import mediapipe as mp
            import cv2

            # MediaPipe expects RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb,
            )

            result = self._run_landmarker(
                self._hand_landmarker,
                mp_image,
                timestamp_ms,
            )

            if not result.hand_landmarks:
                return []

            hands = []
            for i, landmarks in enumerate(result.hand_landmarks):
                if len(landmarks) == 0:
                    continue

                # Handedness: "Left" or "Right"
                handedness = ""
                if result.handedness and i < len(result.handedness):
                    cats = result.handedness[i]
                    if cats:
                        handedness = cats[0].category_name  # "Left" / "Right"

                # Build 21 landmarks
                hand_landmarks = []
                for j, lm in enumerate(landmarks):
                    hand_landmarks.append({
                        "id": j,
                        "x": round(float(lm.x), 4),
                        "y": round(float(lm.y), 4),
                        "z": round(float(lm.z), 4),
                    })

                if hand_landmarks:
                    hands.append({
                        "handedness": handedness,
                        "landmarks": hand_landmarks,
                        "_behavior_landmarks": hand_landmarks_from_objects(landmarks),
                    })

            return hands

        except Exception as exc:
            logger.debug("MediaPipe hand error: %s", exc)
            return []

    # ── Pose classification ────────────────────────────────────

    @staticmethod
    def _classify_pose(landmarks) -> str:
        """Simple pose classifier based on key landmarks.

        Uses shoulder-hip-eye vertical ratios to distinguish
        standing / sitting / lying.
        """
        try:
            # Key indices (MediaPipe pose topology):
            # 11=left_shoulder, 12=right_shoulder
            # 23=left_hip, 24=right_hip
            # 0=nose
            nose_y = landmarks[0].y
            shoulder_y = (landmarks[11].y + landmarks[12].y) / 2
            hip_y = (landmarks[23].y + landmarks[24].y) / 2
            knee_y = (landmarks[25].y + landmarks[26].y) / 2

            # Torso length
            torso_len = abs(hip_y - shoulder_y)
            if torso_len < 0.02:
                return "unknown"

            # Vertical position of hips relative to shoulders
            # Standing: hips well below shoulders, knees below hips
            if hip_y > shoulder_y + torso_len * 0.3:
                if knee_y > hip_y:
                    return "standing"
                return "sitting"

            # Lying: hips and shoulders at similar height
            return "lying"

        except (IndexError, ZeroDivisionError):
            return "unknown"
