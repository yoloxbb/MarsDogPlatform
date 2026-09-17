"""OpenCV-compatible face model adapters.

The RKNN models shipped with this project are converted FP16 graphs.  They
have no portable metadata describing their preprocessing or output order, so
the adapter deliberately binds each accepted profile to a SHA-256 fingerprint
before importing RKNN Lite.  This prevents an INT8 or newly exported model
from being used with the wrong input contract just because it was renamed.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Any, Mapping

import numpy as np

logger = logging.getLogger(__name__)

_YUNET_MODEL_SIZE = (640, 640)
_SFACE_MODEL_SIZE = (112, 112)
_YUNET_STRIDES = (8, 16, 32)
_YUNET_OUTPUT_NAMES = (
    "cls_8",
    "cls_16",
    "cls_32",
    "obj_8",
    "obj_16",
    "obj_32",
    "bbox_8",
    "bbox_16",
    "bbox_32",
    "kps_8",
    "kps_16",
    "kps_32",
)

# These are the artifacts evaluated on RK3588 with rknn-toolkit-lite2 2.3.2.
# Keep the values in one place so a future conversion has to be explicitly
# reviewed and added along with its parity evidence.
YUNET_FP16_SHA256 = (
    "bbdd709d9f3385c45e7bb4ac667609866d32f3e80767c1bb0a6c2b4b00e52315"
)
SFACE_FP16_SHA256 = (
    "42d25f58bf8af8673d040083ac4b8ae9697c2588e4d7b1c6ce3f25c5fdab87db"
)

YUNET_PROFILE = "yunet_2023mar_fp16"
SFACE_PROFILE = "sface_2021dec_fp16"

RKNN_PROFILES: Mapping[str, Mapping[str, Any]] = {
    YUNET_PROFILE: {
        "role": "detector",
        "sha256": YUNET_FP16_SHA256,
        "input_size": _YUNET_MODEL_SIZE,
        "input_layout": "nhwc",
        "input_dtype": "float16",
        "input_pass_through": True,
    },
    SFACE_PROFILE: {
        "role": "recognizer",
        "sha256": SFACE_FP16_SHA256,
        "input_size": _SFACE_MODEL_SIZE,
        "input_layout": "nhwc",
        "input_dtype": "float16",
        "input_pass_through": True,
    },
}


class FaceBackendError(RuntimeError):
    """Raised when a face model cannot satisfy its backend contract."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_rknn_profile(
    path: Path,
    role: str,
    config: Mapping[str, Any] | None,
) -> tuple[str, Mapping[str, Any], Any]:
    """Validate an RKNN artifact and return profile plus requested core mask."""

    if not path.is_file():
        raise FaceBackendError(f"RKNN {role} model does not exist: {path}")
    options: Mapping[str, Any] = {} if config is None else config
    if not isinstance(options, Mapping):
        raise FaceBackendError("rknn_config must be a mapping")

    default_profile = YUNET_PROFILE if role == "detector" else SFACE_PROFILE
    profile_name = str(options.get("profile", default_profile))
    profile = RKNN_PROFILES.get(profile_name)
    if profile is None or profile.get("role") != role:
        valid = YUNET_PROFILE if role == "detector" else SFACE_PROFILE
        raise FaceBackendError(
            f"Unsupported RKNN {role} profile {profile_name!r}; expected {valid!r}"
        )

    actual = _sha256_file(path)
    expected = str(profile["sha256"])
    if actual != expected:
        raise FaceBackendError(
            f"Unverified RKNN {role} artifact {path.name}: SHA-256 {actual}; "
            f"profile {profile_name!r} requires {expected}"
        )
    return profile_name, profile, options.get("core_mask", "auto")


