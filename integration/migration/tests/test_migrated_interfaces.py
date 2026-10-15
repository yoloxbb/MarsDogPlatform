"""Migration gate: unchanged ROS identity, launch/default configs and packaged media."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import xml.etree.ElementTree as ET

import pytest
import yaml

from integration.naming.config_compatibility import (
    FIXTURE, ASSET_FIXTURE, assert_reviewed_config, assert_reviewed_asset,
    restore_reviewed_interface_names,
)

REPO = Path(__file__).resolve().parents[3]
BASELINE = json.loads((Path(__file__).resolve().parents[1] / "baseline/sources.json").read_text())
REVIEWED_CONFIGS = json.loads(FIXTURE.read_text())["configs"]
REVIEWED_ASSETS = json.loads(ASSET_FIXTURE.read_text())["assets"]


@pytest.mark.parametrize("module", ["emotion", "behavior", "action", "voice", "vision"])
def test_migration_preserves_wire_and_default_assets(module):
    source = REPO / "modules" / module
    protected = {
        name: record for name, record in BASELINE["sources"][module]["files"].items()
        if name == "package.xml"
        or name.startswith(("config/", "configs/", "launch/", "marsdog_ros2/launch/", "scripts/"))
        or Path(name).suffix in {".msg", ".srv", ".action"}
        or (module == "vision" and name.startswith("marsdog_vision_interaction/web/"))
        or (module == "voice" and name.startswith(("lib/", "marsdog_voice_interaction/api/static/")))
    }
    assert protected, "No protected protocol/config files were selected"
    for name, record in protected.items():
        path = source / name
        if module == "action" and name == "action/ExecuteBehavior.action":
            # Authorized retirement: only the unchanged public IDL is generated.
            assert not path.exists()
            public = REPO / "interfaces/ros2/marsdog_interfaces/action/ExecuteBehavior.action"
            retired = json.loads((REPO / "integration/naming/interface_migration.json").read_text())["retired_assets"][path.relative_to(REPO).as_posix()]
            assert retired["original_sha256"] == record["sha256"]
            fields = [" ".join(line.split("#", 1)[0].split()) for line in public.read_text().splitlines()
                      if line.split("#", 1)[0].strip()]
            assert fields == retired["fields"]
            continue
        assert path.is_file(), name
        actual_bytes = restore_reviewed_interface_names(path.read_bytes(), path.relative_to(REPO).as_posix())
        if name == "package.xml":
            # Logging refactor permits exactly this public infrastructure dependency.
            # Removing the one literal addition must recover every frozen byte/XML element.
            addition = b"  <exec_depend>marsdog_observability</exec_depend>\n"
            assert actual_bytes.count(addition) == 1
            actual_bytes = actual_bytes.replace(addition, b"", 1)
        if module == "action" and name == "package.xml":
            # Explicit public dependencies introduced after migration. The
            # frozen original is never replaced; every other element is exact.
            frozen_xml = (REPO / "integration/migration/fixtures/action-package-original.xml").read_bytes()
            assert hashlib.sha256(frozen_xml).hexdigest() == record["sha256"]
            original = ET.fromstring(frozen_xml)
            actual = ET.fromstring(actual_bytes)
            assert actual.tag == original.tag and actual.attrib == original.attrib
            for dependency in ('marsdog_interfaces', 'robot_local_motion', 'person_3d_localization'):
                added = [n for n in actual if n.tag == "exec_depend" and n.text == dependency]
                assert len(added) == 1, dependency
                actual.remove(added[0])
            # Public interface migration removes only these obsolete dependencies.
            for tag, text in (("depend", "marsdog_voice_interaction"),
                              ("buildtool_depend", "rosidl_default_generators"),
                              ("member_of_group", "rosidl_interface_packages")):
                removed = [n for n in original if n.tag == tag and n.text == text]
                assert len(removed) == 1, (tag, text)
                original.remove(removed[0])
            normalize = lambda root: [(n.tag, n.attrib, (n.text or "").strip(), [(c.tag, (c.text or "").strip()) for c in n]) for n in root]
            assert normalize(actual) == normalize(original)
        elif path.relative_to(REPO).as_posix() in REVIEWED_CONFIGS:
            # Explicit reviews preserve original migration evidence and check
            # every value outside the reviewed changes; all other assets stay byte-exact.
            review = REVIEWED_CONFIGS[path.relative_to(REPO).as_posix()]
            assert_reviewed_config(yaml.safe_load(actual_bytes), review, record["sha256"])
        elif path.relative_to(REPO).as_posix() in REVIEWED_ASSETS:
            # Preserve reviewed revisions that predate this refactor. This is
            # not a claim that their algorithms/config equal the migration era.
            review = REVIEWED_ASSETS[path.relative_to(REPO).as_posix()]
            assert_reviewed_asset(actual_bytes, review, record['sha256'])
        else:
            assert hashlib.sha256(actual_bytes).hexdigest() == record["sha256"], name
        actual_mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        assert actual_mode == record["working_mode"], name


def test_robotics_migration_preserves_idl_and_default_configs():
    mapping = json.loads((REPO / "docs/migration/history/robot-import.json").read_text())["path_mapping"]
    checked = 0
    for name, record in BASELINE["sources"]["robot"]["files"].items():
        prefix = next((prefix for prefix in mapping if name.startswith(prefix)), None)
        if prefix is None:
            continue
        relative = name[len(prefix):]
        if not (relative.startswith(("config/", "launch/")) or Path(relative).suffix in {".msg", ".srv", ".action"}):
            continue
        actual = REPO / mapping[prefix] / relative
        actual_bytes = restore_reviewed_interface_names(actual.read_bytes(), actual.relative_to(REPO).as_posix())
        review = REVIEWED_CONFIGS.get(actual.relative_to(REPO).as_posix())
        if review:
            assert_reviewed_config(yaml.safe_load(actual_bytes), review, record['sha256'])
        elif actual.relative_to(REPO).as_posix() in REVIEWED_ASSETS:
            review = REVIEWED_ASSETS[actual.relative_to(REPO).as_posix()]
            assert_reviewed_asset(actual_bytes, review, record['sha256'])
        else:
            assert hashlib.sha256(actual_bytes).hexdigest() == record["sha256"], name
        checked += 1
    assert checked > 0
