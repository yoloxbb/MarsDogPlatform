"""Common contracts for human pose backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


class PoseBackendError(RuntimeError):
    """A pose model cannot satisfy its runtime or numerical contract."""


def validate_frame(frame: Any) -> np.ndarray:
    image = np.asarray(frame)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("pose input must be a non-empty HxWx3 image")
    if image.shape[0] <= 0 or image.shape[1] <= 0:
        raise ValueError("pose input must be a non-empty HxWx3 image")
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    return image


@dataclass(slots=True)
class PoseResult:
    """One detected person in source-frame normalized coordinates."""

    box: np.ndarray
    score: float
    keypoints: np.ndarray


class PoseBackend(Protocol):
    backend_name: str
    keypoint_format: str

    @property
    def fatal_error(self) -> str | None: ...

    def process(self, frame: np.ndarray) -> list[PoseResult]: ...

    def close(self) -> None: ...
