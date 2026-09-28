"""Configuration path resolution for source and installed ROS2 layouts."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_config_dir(explicit: str | None = None) -> Path:
    """Return the behavior configuration directory.

    Resolution order:
    1. Explicit caller-provided directory.
    2. ``MARSDOG_BEHAVIOR_CONFIG_DIR`` override.
    3. Repository/source layout.
    4. ROS2 package share directory.
    5. Ordinary Python installation prefix share directory.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_dir = os.environ.get("MARSDOG_BEHAVIOR_CONFIG_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    source_dir = Path(__file__).resolve().parent.parent / "config"
    if source_dir.is_dir():
        return source_dir

    try:
        from ament_index_python.packages import get_package_share_directory

        share_dir = Path(get_package_share_directory("marsdog_behavior")) / "config"
        if share_dir.is_dir():
            return share_dir
    except (ImportError, LookupError):
        pass

    installed_dir = Path(sys.prefix) / "share" / "marsdog_behavior" / "config"
    if installed_dir.is_dir():
        return installed_dir

    raise FileNotFoundError(
        "marsdog_behavior config directory not found; set "
        "MARSDOG_BEHAVIOR_CONFIG_DIR or install the package config files"
    )


def get_config_file(filename: str, config_dir: str | None = None) -> Path:
    """Resolve one required configuration file."""
    path = get_config_dir(config_dir) / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required behavior config not found: {path}")
    return path
