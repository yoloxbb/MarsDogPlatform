"""Migration gate: unchanged ROS identity, launch/default configs and packaged media."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BASELINE = json.loads((Path(__file__).resolve().parents[1] / "baseline/sources.json").read_text())


@pytest.mark.parametrize("module", ["emotion", "behavior", "action", "voice"])
def test_migration_preserves_wire_and_default_assets(module):
    source = REPO / "modules" / module
    protected = {
        name: record for name, record in BASELINE["sources"][module]["files"].items()
        if name == "package.xml"
        or name.startswith(("config/", "configs/", "launch/", "marsdog_ros2/launch/", "scripts/"))
        or Path(name).suffix in {".msg", ".srv", ".action"}
        or (module == "voice" and name.startswith(("lib/", "marsdog_voice_interaction/api/static/")))
    }
    assert protected, "No protected protocol/config files were selected"
    for name, record in protected.items():
        path = source / name
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], name
        actual_mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        assert actual_mode == record["working_mode"], name
