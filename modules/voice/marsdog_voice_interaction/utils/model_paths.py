"""Resolve deployment model paths without depending on the working directory."""
from __future__ import annotations

import os
from pathlib import Path


def environment_directory(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute directory: {raw}")
    return path.resolve()


def model_root(config_path: str | Path) -> Path:
    """Use the explicit root, or models/ in the enclosing platform checkout.

    Configs may be installed under out/ or supplied outside the checkout. The
    package location provides the latter's anchor. A detached wheel deployment
    must explicitly configure its model root; cwd and folder existence never
    select a different model.
    """
    override = environment_directory("MARSDOG_MODEL_DIR")
    if override is not None:
        return override
    for anchor in (Path(config_path).resolve(), Path(__file__).resolve()):
        for candidate in anchor.parents:
            if (candidate / "platform/modules.json").is_file():
                return candidate / "models"
    raise ValueError(
        "Cannot locate the MarsDog platform checkout; set MARSDOG_MODEL_DIR "
        "to an absolute model directory"
    )