def _core_mask_value(rknn_class: Any, value: Any) -> Any:
    """Translate the YAML-friendly core selector to RKNN Lite's constant."""

    if value is None:
        value = "auto"
    if isinstance(value, (bool, np.bool_)):
        raise FaceBackendError("Invalid RKNN core_mask boolean")
    if isinstance(value, (int, np.integer)):
        numeric = int(value)
        # YAML parses an unquoted `core_mask: 0` as an integer.  The public
        # selector `0` means NPU core 0, while the combined selectors retain
        # their explicit bitmask spellings.
        if numeric in (0, 1, 2):
            value = str(numeric)
        else:
            raise FaceBackendError(
                f"Invalid RKNN core_mask {value!r}; expected auto, 0, 1, 2, 0_1 or 0_1_2"
            )
    text = str(value).strip().lower()
    names = {
        "auto": "NPU_CORE_AUTO",
        "0": "NPU_CORE_0",
        "1": "NPU_CORE_1",
        "2": "NPU_CORE_2",
        "0_1": "NPU_CORE_0_1",
        "0_1_2": "NPU_CORE_0_1_2",
    }
    if text not in names:
        raise FaceBackendError(
            f"Invalid RKNN core_mask {value!r}; expected auto, 0, 1, 2, 0_1 or 0_1_2"
        )
    constant = names[text]
    try:
        return getattr(rknn_class, constant)
    except AttributeError as exc:
        raise FaceBackendError(
            f"RKNN Lite does not expose required core selector {constant}"
        ) from exc


def _load_rknn(
    path: Path,
    role: str,
    config: Mapping[str, Any] | None,
    runtime_library: str,
) -> tuple[Any, str, Mapping[str, Any]]:
    """Validate and initialize RKNN Lite, releasing partial instances."""

    profile_name, profile, requested_core = _validate_rknn_profile(path, role, config)
    # This import is intentionally lazy: ONNX-only deployments must not need
    # RKNN Lite or its shared library just to import the vision package.
    from marsdog_vision_interaction.utils.rknn_runtime import (
        configure_rknn_runtime,
    )

    configure_rknn_runtime(str(runtime_library or ""))
    try:
        from rknnlite.api import RKNNLite
    except ImportError as exc:  # pragma: no cover - exercised on x86 hosts
        raise FaceBackendError(
            "RKNN model requested but rknn-toolkit-lite2 is unavailable"
        ) from exc

    core_mask = _core_mask_value(RKNNLite, requested_core)
    runtime: Any = None
    try:
        runtime = RKNNLite()
        result = runtime.load_rknn(str(path))
        if result != 0:
            raise FaceBackendError(
                f"RKNN {role} load failed for {path}: return code {result}"
            )
        result = runtime.init_runtime(core_mask=core_mask)
        if result != 0:
            raise FaceBackendError(
                f"RKNN {role} runtime initialization failed for {path}: "
                f"return code {result}"
            )
    except Exception:
        if runtime is not None:
            _release_runtime(runtime)
        raise
    logger.info("RKNN %s loaded: model=%s profile=%s core_mask=%s", role, path, profile_name, requested_core)
    return runtime, profile_name, profile


def _release_runtime(runtime: Any) -> None:
    release = getattr(runtime, "release", None)
    if callable(release):
        try:
            release()
        except Exception:
            logger.exception("RKNN runtime release failed")


def _as_input_frame(frame: np.ndarray) -> np.ndarray:
    image = np.asarray(frame)
    if image.ndim != 3 or image.shape[2] != 3 or image.shape[0] <= 0 or image.shape[1] <= 0:
        raise ValueError("face input must be a non-empty HxWx3 image")
    return image


def _validate_detector_options(
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
) -> tuple[float, float, int]:
    score = float(score_threshold)
    nms = float(nms_threshold)
    limit = int(top_k)
    if not np.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("face score_threshold must be finite and within [0, 1]")
    if not np.isfinite(nms) or not 0.0 <= nms <= 1.0:
        raise ValueError("face nms_threshold must be finite and within [0, 1]")
    if limit < 0:
        raise ValueError("face top_k must be non-negative")
    return score, nms, limit


