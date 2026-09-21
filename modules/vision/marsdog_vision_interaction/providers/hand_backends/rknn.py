"""RKNN Lite palm + hand landmark backend.

The converted graphs use the MediaPipe palm detector contract: 2016 anchors,
18 regression values and one confidence per anchor, followed by a 224 square
landmark graph.  Geometry lives here so the standalone checker and the ROS
provider exercise exactly the same decoder and tracker.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import math
from pathlib import Path
import threading
from typing import Any, Mapping

import cv2
import numpy as np

from marsdog_vision_interaction.utils.rknn_runtime import configure_rknn_runtime

from .base import HandBackend, HandBackendError, HandResult, validate_frame

logger = logging.getLogger(__name__)

DETECTOR_SIZE = 192
LANDMARK_SIZE = 224
DETECTOR_STRIDES = (8, 16, 16, 16)
DETECTOR_MIN_SCALE = 0.1484375
DETECTOR_MAX_SCALE = 0.75
DEFAULT_SCORE_THRESHOLD = 0.30
DEFAULT_NMS_THRESHOLD = 0.30
DEFAULT_PRESENCE_THRESHOLD = 0.50

HAND_DETECTOR_FP16_SHA256 = "588b2b3749a864766de23caccd12b979305158dad8ea836098529c3f1874c373"
HAND_LANDMARK_FP16_SHA256 = "9c973f44a100ebdd9aacbe54e7495fe046b2e94fe900f296d3c7a50189a0e7c4"
HAND_RKNN_PROFILES: Mapping[str, Mapping[str, Any]] = {
    "hand_fp16": {
        "detector_sha256": HAND_DETECTOR_FP16_SHA256,
        "landmark_sha256": HAND_LANDMARK_FP16_SHA256,
        "detector_dtype": "uint8",
        "landmark_dtype": "uint8",
        "input_size": (192, 224),
        # RKNN output is the palm classifier logit.  The original graph
        # decoder applies sigmoid before thresholding; never infer this from
        # the range of one frame because a valid frame can contain only
        # positive logits.
        "score_activation": "sigmoid",
    },
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_profile(
    detector_path: Path,
    landmark_path: Path,
    config: Mapping[str, Any] | None,
) -> str:
    if not detector_path.is_file():
        raise HandBackendError(f"RKNN hand detector does not exist: {detector_path}")
    if not landmark_path.is_file():
        raise HandBackendError(f"RKNN hand landmark model does not exist: {landmark_path}")
    options: Mapping[str, Any] = {} if config is None else config
    if not isinstance(options, Mapping):
        raise HandBackendError("hand_rknn must be a mapping")
    profile_name = str(options.get("profile", "hand_fp16"))
    profile = HAND_RKNN_PROFILES.get(profile_name)
    if profile is None:
        raise HandBackendError(f"Unsupported hand RKNN profile {profile_name!r}")
    actual_detector = _sha256_file(detector_path)
    actual_landmark = _sha256_file(landmark_path)
    if actual_detector != profile["detector_sha256"]:
        raise HandBackendError(
            f"Unverified RKNN hand detector {detector_path.name}: SHA-256 {actual_detector}; "
            f"profile {profile_name!r} requires {profile['detector_sha256']}"
        )
    if actual_landmark != profile["landmark_sha256"]:
        raise HandBackendError(
            f"Unverified RKNN hand landmark model {landmark_path.name}: SHA-256 {actual_landmark}; "
            f"profile {profile_name!r} requires {profile['landmark_sha256']}"
        )
    return profile_name


def _core_mask_value(rknn_class: Any, value: Any) -> Any:
    if value is None:
        value = "auto"
    if isinstance(value, (bool, np.bool_)):
        raise HandBackendError("Invalid RKNN core_mask boolean")
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
        raise HandBackendError(
            f"Invalid RKNN core_mask {value!r}; expected auto, 0, 1, 2, 0_1 or 0_1_2"
        )
    try:
        return getattr(rknn_class, name)
    except AttributeError as exc:
        raise HandBackendError(f"RKNN Lite does not expose {name}") from exc


def _release_runtime(runtime: Any) -> None:
    release = getattr(runtime, "release", None)
    if callable(release):
        try:
            release()
        except Exception:
            logger.exception("RKNN hand runtime release failed")


def _anchors() -> np.ndarray:
    scales = [
        DETECTOR_MIN_SCALE
        + (DETECTOR_MAX_SCALE - DETECTOR_MIN_SCALE) * index / 3.0
        for index in range(4)
    ]
    anchors: list[tuple[float, float, float, float]] = []
    # The graph has one stride-8 layer and three equal stride-16 layers.  The
    # SSD anchor calculator groups equal strides into one feature map, so the
    # six stride-16 slots must be emitted for each cell before moving on.
    groups = (
        (8, (scales[0], math.sqrt(scales[0] * scales[1]))),
        (
            16,
            (
                scales[1],
                math.sqrt(scales[1] * scales[2]),
                scales[2],
                math.sqrt(scales[2] * scales[3]),
                scales[3],
                math.sqrt(scales[3] * 1.0),
            ),
        ),
    )
    for stride, slots in groups:
        feature_map = math.ceil(DETECTOR_SIZE / stride)
        for y in range(feature_map):
            for x in range(feature_map):
                center = ((x + 0.5) / feature_map, (y + 0.5) / feature_map)
                for _ in slots:
                    anchors.append((center[0], center[1], 1.0, 1.0))
    output = np.asarray(anchors, dtype=np.float32)
    if output.shape != (2016, 4):
        raise HandBackendError(f"unexpected palm anchor shape {output.shape}")
    return output


ANCHORS = _anchors()


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -80.0, 80.0)))


def _confidence(values: Any, *, activation: str = "auto") -> np.ndarray:
    output = np.asarray(values, dtype=np.float32).reshape(-1)
    if output.size != 2016 or not np.isfinite(output).all():
        raise HandBackendError(f"palm score output has invalid shape or values: {output.shape}")
    if activation == "sigmoid":
        return _sigmoid(output)
    if activation in {"probability", "identity"}:
        if activation == "probability" and (
            float(output.min(initial=0.0)) < 0.0
            or float(output.max(initial=0.0)) > 1.0
        ):
            raise HandBackendError("palm probability output is outside [0, 1]")
        return output
    if activation != "auto":
        raise HandBackendError(f"unsupported palm score activation {activation!r}")
    # Compatibility mode for direct decoder callers.  Deployed profiles bind
    # the activation explicitly and never take this data-dependent branch.
    if float(output.min(initial=0.0)) < 0.0 or float(output.max(initial=0.0)) > 1.0:
        return _sigmoid(output)
    return output


def _decode_raw_detections(
    regressors: Any,
    scores: Any,
    *,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    score_activation: str = "auto",
) -> list["_PalmDetection"]:
    regressions = np.asarray(regressors, dtype=np.float32)
    if regressions.size != 2016 * 18:
        raise HandBackendError(
            f"palm regression output has {regressions.size} values; expected {2016 * 18}"
        )
    regressions = regressions.reshape(2016, 18)
    confidence = _confidence(scores, activation=score_activation)
    if not np.isfinite(regressions).all():
        raise HandBackendError("palm regression output contains non-finite values")
    decoded = regressions / float(DETECTOR_SIZE)
    centers = decoded[:, :2] + ANCHORS[:, :2]
    size = decoded[:, 2:4]
    # The graph stores width and height directly in model coordinates.
    boxes = np.column_stack((centers - size / 2.0, size))
    points = decoded[:, 4:].reshape(2016, 7, 2) + ANCHORS[:, None, :2]
    output: list[_PalmDetection] = []
    for box, keypoints, score in zip(boxes, points, confidence):
        if float(score) < float(score_threshold):
            continue
        if not np.isfinite(box).all() or not np.isfinite(keypoints).all():
            continue
        if box[2] <= 0.0 or box[3] <= 0.0:
            continue
        output.append(_PalmDetection(float(score), box.astype(np.float32), keypoints.astype(np.float32)))
    return output


@dataclass(slots=True)
class _PalmDetection:
    score: float
    box: np.ndarray  # normalized top-left x/y/width/height
    keypoints: np.ndarray  # normalized x/y in model square


def _iou(first: np.ndarray, second: np.ndarray) -> float:
    fx, fy, fw, fh = [float(value) for value in first]
    sx, sy, sw, sh = [float(value) for value in second]
    left, top = max(fx, sx), max(fy, sy)
    right, bottom = min(fx + fw, sx + sw), min(fy + fh, sy + sh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = max(0.0, fw) * max(0.0, fh) + max(0.0, sw) * max(0.0, sh) - intersection
    return intersection / union if union > 1e-12 else 0.0


def _weighted_nms(
    candidates: list[_PalmDetection],
    threshold: float = DEFAULT_NMS_THRESHOLD,
    limit: int = 2,
) -> list[_PalmDetection]:
    """Merge overlapping palm candidates instead of selecting a duplicate."""

    pending = sorted(candidates, key=lambda item: item.score, reverse=True)
    kept: list[_PalmDetection] = []
    while pending and len(kept) < limit:
        seed = pending.pop(0)
        cluster = [seed]
        remaining: list[_PalmDetection] = []
        for candidate in pending:
            if _iou(seed.box, candidate.box) >= threshold:
                cluster.append(candidate)
            else:
                remaining.append(candidate)
        pending = remaining
        weights = np.asarray([max(item.score, 1e-6) for item in cluster], dtype=np.float32)
        weight_sum = float(weights.sum())
        box = sum(item.box * weight for item, weight in zip(cluster, weights)) / weight_sum
        keypoints = sum(
            item.keypoints * weight for item, weight in zip(cluster, weights)
        ) / weight_sum
        kept.append(_PalmDetection(max(item.score for item in cluster), box, keypoints))
    return kept


def decode_palm_outputs(
    outputs: Any,
    *,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    nms_threshold: float = DEFAULT_NMS_THRESHOLD,
    max_hands: int = 2,
    score_activation: str = "auto",
) -> list[_PalmDetection]:
    """Decode RKNN output tensors, accepting list or mapping output forms."""

    if isinstance(outputs, Mapping):
        regressors = outputs.get("regressors", outputs.get("regression"))
        scores = outputs.get("scores", outputs.get("score"))
        if regressors is None or scores is None:
            raise HandBackendError("palm output mapping requires regressors and scores")
    else:
        try:
            values = list(outputs) if not isinstance(outputs, np.ndarray) else [outputs]
        except TypeError as exc:
            raise HandBackendError("palm inference returned a non-sequence") from exc
        if len(values) != 2:
            raise HandBackendError(f"palm inference returned {len(values)} outputs; expected 2")
        arrays = [np.asarray(value) for value in values]
        if arrays[0].size == 2016 * 18:
            regressors, scores = arrays
        elif arrays[1].size == 2016 * 18:
            scores, regressors = arrays
        else:
            raise HandBackendError("palm outputs do not contain a 2016x18 regression tensor")
    detections = _decode_raw_detections(
        regressors,
        scores,
        score_threshold=float(score_threshold),
        score_activation=score_activation,
    )
    return _weighted_nms(detections, float(nms_threshold), max(1, min(2, int(max_hands))))


def letterbox_geometry(width: int, height: int, size: int = DETECTOR_SIZE) -> tuple[float, int, int, int, int]:
    """Return scale, resized dimensions and centered zero-padding."""

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


def _cpu_letterbox(frame: np.ndarray, size: int = DETECTOR_SIZE) -> np.ndarray:
    image = validate_frame(frame)
    height, width = image.shape[:2]
    _scale, resized_width, resized_height, pad_x, pad_y = letterbox_geometry(width, height, size)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    output = np.zeros((size, size, 3), dtype=np.uint8)
    output[pad_y : pad_y + resized_height, pad_x : pad_x + resized_width] = resized
    return output


def _undo_letterbox(
    detection: _PalmDetection,
    *,
    width: int,
    height: int,
    size: int = DETECTOR_SIZE,
) -> None:
    scale, resized_width, resized_height, pad_x, pad_y = letterbox_geometry(width, height, size)
    x, y, box_width, box_height = [float(value) for value in detection.box]
    source_x = (x * size - pad_x) / scale
    source_y = (y * size - pad_y) / scale
    detection.box[:] = (
        source_x / width,
        source_y / height,
        box_width * size / scale / width,
        box_height * size / scale / height,
    )
    points = detection.keypoints
    points[:, 0] = (points[:, 0] * size - pad_x) / scale / width
    points[:, 1] = (points[:, 1] * size - pad_y) / scale / height


def _roi_points(center_x: float, center_y: float, size: float, angle: float) -> np.ndarray:
    half = size * 0.5
    corners = np.asarray([[-half, -half], [half, -half], [-half, half]], dtype=np.float32)
    cosine, sine = math.cos(angle), math.sin(angle)
    rotation = np.asarray(((cosine, -sine), (sine, cosine)), dtype=np.float32)
    return corners @ rotation.T + np.asarray((center_x, center_y), dtype=np.float32)


def _sample_detection_roi(frame: np.ndarray, detection: _PalmDetection) -> tuple[np.ndarray, np.ndarray, float, float]:
    height, width = frame.shape[:2]
    x, y, box_width, box_height = [float(value) for value in detection.box]
    center_x, center_y = (x + box_width / 2.0) * width, (y + box_height / 2.0) * height
    wrist, mcp = detection.keypoints[0], detection.keypoints[2]
    angle = math.atan2(float(mcp[1] - wrist[1]) * height, float(mcp[0] - wrist[0]) * width) + math.pi / 2.0
    long_side = max(box_width * width, box_height * height)
    roi_size = max(1.0, long_side * 2.6)
    # Shift toward the fingers in the upright ROI coordinate system.  This is
    # the MediaPipe rect transformation's -0.5 y shift.
    cosine, sine = math.cos(angle), math.sin(angle)
    center_x += 0.5 * box_height * height * sine
    center_y -= 0.5 * box_height * height * cosine
    points = _roi_points(center_x, center_y, roi_size, angle)
    destination = np.asarray([[0.0, 0.0], [LANDMARK_SIZE, 0.0], [0.0, LANDMARK_SIZE]], dtype=np.float32)
    matrix = cv2.getAffineTransform(points, destination)
    roi = cv2.warpAffine(
        frame,
        matrix,
        (LANDMARK_SIZE, LANDMARK_SIZE),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    return roi, matrix, angle, roi_size


def _sample_tracking_roi(frame: np.ndarray, result: HandResult) -> tuple[np.ndarray, np.ndarray, float, float]:
    points = result.landmarks[:, :2].copy()
    height, width = frame.shape[:2]
    points_px = points * np.asarray((width, height), dtype=np.float32)
    wrist = points_px[0]
    middle_mcp = 0.25 * (points_px[5] + points_px[13]) + 0.5 * points_px[9]
    angle = math.pi / 2.0 - math.atan2(
        float(wrist[1] - middle_mcp[1]),
        float(middle_mcp[0] - wrist[0]),
    )
    selected = points_px[[0, 1, 2, 3, 5, 6, 9, 10, 13, 14, 17, 18]]
    axis_center = 0.5 * (selected.min(axis=0) + selected.max(axis=0))
    cosine, sine = math.cos(angle), math.sin(angle)
    rotation = np.asarray(((cosine, -sine), (sine, cosine)), dtype=np.float32)
    # Row-vector multiplication by R converts source coordinates to ROI-local
    # coordinates.  Reconstruct the transformed center before applying the
    # calculator's shift_y=-.1 in local coordinates.
    local = (selected - axis_center) @ rotation
    local_center = 0.5 * (local.min(axis=0) + local.max(axis=0))
    center = axis_center + local_center @ rotation.T
    local_extent = local.max(axis=0) - local.min(axis=0)
    extent = max(float(local_extent[0]), float(local_extent[1])) * 2.0
    extent = max(1.0, extent)
    shift_local = np.asarray((0.0, -0.1 * float(local_extent[1])), dtype=np.float32)
    center += shift_local @ rotation.T
    roi_points = _roi_points(float(center[0]), float(center[1]), extent, angle)
    destination = np.asarray([[0.0, 0.0], [LANDMARK_SIZE, 0.0], [0.0, LANDMARK_SIZE]], dtype=np.float32)
    matrix = cv2.getAffineTransform(roi_points, destination)
    roi = cv2.warpAffine(
        frame, matrix, (LANDMARK_SIZE, LANDMARK_SIZE),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
    )
    return roi, matrix, angle, extent


def _project_landmarks(
    matrix: np.ndarray,
    raw: np.ndarray,
    *,
    image_width: int,
    image_height: int,
    roi_size_px: float,
) -> np.ndarray:
    inverse = cv2.invertAffineTransform(matrix)
    xy = np.column_stack((raw[:, :2], np.ones(len(raw), dtype=np.float32)))
    projected_px = xy @ inverse.T
    projected = np.empty((len(raw), 3), dtype=np.float32)
    projected[:, 0] = projected_px[:, 0] / float(image_width)
    projected[:, 1] = projected_px[:, 1] / float(max(1, image_height))
    # MediaPipe's hand graph applies normalize_z=0.4.  Preserve that scale
    # while mapping the ROI pixel depth back to the normalized image width.
    projected[:, 2] = raw[:, 2] * float(roi_size_px) / float(LANDMARK_SIZE * 0.4 * max(1, image_width))
    return projected


def project_landmarks(matrix: np.ndarray, raw: np.ndarray, image_width: int, roi_size_px: float, image_height: int | None = None) -> np.ndarray:
    """Public geometry helper used by deterministic tests and reports."""

    return _project_landmarks(
        np.asarray(matrix, dtype=np.float32),
        np.asarray(raw, dtype=np.float32).reshape(21, 3),
        image_width=int(image_width),
        image_height=int(image_height if image_height is not None else image_width),
        roi_size_px=float(roi_size_px),
    )


class RKNNHandBackend(HandBackend):
    backend_name = "rknn"

    def __init__(
        self,
        detector_path: str | Path,
        landmark_path: str | Path,
        *,
        config: Mapping[str, Any] | None = None,
        runtime_library: str = "",
        running_mode: str = "video",
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        nms_threshold: float = DEFAULT_NMS_THRESHOLD,
        presence_threshold: float = DEFAULT_PRESENCE_THRESHOLD,
        detection_interval: int = 5,
        preprocessing: str = "cpu",
        rga_preprocessor: Any = None,
        max_hands: int = 2,
    ) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._fatal_error: str | None = None
        self._detector: Any = None
        self._landmarker: Any = None
        self._tracks: list[HandResult] = []
        self._calls_since_detection = 0
        self._last_shape: tuple[int, int] | None = None
        self._last_timestamp_ms: int | None = None
        self._score_threshold = float(score_threshold)
        self._nms_threshold = float(nms_threshold)
        self._presence_threshold = float(presence_threshold)
        self._detection_interval = max(1, int(detection_interval))
        self._max_hands = max(1, min(2, int(max_hands)))
        self._preprocessing = str(preprocessing or "cpu").strip().lower()
        self._running_mode = str(running_mode or "video").strip().lower()
        if self._running_mode not in {"image", "video"}:
            raise HandBackendError("hand running_mode must be image or video")
        self._rga = rga_preprocessor
        if self._preprocessing not in {"cpu", "rga"}:
            raise HandBackendError("hand preprocessing must be cpu or rga")
        if self._preprocessing == "rga" and self._rga is None:
            try:
                from marsdog_vision_interaction.utils.hand_rga import RgaPreprocessor

                # An explicit RGA selection must never silently become the
                # CPU reference path.  Keep the mode in the constructor even
                # though RgaPreprocessor currently defaults to it, so a
                # future default change cannot invalidate diagnostics.
                self._rga = RgaPreprocessor(mode="rga")
            except Exception as exc:
                raise HandBackendError(f"RGA hand preprocessing requested but unavailable: {exc}") from exc

        try:
            profile_name = _validate_profile(Path(detector_path), Path(landmark_path), config)
        except Exception:
            # RGA may already have loaded a native helper before model
            # fingerprint validation.  Unwind it even though no RKNN context
            # has been created yet.
            self._close_locked()
            raise
        self._score_activation = str(
            HAND_RKNN_PROFILES[profile_name].get("score_activation", "auto")
        )
        try:
            configure_rknn_runtime(str(runtime_library or ""))
            from rknnlite.api import RKNNLite
            core_mask = _core_mask_value(RKNNLite, (config or {}).get("core_mask", "auto"))
            self._detector = RKNNLite(verbose=False)
            result = self._detector.load_rknn(str(detector_path))
            if result != 0:
                raise HandBackendError(f"hand detector load failed: return code {result}")
            result = self._detector.init_runtime(core_mask=core_mask)
            if result != 0:
                raise HandBackendError(f"hand detector runtime initialization failed: return code {result}")
            self._landmarker = RKNNLite(verbose=False)
            result = self._landmarker.load_rknn(str(landmark_path))
            if result != 0:
                raise HandBackendError(f"hand landmark model load failed: return code {result}")
            result = self._landmarker.init_runtime(core_mask=core_mask)
            if result != 0:
                raise HandBackendError(f"hand landmark runtime initialization failed: return code {result}")
        except ImportError as exc:
            self.close()
            raise HandBackendError("RKNN hand model requested but rknn-toolkit-lite2 is unavailable") from exc
        except Exception:
            self.close()
            raise

    @property
    def fatal_error(self) -> str | None:
        with self._lock:
            return self._fatal_error

    @property
    def preprocessing_mode(self) -> str:
        return self._preprocessing if self._rga is not None or self._preprocessing == "cpu" else "unavailable"

    def _mark_fatal_locked(self, exc: BaseException) -> None:
        if self._fatal_error is None:
            self._fatal_error = str(exc)
        self._tracks.clear()
        self._close_locked()

    def _close_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        detector, self._detector = self._detector, None
        landmarker, self._landmarker = self._landmarker, None
        if detector is not None:
            _release_runtime(detector)
        if landmarker is not None:
            _release_runtime(landmarker)
        preprocessor, self._rga = self._rga, None
        close = getattr(preprocessor, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.exception("RGA hand preprocessor release failed")

    def _detector_input(self, frame: np.ndarray) -> np.ndarray:
        if self._preprocessing == "rga":
            try:
                output = self._rga.letterbox(frame, size=DETECTOR_SIZE)
            except Exception as exc:
                # RGA is part of the selected inference path.  A native
                # failure must release the RKNN contexts and become a single
                # fatal transition; otherwise every subsequent frame would
                # retry the same broken operation indefinitely.
                error = HandBackendError(f"RGA hand preprocessing failed: {exc}")
                self._mark_fatal_locked(error)
                raise error from exc
            tensor = np.asarray(output)
            if tensor.shape != (DETECTOR_SIZE, DETECTOR_SIZE, 3) or tensor.dtype != np.uint8:
                error = HandBackendError(
                    f"RGA hand preprocessor returned {tensor.shape}/{tensor.dtype}; expected (192, 192, 3)/uint8"
                )
                self._mark_fatal_locked(error)
                raise error
            return np.ascontiguousarray(tensor)
        return _cpu_letterbox(frame)

    def _inference(self, runtime: Any, tensor: np.ndarray) -> Any:
        if runtime is None:
            raise HandBackendError("RKNN hand runtime is unavailable")
        try:
            return runtime.inference(
                inputs=[tensor[None, ...]],
                data_format=["nhwc"],
                inputs_pass_through=[0],
            )
        except Exception as exc:
            self._mark_fatal_locked(HandBackendError(f"RKNN hand inference failed: {exc}"))
            raise HandBackendError(str(self._fatal_error)) from exc

    def _run_landmark(self, frame: np.ndarray, source: HandResult | _PalmDetection) -> HandResult | None:
        if isinstance(source, _PalmDetection):
            roi, matrix, angle, roi_size = _sample_detection_roi(frame, source)
            score, box = source.score, source.box.copy()
        else:
            roi, matrix, angle, roi_size = _sample_tracking_roi(frame, source)
            score, box = source.score, source.box.copy() if source.box is not None else None
        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        outputs = self._inference(self._landmarker, np.ascontiguousarray(rgb, dtype=np.uint8))
        try:
            values = list(outputs) if not isinstance(outputs, Mapping) else [
                outputs.get("landmarks"), outputs.get("presence"), outputs.get("handedness")
            ]
            if len(values) < 3 or any(value is None for value in values[:3]):
                raise HandBackendError("hand landmark output requires landmarks, presence and handedness")
            raw = np.asarray(values[0], dtype=np.float32)
            if raw.size != 63:
                raise HandBackendError(f"hand landmark tensor has {raw.size} values; expected 63")
            raw = raw.reshape(21, 3)
            presence_values = np.asarray(values[1], dtype=np.float32).reshape(-1)
            handedness_values = np.asarray(values[2], dtype=np.float32).reshape(-1)
            if not len(presence_values) or not len(handedness_values):
                raise HandBackendError("hand landmark scalar outputs are empty")
            presence = float(presence_values[0])
            handedness_score = float(handedness_values[0])
            if not np.isfinite(raw).all() or not np.isfinite((presence, handedness_score)).all():
                raise HandBackendError("hand landmark outputs contain non-finite values")
            if presence < self._presence_threshold:
                return None
            projected = _project_landmarks(
                matrix,
                raw,
                image_width=frame.shape[1],
                image_height=frame.shape[0],
                roi_size_px=roi_size,
            )
            result = HandResult(
                landmarks=projected,
                handedness="Right" if handedness_score >= 0.5 else "Left",
                handedness_score=handedness_score,
                score=score,
                presence=presence,
                box=box,
                rotation=angle,
                _roi_matrix=matrix,
                _roi_size_px=roi_size,
            )
            return result
        except HandBackendError as exc:
            self._mark_fatal_locked(exc)
            raise
        except Exception as exc:
            error = HandBackendError(f"hand landmark output contract failed: {exc}")
            self._mark_fatal_locked(error)
            raise error from exc

    def _detect(self, frame: np.ndarray) -> list[HandResult]:
        tensor = self._detector_input(frame)
        outputs = self._inference(self._detector, tensor)
        try:
            detections = decode_palm_outputs(
                outputs,
                score_threshold=self._score_threshold,
                nms_threshold=self._nms_threshold,
                max_hands=self._max_hands,
                score_activation=self._score_activation,
            )
        except HandBackendError as exc:
            # Output shape/order/value failures indicate an incompatible or
            # corrupted deployed graph, rather than a bad camera frame.
            self._mark_fatal_locked(exc)
            raise
        for detection in detections:
            _undo_letterbox(
                detection,
                width=frame.shape[1],
                height=frame.shape[0],
            )
        output: list[HandResult] = []
        for detection in detections:
            result = self._run_landmark(frame, detection)
            if result is not None:
                output.append(result)
        return output[: self._max_hands]

    def _track(self, frame: np.ndarray) -> list[HandResult]:
        output: list[HandResult] = []
        for previous in self._tracks:
            result = self._run_landmark(frame, previous)
            if result is not None:
                output.append(result)
        return output[: self._max_hands]

    @staticmethod
    def _result_iou(first: HandResult, second: HandResult) -> float:
        if first.box is None or second.box is None:
            return 0.0
        return _iou(np.asarray(first.box), np.asarray(second.box))

    @staticmethod
    def _result_wrist_distance(first: HandResult, second: HandResult) -> float:
        return float(np.linalg.norm(first.landmarks[0, :2] - second.landmarks[0, :2]))

    @classmethod
    def _same_tracked_hand(cls, tracked: HandResult, detected: HandResult) -> bool:
        """Match a fresh detector result to a current ROI by geometry.

        Handedness is deliberately not used as the identity key: mirrored
        camera streams and transient classifier flips are both possible.
        The detector box is preferred when it overlaps; the wrist fallback
        covers a detector box that moved outside the old stale box.
        """

        if cls._result_iou(tracked, detected) >= 0.05:
            return True
        return cls._result_wrist_distance(tracked, detected) <= 0.22

    @classmethod
    def _merge_tracking_and_detection(
        cls,
        tracked: list[HandResult],
        detected: list[HandResult],
        limit: int,
    ) -> list[HandResult]:
        """Keep valid tracked hands when a periodic palm search misses them."""

        merged = list(tracked)
        matched: set[int] = set()
        for fresh in detected:
            match_index = next(
                (
                    index
                    for index, current in enumerate(merged)
                    if index not in matched and cls._same_tracked_hand(current, fresh)
                ),
                None,
            )
            if match_index is None:
                if len(merged) < limit:
                    merged.append(fresh)
                continue
            matched.add(match_index)
            # Tracking supplied the current landmark inference.  Refresh its
            # palm metadata with the current detector box so the next search
            # still has a useful spatial reference.
            current = merged[match_index]
            if fresh.box is not None:
                current.box = fresh.box.copy()
            current.score = max(current.score, fresh.score)
        return merged[:limit]

    def process(self, frame: np.ndarray, *, mode: str | None = None, timestamp_ms: int | None = None) -> list[HandResult]:
        image = validate_frame(frame)
        with self._lock:
            if self._closed or self._fatal_error:
                return []
            shape = image.shape[:2]
            running_mode = str(mode or self._running_mode).strip().lower()
            backwards = (
                timestamp_ms is not None
                and self._last_timestamp_ms is not None
                and int(timestamp_ms) <= self._last_timestamp_ms
            )
            if timestamp_ms is not None:
                self._last_timestamp_ms = int(timestamp_ms)
            if running_mode == "image" or backwards or shape != self._last_shape:
                self._tracks.clear()
                self._calls_since_detection = self._detection_interval
            self._last_shape = shape
            try:
                use_detection = not self._tracks or self._calls_since_detection >= self._detection_interval
                if use_detection:
                    if self._tracks:
                        # A periodic palm search is additive.  Running the
                        # existing ROIs first prevents one missed detector
                        # result from deleting a hand that is still visible.
                        tracked = self._track(image)
                        detected = self._detect(image)
                        results = self._merge_tracking_and_detection(
                            tracked, detected, self._max_hands
                        )
                    else:
                        results = self._detect(image)
                    # The detection call itself counts toward the bounded
                    # search interval.  With interval=5 this gives detection
                    # calls 1, 6, 11... rather than 1, 7, 13....
                    self._calls_since_detection = 1
                else:
                    results = self._track(image)
                    self._calls_since_detection += 1
                    # A failed ROI is immediately removed.  Reacquire in the
                    # same call to avoid publishing stale points.
                    if len(results) != len(self._tracks):
                        detected = self._detect(image)
                        results = self._merge_tracking_and_detection(
                            results, detected, self._max_hands
                        )
                        self._calls_since_detection = 1
                self._tracks = list(results)
                return list(results)
            except HandBackendError:
                self._tracks.clear()
                return []
            except (ValueError, cv2.error) as exc:
                self._tracks.clear()
                logger.debug("Recoverable hand frame error: %s", exc)
                return []

    def close(self) -> None:
        with self._lock:
            self._tracks.clear()
            self._close_locked()
