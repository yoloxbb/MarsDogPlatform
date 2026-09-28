"""YOLOv8 pose backend for the RK3588 NPU.

The deployed export is a one-class YOLOv8 pose graph.  Its output is
``(1, 56, 8400)``: four ``cx, cy, width, height`` values, one person score,
and 17 ``x, y, score`` COCO keypoints.  Geometry and runtime lifetime live in
this module so the provider and board smoke tool use the same decoder.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import threading
from typing import Any, Mapping

import cv2
import numpy as np

from marsdog_vision_interaction.utils.rknn_runtime import configure_rknn_runtime

from .base import PoseBackendError, PoseResult, validate_frame

logger = logging.getLogger(__name__)

INPUT_SIZE = 640
COCO_KEYPOINT_COUNT = 17
OUTPUT_WIDTH = 4 + 1 + COCO_KEYPOINT_COUNT * 3
POSE_RKNN_SHA256 = "74e0a714e3565c491b724787f7419b343d4e1451e56a8103c5b524c482fc1ce2"
POSE_RKNN_PROFILES: Mapping[str, Mapping[str, Any]] = {
    "yolov8n_pose_fp16": {
        "sha256": POSE_RKNN_SHA256,
        "input_size": INPUT_SIZE,
        "keypoint_format": "coco_17",
        "output_shape": (1, OUTPUT_WIDTH, 8400),
        "input_dtype": "uint8",
        "input_layout": "nhwc",
        "inputs_pass_through": [0],
    },
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _profile_for_model(path: Path, config: Mapping[str, Any] | None) -> tuple[str, Mapping[str, Any]]:
    if not path.is_file():
        raise PoseBackendError(f"RKNN pose model does not exist: {path}")
    options: Mapping[str, Any] = {} if config is None else config
    if not isinstance(options, Mapping):
        raise PoseBackendError("pose_rknn must be a mapping")
    profile_name = str(options.get("profile", "yolov8n_pose_fp16"))
    profile = POSE_RKNN_PROFILES.get(profile_name)
    if profile is None:
        raise PoseBackendError(f"Unsupported pose RKNN profile {profile_name!r}")
    actual = _sha256_file(path)
    if actual != profile["sha256"]:
        raise PoseBackendError(
            f"Unverified RKNN pose model {path.name}: SHA-256 {actual}; "
            f"profile {profile_name!r} requires {profile['sha256']}"
        )
    return profile_name, profile


def _core_mask_value(rknn_class: Any, value: Any) -> Any:
    if value is None:
        value = "auto"
    if isinstance(value, (bool, np.bool_)):
        raise PoseBackendError("Invalid RKNN core_mask boolean")
    if isinstance(value, (int, np.integer)):
        value = str(int(value))
    names = {
        "auto": "NPU_CORE_AUTO",
        "0": "NPU_CORE_0",
        "1": "NPU_CORE_1",
        "2": "NPU_CORE_2",
        "0_1": "NPU_CORE_0_1",
        "0_1_2": "NPU_CORE_0_1_2",
    }
    name = names.get(str(value).strip().lower())
    if name is None:
        raise PoseBackendError(
            f"Invalid RKNN core_mask {value!r}; expected auto, 0, 1, 2, 0_1 or 0_1_2"
        )
    try:
        return getattr(rknn_class, name)
    except AttributeError as exc:
        raise PoseBackendError(f"RKNN Lite does not expose {name}") from exc


def letterbox_geometry(
    width: int,
    height: int,
    size: int = INPUT_SIZE,
) -> tuple[float, int, int, int, int]:
    """Return scale, resized dimensions, and centered integer padding."""

    if width <= 0 or height <= 0 or size <= 0:
        raise ValueError("letterbox dimensions must be positive")
    scale = min(float(size) / width, float(size) / height)
    resized_width = max(1, min(size, int(round(width * scale))))
    resized_height = max(1, min(size, int(round(height * scale))))
    return (
        scale,
        resized_width,
        resized_height,
        (size - resized_width) // 2,
        (size - resized_height) // 2,
    )


def letterbox_frame(frame: Any, size: int = INPUT_SIZE) -> tuple[np.ndarray, tuple[float, int, int, int, int]]:
    """Convert a BGR frame to contiguous RGB uint8 model input."""

    image = validate_frame(frame)
    height, width = image.shape[:2]
    geometry = letterbox_geometry(width, height, size)
    _scale, resized_width, resized_height, pad_x, pad_y = geometry
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    # Ultralytics' YOLO export uses the 114 gray letterbox value.  Keeping the
    # same value matters around borders because the trained graph sees this
    # pixel distribution during calibration.
    output = np.full((size, size, 3), 114, dtype=np.uint8)
    output[pad_y : pad_y + resized_height, pad_x : pad_x + resized_width] = resized
    return np.ascontiguousarray(output), geometry


def _iou(first: np.ndarray, second: np.ndarray) -> float:
    fx, fy, fw, fh = [float(value) for value in first]
    sx, sy, sw, sh = [float(value) for value in second]
    left, top = max(fx, sx), max(fy, sy)
    right, bottom = min(fx + fw, sx + sw), min(fy + fh, sy + sh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = max(0.0, fw) * max(0.0, fh) + max(0.0, sw) * max(0.0, sh) - intersection
    return intersection / union if union > 1e-12 else 0.0


def _as_output_array(outputs: Any) -> np.ndarray:
    if isinstance(outputs, Mapping):
        values = list(outputs.values())
    elif isinstance(outputs, np.ndarray):
        values = [outputs]
    else:
        try:
            values = list(outputs)
        except TypeError as exc:
            raise PoseBackendError("YOLO pose inference returned a non-sequence") from exc
    if len(values) != 1:
        raise PoseBackendError(f"YOLO pose inference returned {len(values)} outputs; expected one")
    output = np.asarray(values[0], dtype=np.float32)
    expected_shape = (1, OUTPUT_WIDTH, 8400)
    if output.shape != expected_shape:
        raise PoseBackendError(
            f"YOLO pose output shape {tuple(output.shape)} is invalid; expected {expected_shape}"
        )
    if not np.isfinite(output).all():
        raise PoseBackendError("YOLO pose output contains non-finite values")
    return output[0].T


def decode_yolov8_pose_outputs(
    outputs: Any,
    *,
    score_threshold: float = 0.30,
    nms_threshold: float = 0.45,
    max_num_poses: int = 4,
    model_size: int = INPUT_SIZE,
) -> list[PoseResult]:
    """Decode, NMS, and return model-space YOLOv8 pose detections.

    Results are still in model pixel coordinates.  ``undo_letterbox`` maps
    them to source-frame normalized coordinates after the source shape is
    known.
    """

    rows = _as_output_array(outputs)
    threshold = float(score_threshold)
    candidates: list[PoseResult] = []
    for row in rows:
        score = float(row[4])
        if score < threshold:
            continue
        cx, cy, width, height = [float(value) for value in row[:4]]
        if not np.isfinite((cx, cy, width, height, score)).all() or width <= 0.0 or height <= 0.0:
            continue
        keypoints = row[5:].reshape(COCO_KEYPOINT_COUNT, 3).copy()
        if not np.isfinite(keypoints).all():
            continue
        box = np.asarray((cx - width / 2.0, cy - height / 2.0, width, height), dtype=np.float32)
        keypoints[:, 2] = np.clip(keypoints[:, 2], 0.0, 1.0)
        candidates.append(PoseResult(box=box, score=score, keypoints=keypoints))

    pending = sorted(candidates, key=lambda item: item.score, reverse=True)
    kept: list[PoseResult] = []
    limit = max(1, int(max_num_poses))
    while pending and len(kept) < limit:
        current = pending.pop(0)
        kept.append(current)
        pending = [item for item in pending if _iou(current.box, item.box) < float(nms_threshold)]
    return kept


def undo_letterbox(
    detection: PoseResult,
    *,
    width: int,
    height: int,
    geometry: tuple[float, int, int, int, int] | None = None,
    model_size: int = INPUT_SIZE,
) -> PoseResult:
    """Map one model-space detection to source normalized coordinates."""

    if width <= 0 or height <= 0:
        raise ValueError("source dimensions must be positive")
    geometry = geometry or letterbox_geometry(width, height, model_size)
    _scale, resized_width, resized_height, pad_x, pad_y = geometry
    # cv2.resize uses the rounded output dimensions, so the effective scale
    # can differ slightly between axes on odd source sizes.
    scale_x = resized_width / width
    scale_y = resized_height / height
    x, y, box_width, box_height = [float(value) for value in detection.box]
    source_x = (x - pad_x) / scale_x
    source_y = (y - pad_y) / scale_y
    source_w = box_width / scale_x
    source_h = box_height / scale_y
    left = max(0.0, min(float(width), source_x)) / width
    top = max(0.0, min(float(height), source_y)) / height
    right = max(0.0, min(float(width), source_x + source_w)) / width
    bottom = max(0.0, min(float(height), source_y + source_h)) / height
    detection.box = np.asarray((left, top, max(0.0, right - left), max(0.0, bottom - top)), dtype=np.float32)

    points = detection.keypoints
    points[:, 0] = (points[:, 0] - pad_x) / resized_width
    points[:, 1] = (points[:, 1] - pad_y) / resized_height
    outside = (
        (points[:, 0] < 0.0)
        | (points[:, 0] > 1.0)
        | (points[:, 1] < 0.0)
        | (points[:, 1] > 1.0)
    )
    points[:, 0] = np.clip(points[:, 0], 0.0, 1.0)
    points[:, 1] = np.clip(points[:, 1], 0.0, 1.0)
    points[outside, 2] = 0.0
    return detection


def _release_runtime(runtime: Any) -> None:
    release = getattr(runtime, "release", None)
    if callable(release):
        try:
            release()
        except Exception:
            logger.exception("RKNN pose runtime release failed")


class RKNNPoseBackend:
    """Single YOLOv8 pose RKNN runtime with fatal error latching."""

    backend_name = "rknn"
    keypoint_format = "coco_17"

    def __init__(
        self,
        model_path: str | Path,
        *,
        config: Mapping[str, Any] | None = None,
        runtime_library: str = "",
        score_threshold: float = 0.30,
        nms_threshold: float = 0.45,
        max_num_poses: int = 4,
    ) -> None:
        self._lock = threading.RLock()
        self._runtime: Any = None
        self._closed = False
        self._fatal_error: str | None = None
        self._score_threshold = float(score_threshold)
        self._nms_threshold = float(nms_threshold)
        self._max_num_poses = max(1, int(max_num_poses))
        self.model_path = str(model_path)
        self.profile_name, self.profile = _profile_for_model(Path(model_path), config)
        try:
            configure_rknn_runtime(str(runtime_library or ""))
            from rknnlite.api import RKNNLite

            core_mask = _core_mask_value(RKNNLite, (config or {}).get("core_mask", "auto"))
            self._runtime = RKNNLite(verbose=False)
            result = self._runtime.load_rknn(str(model_path))
            if result != 0:
                raise PoseBackendError(f"pose model load failed: return code {result}")
            result = self._runtime.init_runtime(core_mask=core_mask)
            if result != 0:
                raise PoseBackendError(f"pose runtime initialization failed: return code {result}")
        except ImportError as exc:
            self.close()
            raise PoseBackendError("RKNN pose model requested but rknn-toolkit-lite2 is unavailable") from exc
        except Exception:
            self.close()
            raise

    @property
    def fatal_error(self) -> str | None:
        with self._lock:
            return self._fatal_error

    def _mark_fatal_locked(self, exc: BaseException) -> None:
        if self._fatal_error is None:
            self._fatal_error = str(exc)
        self._close_locked()

    def _close_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        runtime, self._runtime = self._runtime, None
        if runtime is not None:
            _release_runtime(runtime)

    def process(self, frame: np.ndarray) -> list[PoseResult]:
        with self._lock:
            if self._fatal_error:
                raise PoseBackendError(self._fatal_error)
            if self._closed or self._runtime is None:
                raise PoseBackendError("RKNN pose runtime is unavailable")
            tensor, geometry = letterbox_frame(frame)
            try:
                outputs = self._runtime.inference(
                    inputs=[tensor[None, ...]],
                    data_format=["nhwc"],
                    inputs_pass_through=[0],
                )
                detections = decode_yolov8_pose_outputs(
                    outputs,
                    score_threshold=self._score_threshold,
                    nms_threshold=self._nms_threshold,
                    max_num_poses=self._max_num_poses,
                )
                image = validate_frame(frame)
                source_height, source_width = image.shape[:2]
                for detection in detections:
                    undo_letterbox(
                        detection,
                        width=source_width,
                        height=source_height,
                        geometry=geometry,
                    )
                return detections
            except PoseBackendError as exc:
                self._mark_fatal_locked(exc)
                raise
            except Exception as exc:
                error = PoseBackendError(f"RKNN pose inference failed: {exc}")
                self._mark_fatal_locked(error)
                raise error from exc

    def close(self) -> None:
        with self._lock:
            self._close_locked()