def _letterbox_bgr(frame: np.ndarray, size: tuple[int, int]) -> tuple[np.ndarray, float, float]:
    """Fit BGR image into a zero-padded target and return x/y scale."""

    image = _as_input_frame(frame)
    target_w, target_h = size
    src_h, src_w = image.shape[:2]
    scale = min(target_w / src_w, target_h / src_h)
    resized_w = max(1, min(target_w, int(round(src_w * scale))))
    resized_h = max(1, min(target_h, int(round(src_h * scale))))
    if resized_w == src_w and resized_h == src_h:
        resized = image
    else:
        import cv2

        resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    padded = np.zeros((target_h, target_w, 3), dtype=resized.dtype)
    padded[:resized_h, :resized_w] = resized
    return padded, resized_w / src_w, resized_h / src_h


def _normalise_output_list(outputs: Any) -> list[np.ndarray]:
    if isinstance(outputs, Mapping):
        missing = [name for name in _YUNET_OUTPUT_NAMES if name not in outputs]
        if missing:
            raise FaceBackendError(f"YuNet inference missing outputs: {', '.join(missing)}")
        return [np.asarray(outputs[name]) for name in _YUNET_OUTPUT_NAMES]
    if isinstance(outputs, np.ndarray):
        values = [outputs]
    else:
        try:
            values = list(outputs)
        except TypeError as exc:
            raise FaceBackendError("YuNet inference returned a non-sequence") from exc
    if len(values) == 1 and isinstance(values[0], (list, tuple)):
        values = list(values[0])
    if len(values) != 12:
        raise FaceBackendError(f"YuNet inference returned {len(values)} outputs; expected 12")
    return [np.asarray(value) for value in values]


def _reshape_prediction(value: np.ndarray, width: int, label: str) -> np.ndarray:
    array = np.asarray(value)
    if array.size == 0 or array.size % width:
        raise FaceBackendError(f"YuNet output {label} has invalid shape {array.shape}")
    if width == 1:
        return array.astype(np.float32, copy=False).reshape(-1)
    return array.astype(np.float32, copy=False).reshape(-1, width)


def _nms_yunet(
    rows: np.ndarray,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
) -> np.ndarray:
    if rows.size == 0:
        return np.empty((0, 15), dtype=np.float32)
    values = np.asarray(rows, dtype=np.float32)
    import cv2

    boxes = [
        [int(row[0]), int(row[1]), int(row[2]), int(row[3])]
        for row in values
    ]
    scores = values[:, 14].astype(float).tolist()
    kept = cv2.dnn.NMSBoxes(
        boxes,
        scores,
        float(score_threshold),
        float(nms_threshold),
        eta=1.0,
        top_k=max(0, int(top_k)),
    )
    if kept is None or len(kept) == 0:
        return np.empty((0, 15), dtype=np.float32)
    indices = np.asarray(kept, dtype=np.int64).reshape(-1)
    return values[indices]


