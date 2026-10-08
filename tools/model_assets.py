"""Model storage convention for platform preparation and trial commands."""
import os
from pathlib import Path
import warnings

from runtime_environment import ROOT

CPU_BUNDLE = Path("cpu-20260929")
QWEN_INTENT = Path("llm/qwen2.5-0.5b-instruct")


def model_directory():
    raw = os.environ.get("MARSDOG_MODEL_DIR", "").strip()
    if not raw:
        return ROOT / "models"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("MARSDOG_MODEL_DIR must be an absolute directory: " + raw)
    return path.resolve()


def default_manifest(kind):
    relative, filename, legacy_relative = {
        "voice": (CPU_BUNDLE, "voice-replay.json", CPU_BUNDLE),
        "intent": (QWEN_INTENT, "intent-replay.json", Path("qwen2.5-0.5b-instruct")),
    }[kind]
    target = model_directory() / relative / filename
    # Preserve already prepared local trials. An explicit root never falls back
    # to a different deployment; an existing canonical bundle must stand alone.
    legacy = ROOT / "out/models" / legacy_relative / filename
    if (not os.environ.get("MARSDOG_MODEL_DIR", "").strip()
            and not target.parent.exists() and legacy.is_file()):
        warnings.warn(
            f"Using existing CPU assets at {legacy}; new preparations use {target.parent}. "
            "Use --voice-manifest / --intent-manifest to select assets explicitly.",
            UserWarning, stacklevel=2,
        )
        return legacy
    return target
