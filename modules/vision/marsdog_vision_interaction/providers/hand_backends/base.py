"""Common hand backend data and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


class HandBackendError(RuntimeError):
    """A hand model cannot satisfy its runtime or numerical contract."""


def validate_frame(frame: Any) -> np.ndarray:
    image = np.asarray(frame)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("hand input must be a non-empty HxWx3 image")
    if image.shape[0] <= 0 or image.shape[1] <= 0:
        raise ValueError("hand input must be a non-empty HxWx3 image")
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    return image


@dataclass(slots=True)
class HandResult:
    """One hand in source-frame coordinates.

    ``landmarks`` is always ``(21, 3)`` and stores normalized x/y plus z in
    the same normalized image-width scale used by MediaPipe.  The array is
    intentionally retained at float32 until the observation serializer rounds
    the public payload; the gesture engine consumes ``_behavior_landmarks``
    built from this array.
    """

    landmarks: np.ndarray
    handedness: str
    handedness_score: float
    score: float = 0.0
    presence: float = 0.0
    box: np.ndarray | None = None
    rotation: float = 0.0
    _roi_matrix: np.ndarray | None = None
    _roi_size_px: float = 0.0

    def __post_init__(self) -> None:
        points = np.asarray(self.landmarks, dtype=np.float32)
        if points.shape != (21, 3):
            raise HandBackendError(
                f"hand landmark output has shape {points.shape}; expected (21, 3)"
            )
        if not np.isfinite(points).all():
            raise HandBackendError("hand landmark output contains non-finite values")
        self.landmarks = points
        self.handedness = str(self.handedness or "").strip().capitalize()
        if self.handedness not in {"Left", "Right"}:
            self.handedness = ""
        for name in ("handedness_score", "score", "presence"):
            value = float(getattr(self, name))
            if not np.isfinite(value):
                raise HandBackendError(f"hand {name} is non-finite")
            setattr(self, name, value)
        if self.box is not None:
            box = np.asarray(self.box, dtype=np.float32).reshape(-1)
            if box.size != 4 or not np.isfinite(box).all():
                raise HandBackendError("hand box must contain four finite values")
            self.box = box

    def as_observation(self) -> dict[str, Any]:
        """Build the legacy observation shape without losing internal data."""

        landmarks = [
            {"id": index, "x": float(point[0]), "y": float(point[1]), "z": float(point[2])}
            for index, point in enumerate(self.landmarks)
        ]
        return {
            "handedness": self.handedness,
            "landmarks": landmarks,
        }


class HandBackend:
    """Small runtime protocol used by the observation provider."""

    backend_name = "unknown"

    @property
    def fatal_error(self) -> str | None:
        return None

    @property
    def preprocessing_mode(self) -> str:
        return "cpu"

    def process(self, frame: np.ndarray, *, mode: str | None = None, timestamp_ms: int | None = None) -> list[HandResult]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