def decode_yunet_outputs(
    outputs: Any,
    score_threshold: float = 0.3,
    nms_threshold: float = 0.45,
    top_k: int = 5000,
    *,
    valid_width: int = 640,
    valid_height: int = 640,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    model_width: int = 640,
    model_height: int = 640,
) -> np.ndarray:
    """Decode RKNN YuNet tensors into OpenCV's ``N x 15`` face rows.

    ``valid_width`` and ``valid_height`` describe the unpadded part of the
    model image.  Coordinates are clipped to that region and then mapped back
    by ``scale_x``/``scale_y`` so callers receive source-image coordinates.
    """

    if model_width <= 0 or model_height <= 0 or valid_width <= 0 or valid_height <= 0:
        raise ValueError("YuNet model and valid dimensions must be positive")
    if scale_x <= 0 or scale_y <= 0:
        raise ValueError("YuNet coordinate scales must be positive")
    tensors = _normalise_output_list(outputs)
    decoded: list[np.ndarray] = []
    for level, stride in enumerate(_YUNET_STRIDES):
        cls = _reshape_prediction(tensors[level], 1, f"cls_{stride}")
        obj = _reshape_prediction(tensors[level + 3], 1, f"obj_{stride}")
        bbox = _reshape_prediction(tensors[level + 6], 4, f"bbox_{stride}")
        kps = _reshape_prediction(tensors[level + 9], 10, f"kps_{stride}")
        count = model_width // stride * (model_height // stride)
        if not (len(cls) == len(obj) == len(bbox) == len(kps) == count):
            raise FaceBackendError(
                f"YuNet stride {stride} output sizes disagree: "
                f"cls={len(cls)}, obj={len(obj)}, bbox={len(bbox)}, kps={len(kps)}, expected={count}"
            )
        columns = model_width // stride
        indices = np.arange(count, dtype=np.int32)
        grid_rows = indices // columns
        grid_cols = indices % columns
        score = np.sqrt(np.clip(cls, 0.0, 1.0) * np.clip(obj, 0.0, 1.0))
        finite = (
            np.isfinite(score)
            & np.isfinite(bbox).all(axis=1)
            & np.isfinite(kps).all(axis=1)
            & (score >= float(score_threshold))
        )
        if not finite.any():
            continue
        grid_rows = grid_rows[finite].astype(np.float32)
        grid_cols = grid_cols[finite].astype(np.float32)
        box = bbox[finite]
        points = kps[finite]
        scores = score[finite].astype(np.float32)
        cx = (grid_cols + box[:, 0]) * stride
        cy = (grid_rows + box[:, 1]) * stride
        width = np.exp(np.clip(box[:, 2], -50.0, 50.0)) * stride
        height = np.exp(np.clip(box[:, 3], -50.0, 50.0)) * stride
        x1 = cx - width / 2.0
        y1 = cy - height / 2.0
        x2 = x1 + width
        y2 = y1 + height
        valid = (
            np.isfinite(x1)
            & np.isfinite(y1)
            & np.isfinite(width)
            & np.isfinite(height)
            & (x2 > 0.0)
            & (y2 > 0.0)
            & (x1 < valid_width)
            & (y1 < valid_height)
            & (width > 0.0)
            & (height > 0.0)
        )
        if not valid.any():
            continue
        x1, y1, x2, y2 = x1[valid], y1[valid], x2[valid], y2[valid]
        points, scores = points[valid], scores[valid]
        valid_box = (
            np.clip(x2, 0.0, float(valid_width))
            > np.clip(x1, 0.0, float(valid_width))
        ) & (
            np.clip(y2, 0.0, float(valid_height))
            > np.clip(y1, 0.0, float(valid_height))
        )
        if not valid_box.any():
            continue
        raw = np.empty((int(valid_box.sum()), 15), dtype=np.float32)
        raw[:, 0] = x1[valid_box]
        raw[:, 1] = y1[valid_box]
        raw[:, 2] = width[valid_box]
        raw[:, 3] = height[valid_box]
        point_values = points[valid_box]
        valid_cols = grid_cols[valid_box]
        valid_rows = grid_rows[valid_box]
        raw[:, 4:14:2] = (valid_cols[:, None] + point_values[:, 0::2]) * stride
        raw[:, 5:14:2] = (valid_rows[:, None] + point_values[:, 1::2]) * stride
        raw[:, 14] = scores[valid_box]
        decoded.append(raw)
    if not decoded:
        return np.empty((0, 15), dtype=np.float32)
    selected = _nms_yunet(
        np.concatenate(decoded),
        float(score_threshold),
        float(nms_threshold),
        int(top_k),
    )
    if not len(selected):
        return selected
    # NMS follows OpenCV in model coordinates. Only the box is clipped to the
    # unpadded content area before mapping it back to the source image.
    model_x1 = np.clip(selected[:, 0], 0.0, float(valid_width))
    model_y1 = np.clip(selected[:, 1], 0.0, float(valid_height))
    model_x2 = np.clip(selected[:, 0] + selected[:, 2], 0.0, float(valid_width))
    model_y2 = np.clip(selected[:, 1] + selected[:, 3], 0.0, float(valid_height))
    selected[:, 0] = model_x1 / scale_x
    selected[:, 1] = model_y1 / scale_y
    selected[:, 2] = (model_x2 - model_x1) / scale_x
    selected[:, 3] = (model_y2 - model_y1) / scale_y
    selected[:, 4:14:2] /= scale_x
    selected[:, 5:14:2] /= scale_y
    return selected


