"""YAML configuration loader for MarsDog perception.

Loads perception.yaml and merges with defaults, providing typed access
to provider configs, topic settings, and debug options.
"""

from __future__ import annotations

import os
from pathlib import Path
from string import Template
from typing import Any

import yaml

from .model_paths import model_root, vision_model_directory


DEBUG_OSD_DEFAULTS: dict[str, bool] = {
    "enabled": True,
    "show_all_detections": False,
}


def _config_bool(value: Any, default: bool) -> bool:
    """Coerce YAML-compatible booleans without treating ``"false"`` as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def normalize_debug_osd(value: Any) -> dict[str, bool]:
    """Return the shared debug OSD settings with compatibility defaults."""
    raw = value if isinstance(value, dict) else {}
    return {
        "enabled": _config_bool(
            raw.get("enabled"), DEBUG_OSD_DEFAULTS["enabled"]
        ),
        "show_all_detections": _config_bool(
            raw.get("show_all_detections"),
            DEBUG_OSD_DEFAULTS["show_all_detections"],
        ),
    }


def _find_project_root(config_path: Path) -> Path:
    """Find a source checkout without assuming a developer-specific path."""
    candidates = (config_path.parent, *config_path.parents, Path.cwd().resolve())
    for candidate in candidates:
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "marsdog_vision_interaction").is_dir()
        ):
            return candidate
    return Path.cwd().resolve()


def _path_variables(config_path: Path, data: dict[str, Any]) -> dict[str, str]:
    project_override = os.environ.get("MARSDOG_VISION_PROJECT_DIR")
    project_dir = Path(
        project_override or _find_project_root(config_path)
    ).expanduser().resolve()

    data_dir = Path(
        os.environ.get("MARSDOG_VISION_DATA_DIR", project_dir / "data")
    ).expanduser().resolve()
    variables = {
        "MARSDOG_VISION_PROJECT_DIR": str(project_dir),
        "MARSDOG_VISION_DATA_DIR": str(data_dir),
    }
    # Only resolve model variables used by this config. Mock configs and configs
    # with explicit model paths also work in a standalone wheel without a root.
    referenced = {
        match.group("named") or match.group("braced")
        for match in Template.pattern.finditer(str(data))
    }
    if "MARSDOG_MODEL_DIR" in referenced:
        variables["MARSDOG_MODEL_DIR"] = str(model_root(config_path))
    if "MARSDOG_VISION_MODEL_DIR" in referenced:
        variables["MARSDOG_VISION_MODEL_DIR"] = str(vision_model_directory(config_path))
    return variables


def _expand_variables(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        return Template(value).safe_substitute(variables)
    if isinstance(value, list):
        return [_expand_variables(item, variables) for item in value]
    if isinstance(value, dict):
        return {
            key: _expand_variables(item, variables)
            for key, item in value.items()
        }
    return value


def load_config(path: str | Path) -> dict[str, Any]:
    """Load and validate a perception YAML config file.

    Args:
        path: Path to a YAML config file (e.g. config/perception.yaml).

    Returns:
        Parsed config dict. Empty dict if file not found or invalid.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    config_path = Path(path).expanduser().resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Config {config_path} must be a YAML mapping, "
            f"got {type(data).__name__}"
        )

    expanded = _expand_variables(data, _path_variables(config_path, data))
    # Keep the compatibility defaults at the shared config boundary so the
    # interaction node and debug viewer cannot interpret an omitted section
    # differently.
    expanded["debug_osd"] = normalize_debug_osd(expanded.get("debug_osd"))
    return expanded


def load_config_safe(
    path: str | Path,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load config with fallback to defaults on any error.

    Args:
        path: Path to a YAML config file.
        defaults: Fallback dict if load fails.

    Returns:
        Parsed config dict or defaults.
    """
    try:
        return load_config(path)
    except Exception:
        return defaults if defaults is not None else {}
