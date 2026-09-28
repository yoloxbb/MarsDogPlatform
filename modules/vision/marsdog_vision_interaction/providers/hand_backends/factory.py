"""Select the hand runtime from explicit model suffixes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .base import HandBackend, HandBackendError
from .mediapipe import MediaPipeHandBackend
from .rknn import RKNNHandBackend


def create_hand_backend(
    landmark_model: str | Path,
    *,
    detector_model: str | Path | None = None,
    running_mode: str = "video",
    rknn_config: Mapping[str, Any] | None = None,
    runtime_library: str = "",
    score_threshold: float = 0.50,
    nms_threshold: float = 0.30,
    presence_threshold: float = 0.50,
    detection_interval: int = 5,
    preprocessing: str | None = None,
    rga_preprocessor: Any = None,
    max_hands: int = 2,
) -> HandBackend:
    """Create a backend; model suffix is the only backend selector."""

    landmark_path = Path(landmark_model)
    suffix = landmark_path.suffix.lower()
    if suffix == ".task":
        return MediaPipeHandBackend(
            landmark_path,
            running_mode=running_mode,
            score_threshold=max(0.0, min(1.0, float(score_threshold))),
            presence_threshold=max(0.0, min(1.0, float(presence_threshold))),
            max_hands=max_hands,
        )
    if suffix == ".rknn":
        if detector_model is None or Path(detector_model).suffix.lower() != ".rknn":
            raise HandBackendError(
                "RKNN hand backend requires hand_detect_model with .rknn suffix"
            )
        options = {} if rknn_config is None else dict(rknn_config)
        mode = preprocessing if preprocessing is not None else options.get("preprocessing", "cpu")
        return RKNNHandBackend(
            detector_model,
            landmark_path,
            config=options,
            runtime_library=runtime_library,
            running_mode=running_mode,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            presence_threshold=presence_threshold,
            detection_interval=detection_interval,
            preprocessing=str(mode),
            rga_preprocessor=rga_preprocessor,
            max_hands=max_hands,
        )
    raise HandBackendError(
        f"Unsupported hand landmark model suffix {landmark_path.suffix!r}; expected .task or .rknn"
    )