# Short aliases are useful for focused post-processing tests and keep the
# implementation name discoverable without making the decoder a class detail.
decode_yunet = decode_yunet_outputs


class _RuntimeAdapter:
    """Common lock/lifecycle behavior for RKNN detector and recognizer."""

    def __init__(self, runtime: Any, profile_name: str) -> None:
        self._runtime = runtime
        self.profile_name = profile_name
        self._lock = threading.RLock()
        self._closed = False
        self._fatal_error: str | None = None

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def fatal_error(self) -> str | None:
        with self._lock:
            return self._fatal_error

    def _mark_fatal_locked(self, exc: BaseException) -> FaceBackendError:
        if isinstance(exc, FaceBackendError):
            error = exc
        else:
            error = FaceBackendError(
                f"{self.__class__.__name__} inference failed: {exc}"
            )
        if self._fatal_error is None:
            self._fatal_error = str(error)
        self._close_locked()
        return error

    def _inference(self, tensor: np.ndarray) -> Any:
        with self._lock:
            if self._closed or self._runtime is None:
                raise FaceBackendError(f"{self.__class__.__name__} is closed")
            try:
                return self._runtime.inference(
                    inputs=[tensor],
                    data_format=["nhwc"],
                    inputs_pass_through=[1],
                )
            except Exception as exc:
                raise self._mark_fatal_locked(exc) from exc

    def _close_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        runtime, self._runtime = self._runtime, None
        if runtime is not None:
            _release_runtime(runtime)

    def close(self) -> None:
        with self._lock:
            self._close_locked()


