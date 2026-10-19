"""Shared portable path defaults for dense reconstruction tools."""

import os
from pathlib import Path


def GetOutputDirectoryValue() -> Path:
    """Return ROBOT_OUTPUT_DIR or a user-local fallback directory."""
    configured_path = os.environ.get("ROBOT_OUTPUT_DIR")
    if configured_path:
        return Path(configured_path).expanduser()
    return Path.home() / "robot_ws" / "output"

