"""Select one RKNN runtime library for all providers in this process."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_configuration_lock = threading.Lock()

_STANDARD_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.FATAL,
    "ERROR": logging.ERROR,
    "WARN": logging.WARN,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def _logging_level_snapshot() -> tuple[dict[str, int], dict[int, str]]:
    return (
        dict(getattr(logging, "_nameToLevel", {})),
        dict(getattr(logging, "_levelToName", {})),
    )


def _restore_logging_levels(snapshot: tuple[dict[str, int], dict[int, str]]) -> None:
    """Restore names clobbered by rknn-toolkit's logging bootstrap.

    rknn-toolkit-lite2 2.3.2 replaces the stdlib level maps while importing
    ``rknnlite.api``.  ``logging.addLevelName`` is the supported way to put
    aliases back; the private maps are then updated with the original reverse
    mapping so custom application levels keep their previous canonical names.
    """

    original_names, original_reverse = snapshot
    desired_names = dict(_STANDARD_LOG_LEVELS)
    desired_names.update(original_names)
    for name, level in desired_names.items():
        logging.addLevelName(int(level), str(name))
    # addLevelName intentionally chooses the last alias as the reverse name.
    # Restore the application's prior choice where it was available.
    level_to_name = getattr(logging, "_levelToName", None)
    name_to_level = getattr(logging, "_nameToLevel", None)
    if isinstance(name_to_level, dict):
        name_to_level.update(_STANDARD_LOG_LEVELS)
        name_to_level.update(original_names)
    if isinstance(level_to_name, dict):
        level_to_name.update(original_reverse)
        for level, name in ((value, key) for key, value in _STANDARD_LOG_LEVELS.items()):
            level_to_name.setdefault(level, name)


def _import_rknn_modules() -> tuple[Any, Any, Path]:
    """Import RKNN modules while protecting process-wide logging state."""

    snapshot = _logging_level_snapshot()
    try:
        import rknnlite
        from rknnlite.api import rknn_lite
        from rknnlite.api.rknn_runtime import RKNNRuntime

        package_dir = Path(rknnlite.__file__).resolve().parent
        return rknn_lite, RKNNRuntime, package_dir
    finally:
        _restore_logging_levels(snapshot)


def configure_rknn_runtime(runtime_library: str = "") -> None:
    """Retain local-library discovery while preventing conflicting overrides.

    Imports stay lazy so ONNX-only installations do not require RKNN Lite.
    The runtime class override is process-wide, so every caller must agree on
    the resolved library. Call before constructing any RKNNLite instance.
    """
    with _configuration_lock:
        candidates: list[Path] = []
        configured = str(runtime_library).strip()
        if configured:
            candidates.append(Path(configured).expanduser())
        env_path = os.environ.get("MARSDOG_RKNN_RUNTIME_LIBRARY", "").strip()
        if env_path:
            candidates.append(Path(env_path).expanduser())
        try:
            rknn_lite, RKNNRuntime, package_dir = _import_rknn_modules()
            candidates.append(package_dir / "api" / "librknnrt.so")
        except ImportError:
            return
        candidates.append(Path("/usr/lib/librknnrt.so"))
        runtime_path = next(
            (path.resolve() for path in candidates if path.is_file()), None
        )
        if runtime_path is None:
            return

        current = getattr(rknn_lite, "RKNNRuntime", None)
        selected = getattr(current, "_marsdog_runtime_library", "")
        if selected:
            if selected != str(runtime_path):
                raise RuntimeError(
                    f"RKNN runtime already configured as {selected}; "
                    f"cannot switch to {runtime_path} in the same process"
                )
            return

        class LocalRKNNRuntime(RKNNRuntime):
            _marsdog_runtime_library = str(runtime_path)

            def _get_rknn_api_lib_path(self):  # type: ignore[no-untyped-def]
                return self._marsdog_runtime_library

        rknn_lite.RKNNRuntime = LocalRKNNRuntime
        logger.info("RKNN runtime library selected: %s", runtime_path)