class OpenCVFaceDetector:
    """OpenCV FaceDetectorYN adapter with the shared detector contract."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        input_size: tuple[int, int],
        score_threshold: float,
        nms_threshold: float,
        top_k: int,
    ) -> None:
        import cv2

        self._lock = threading.RLock()
        self._closed = False
        self._detector = cv2.FaceDetectorYN.create(
            model=str(model_path),
            config="",
            input_size=tuple(input_size),
            score_threshold=float(score_threshold),
            nms_threshold=float(nms_threshold),
            top_k=int(top_k),
        )

    def setInputSize(self, input_size: tuple[int, int]) -> None:  # noqa: N802
        with self._lock:
            if self._closed:
                raise FaceBackendError("OpenCV face detector is closed")
            width, height = [int(value) for value in input_size]
            if width <= 0 or height <= 0:
                raise ValueError("face input dimensions must be positive")
            self._detector.setInputSize((width, height))

    def detect(self, frame: np.ndarray) -> tuple[int, np.ndarray | None]:
        with self._lock:
            if self._closed:
                raise FaceBackendError("OpenCV face detector is closed")
            result = self._detector.detect(_as_input_frame(frame))
            if not isinstance(result, tuple) or len(result) != 2:
                raise FaceBackendError("OpenCV YuNet returned an invalid result")
            retval, faces = result
            if faces is None:
                return int(retval), None
            array = np.asarray(faces, dtype=np.float32)
            if array.size == 0:
                return int(retval), None
            if array.ndim != 2 or array.shape[1] != 15:
                raise FaceBackendError(f"OpenCV YuNet returned shape {array.shape}, expected Nx15")
            return int(retval), array

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._detector = None


class RKNNYuNetDetector(_RuntimeAdapter):
    """RKNN YuNet FP16 detector with OpenCV-compatible output rows."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        score_threshold: float,
        nms_threshold: float,
        top_k: int,
        rknn_config: Mapping[str, Any] | None,
        runtime_library: str,
    ) -> None:
        path = Path(model_path)
        score, nms, limit = _validate_detector_options(
            score_threshold, nms_threshold, top_k
        )
        runtime, profile_name, _ = _load_rknn(path, "detector", rknn_config, runtime_library)
        super().__init__(runtime, profile_name)
        self._score_threshold, self._nms_threshold, self._top_k = score, nms, limit
        self._source_size = _YUNET_MODEL_SIZE

    def setInputSize(self, input_size: tuple[int, int]) -> None:  # noqa: N802
        width, height = [int(value) for value in input_size]
        if width <= 0 or height <= 0:
            raise ValueError("face input dimensions must be positive")
        with self._lock:
            if self._closed:
                raise FaceBackendError("RKNN YuNet detector is closed")
            self._source_size = (width, height)

    def detect(self, frame: np.ndarray) -> tuple[int, np.ndarray | None]:
        image = _as_input_frame(frame)
        with self._lock:
            if self._closed:
                raise FaceBackendError("RKNN YuNet detector is closed")
            padded, scale_x, scale_y = _letterbox_bgr(image, _YUNET_MODEL_SIZE)
            tensors = self._inference(np.asarray(padded, dtype=np.float16)[None, ...])
            try:
                faces = decode_yunet_outputs(
                    tensors,
                    self._score_threshold,
                    self._nms_threshold,
                    self._top_k,
                    valid_width=int(round(image.shape[1] * scale_x)),
                    valid_height=int(round(image.shape[0] * scale_y)),
                    scale_x=scale_x,
                    scale_y=scale_y,
                )
            except Exception as exc:
                # A malformed output is a model contract failure.  Releasing
                # avoids leaving a bad RKNN context active for later frames.
                error = self._mark_fatal_locked(
                    FaceBackendError(f"YuNet inference output contract failed: {exc}")
                )
                raise error
            return 1, (faces if len(faces) else None)


class OpenCVSFaceRecognizer:
    """OpenCV FaceRecognizerSF adapter with the common recognizer contract."""

    def __init__(self, model_path: str | Path) -> None:
        import cv2

        self._lock = threading.RLock()
        self._closed = False
        self._recognizer = cv2.FaceRecognizerSF.create(model=str(model_path), config="")

    def alignCrop(self, frame: np.ndarray, face: np.ndarray) -> np.ndarray:  # noqa: N802
        with self._lock:
            if self._closed:
                raise FaceBackendError("OpenCV SFace recognizer is closed")
            output = self._recognizer.alignCrop(_as_input_frame(frame), _face_row(face))
            return np.asarray(output)

    def feature(self, aligned: np.ndarray) -> np.ndarray:
        with self._lock:
            if self._closed:
                raise FaceBackendError("OpenCV SFace recognizer is closed")
            output = self._recognizer.feature(_as_input_frame(aligned))
            return _validate_feature(output)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._recognizer = None


def _face_row(face: np.ndarray) -> np.ndarray:
    row = np.asarray(face, dtype=np.float32)
    if row.size != 15:
        raise ValueError(f"YuNet face row must contain 15 values, got {row.shape}")
    row = row.reshape(1, 15)
    if not np.isfinite(row).all():
        raise ValueError("YuNet face row contains non-finite values")
    return row


