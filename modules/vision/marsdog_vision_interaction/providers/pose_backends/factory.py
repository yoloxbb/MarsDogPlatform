"""Select the human pose runtime from the model suffix."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .base import PoseBackendError
from .rknn import RKNNPoseBackend


def create_pose_backend(
    model_path: str | Path,
    *,
    rknn_config: Mapping[str, Any] | None = None,
    runtime_library: str = "",
    score_threshold: float = 0.30,
    nms_threshold: float = 0.45,
    max_num_poses: int = 4,
) -> RKNNPoseBackend:
    """Create an RKNN backend; MediaPipe ``.task`` is owned by the provider."""

    path = Path(model_path)
    if path.suffix.lower() != ".rknn":
        raise PoseBackendError(
            f"Unsupported pose model suffix {path.suffix!r}; expected .rknn or a MediaPipe .task path"
        )
    return RKNNPoseBackend(
        path,
        config=rknn_config,
        runtime_library=runtime_library,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        max_num_poses=max_num_poses,
    )