def _similarity_transform(source: np.ndarray) -> np.ndarray:
    """Port OpenCV's FaceRecognizerSF five-point transform to NumPy."""

    destination = np.asarray(
        [
            [38.2946, 51.6963],
            [73.5318, 51.5014],
            [56.0252, 71.7366],
            [41.5493, 92.3655],
            [70.7299, 92.2041],
        ],
        dtype=np.float64,
    )
    src = np.asarray(source, dtype=np.float32).reshape(5, 2)
    if not np.isfinite(src).all():
        raise ValueError("SFace landmarks contain non-finite values")
    # OpenCV receives float landmarks and performs the means/subtractions and
    # products in float32 before accumulating covariance and variance in
    # double. Preserving that order matters at interpolation boundaries.
    destination = destination.astype(np.float32)
    src_mean = np.array(
        [
            np.sum(src[:, 0], dtype=np.float32) / np.float32(5.0),
            np.sum(src[:, 1], dtype=np.float32) / np.float32(5.0),
        ],
        dtype=np.float32,
    )
    dst_mean = np.asarray([56.0262, 71.9008], dtype=np.float32)
    src_demean = np.asarray(src - src_mean, dtype=np.float32)
    dst_demean = np.asarray(destination - dst_mean, dtype=np.float32)
    matrix = np.empty((2, 2), dtype=np.float64)
    matrix[0, 0] = np.sum(
        np.multiply(dst_demean[:, 0], src_demean[:, 0], dtype=np.float32), dtype=np.float64
    ) / 5.0
    matrix[0, 1] = np.sum(
        np.multiply(dst_demean[:, 0], src_demean[:, 1], dtype=np.float32), dtype=np.float64
    ) / 5.0
    matrix[1, 0] = np.sum(
        np.multiply(dst_demean[:, 1], src_demean[:, 0], dtype=np.float32), dtype=np.float64
    ) / 5.0
    matrix[1, 1] = np.sum(
        np.multiply(dst_demean[:, 1], src_demean[:, 1], dtype=np.float32), dtype=np.float64
    ) / 5.0
    u, singular, vt = np.linalg.svd(matrix)
    determinant_sign = -1.0 if np.linalg.det(matrix) < 0 else 1.0
    d_values = np.asarray([1.0, determinant_sign], dtype=np.float64)
    singular_max = float(max(singular[0], singular[1]))
    tolerance = singular_max * 2.0 * np.finfo(np.float32).tiny
    rank = int(np.count_nonzero(singular > tolerance))
    det_u = float(np.linalg.det(u))
    det_vt = float(np.linalg.det(vt))
    if rank == 1 and det_u * det_vt > 0.0:
        # OpenCV keeps U*Vt for the rank-one, orientation-preserving case.
        rotation = u @ vt
    elif rank == 1:
        # The source implementation temporarily flips d[1] for this branch,
        # then restores it before computing scale.
        rotation = u @ np.diag([1.0, -1.0]) @ vt
    else:
        rotation = u @ np.diag(d_values) @ vt
    variance = float(
        np.sum(np.multiply(src_demean[:, 0], src_demean[:, 0], dtype=np.float32), dtype=np.float64)
        / 5.0
        + np.sum(np.multiply(src_demean[:, 1], src_demean[:, 1], dtype=np.float32), dtype=np.float64)
        / 5.0
    )
    if variance <= np.finfo(np.float64).eps:
        raise ValueError("SFace landmarks are degenerate")
    scale = float((singular[0] * d_values[0] + singular[1] * d_values[1]) / variance)
    linear = scale * rotation
    translation = dst_mean.astype(np.float64) - linear @ src_mean.astype(np.float64)
    return np.column_stack((linear, translation))


def _validate_feature(output: Any) -> np.ndarray:
    feature = np.asarray(output, dtype=np.float32)
    if feature.size != 128:
        raise FaceBackendError(f"SFace output has {feature.size} values; expected 128")
    if not np.isfinite(feature).all():
        raise FaceBackendError("SFace output contains non-finite values")
    if float(np.linalg.norm(feature)) <= 1e-12:
        raise FaceBackendError("SFace output has zero norm")
    return feature.reshape(1, 128)


class RKNNSFaceRecognizer(_RuntimeAdapter):
    """RKNN SFace FP16 recognizer with OpenCV-compatible alignment."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        rknn_config: Mapping[str, Any] | None,
        runtime_library: str,
    ) -> None:
        path = Path(model_path)
        runtime, profile_name, _ = _load_rknn(path, "recognizer", rknn_config, runtime_library)
        super().__init__(runtime, profile_name)

    def alignCrop(self, frame: np.ndarray, face: np.ndarray) -> np.ndarray:  # noqa: N802
        image = _as_input_frame(frame)
        row = _face_row(face)
        import cv2

        with self._lock:
            if self._closed:
                raise FaceBackendError("RKNN SFace recognizer is closed")
            matrix = _similarity_transform(row[0, 4:14].reshape(5, 2))
            return cv2.warpAffine(image, matrix, _SFACE_MODEL_SIZE, flags=cv2.INTER_LINEAR)

    def feature(self, aligned: np.ndarray) -> np.ndarray:
        image = _as_input_frame(aligned)
        import cv2

        with self._lock:
            if self._closed:
                raise FaceBackendError("RKNN SFace recognizer is closed")
            if image.shape[1] != 112 or image.shape[0] != 112:
                image = cv2.resize(image, _SFACE_MODEL_SIZE, interpolation=cv2.INTER_LINEAR)
            # OpenCV FaceRecognizerSF uses a BGR->RGB swap with no additional
            # normalization. The converted graph expects FP16 NHWC passthrough.
            rgb = np.ascontiguousarray(image[:, :, ::-1], dtype=np.float16)[None, ...]
            output = self._inference(rgb)
            if isinstance(output, (list, tuple)):
                if len(output) != 1:
                    error = self._mark_fatal_locked(
                        FaceBackendError(
                            f"SFace inference returned {len(output)} outputs"
                        )
                    )
                    raise error
                output = output[0]
            try:
                return _validate_feature(output)
            except Exception as exc:
                error = self._mark_fatal_locked(
                    FaceBackendError(f"SFace inference output contract failed: {exc}")
                )
                raise error from exc


def create_face_detector(
    model_path: str | Path,
    *,
    input_size: tuple[int, int] = (320, 320),
    score_threshold: float = 0.3,
    nms_threshold: float = 0.45,
    top_k: int = 5000,
    rknn_config: Mapping[str, Any] | None = None,
    runtime_library: str = "",
) -> OpenCVFaceDetector | RKNNYuNetDetector:
    """Create the YuNet backend selected by the model filename suffix."""

    path = Path(model_path)
    suffix = path.suffix.lower()
    if suffix == ".onnx":
        return OpenCVFaceDetector(
            path,
            input_size=input_size,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=top_k,
        )
    if suffix == ".rknn":
        return RKNNYuNetDetector(
            path,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=top_k,
            rknn_config=rknn_config,
            runtime_library=runtime_library,
        )
    raise FaceBackendError(
        f"Unsupported face detector model format {path.suffix or '<none>'!r}; "
        "expected .onnx or .rknn"
    )


def create_face_recognizer(
    model_path: str | Path,
    *,
    rknn_config: Mapping[str, Any] | None = None,
    runtime_library: str = "",
) -> OpenCVSFaceRecognizer | RKNNSFaceRecognizer:
    """Create the SFace backend selected by the model filename suffix."""

    path = Path(model_path)
    suffix = path.suffix.lower()
    if suffix == ".onnx":
        return OpenCVSFaceRecognizer(path)
    if suffix == ".rknn":
        return RKNNSFaceRecognizer(
            path,
            rknn_config=rknn_config,
            runtime_library=runtime_library,
        )
    raise FaceBackendError(
        f"Unsupported face recognizer model format {path.suffix or '<none>'!r}; "
        "expected .onnx or .rknn"
    )
