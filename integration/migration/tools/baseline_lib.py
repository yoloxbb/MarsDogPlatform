"""Read-only source inventory shared by capture, verification and snapshot tools."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(os.environ.get("MARSDOG_MIGRATION_WORKSPACE", Path(__file__).resolve().parents[1])).resolve()
_baseline = ROOT / "baseline/sources.json"
_captured_workspace = (json.loads(_baseline.read_text())["workspace_at_capture"]
                       if _baseline.exists() else ROOT.parent)
WORKSPACE = Path(os.environ.get("MARSDOG_LEGACY_ROOT", _captured_workspace)).resolve()
SOURCES = {
    "vision": ("MarsDog", "a05dbf4b9cf3cde9707f05c4360d39e5a52968df"),
    "voice": ("MarsDogVoiceInteraction", "df85e30509b9561d782c1963e3ff362d39cbfa14"),
    "emotion": ("MarsDogEmotion", "cd1e0476df7ab20873d048a8508e67301e7231c1"),
    "behavior": ("20260702_MarsDogTree", "9f2eb0dee84f84bb84a4e497aba4e3effe4d10da"),
    "action": ("20260707_MarsDogAction", "f00c3fdf2945c7a09d5f49ffc3d0df39c37ca2a8"),
    "robot": ("slam/robot_ws", "7dd357fdfe1664775c051195a3c0562af6892d84"),
    "rtabmap": ("slam/rtabmap_ws", "91faa212039c9274f67aa30c147eeb4dfbfc63f2"),
}


def git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        check=True, capture_output=True, text=True, env=env,
    ).stdout


def file_record(path: Path, mode: str) -> dict:
    if mode == "160000":
        raise ValueError(f"Submodule requires separate capture: {path}")
    payload = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    actual_mode = "120000" if path.is_symlink() else (
        "100755" if path.stat().st_mode & 0o111 else "100644"
    )
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload), "index_mode": mode, "working_mode": actual_mode,
    }


def tracked_files(repo: Path) -> dict[str, dict]:
    result = {}
    for entry in git(repo, "ls-files", "--stage", "-z").split("\0"):
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, blob, stage = metadata.split()
        if stage != "0":
            raise ValueError(f"Unmerged path: {repo / name}")
        record = file_record(repo / name, mode)
        record["git_blob"] = blob
        result[name] = record
    return result


def compare_files(repo: Path, expected: dict) -> list[dict]:
    differences = []
    for name, record in expected.items():
        path = repo / name
        if not path.exists() and not path.is_symlink():
            differences.append({"path": name, "reason": "missing"})
            continue
        current = file_record(path, record["index_mode"])
        for field in ("sha256", "working_mode"):
            if current[field] != record[field]:
                differences.append({"path": name, "reason": field})
    return differences


def inventory_package(path: Path) -> dict:
    root = ET.parse(path).getroot()
    dependencies = []
    for item in root:
        if item.tag.endswith("depend") or item.tag == "depend":
            dependencies.append({
                "kind": item.tag, "name": item.text,
                "condition": item.attrib.get("condition"),
            })
    return {
        "name": root.findtext("name"),
        "version": root.findtext("version"),
        "build_types": [
            {"name": n.text, "condition": n.attrib.get("condition")}
            for n in root.findall("./export/build_type")
        ],
        "dependencies": dependencies,
    }


def read_baseline() -> dict:
    return json.loads((ROOT / "baseline/sources.json").read_text())


def verify_sources(workspace: Path = WORKSPACE) -> dict:
    failures = []
    baseline = read_baseline()
    for source_id, source in baseline["sources"].items():
        repo = workspace / source["path"]
        if git(repo, "rev-parse", "HEAD").strip() != source["head"]:
            failures.append({"source": source_id, "reason": "HEAD"})
        status = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        if status != source["status_porcelain"]:
            failures.append({"source": source_id, "reason": "git_status", "actual": status})
        current = tracked_files(repo)
        if set(current) != set(source["files"]):
            failures.append({"source": source_id, "reason": "tracked_path_set"})
        for diff in compare_files(repo, source["files"]):
            failures.append({"source": source_id, **diff})
        for name in set(current) & set(source["files"]):
            for field in ("git_blob", "index_mode"):
                if current[name][field] != source["files"][name][field]:
                    failures.append({"source": source_id, "path": name, "reason": field})
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def clean_environment() -> dict:
    env = dict(os.environ)
    for name in list(env):
        if name.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "CYCLONEDDS_")):
            env.pop(name)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE"):
        env.pop(name, None)
    env.update(
        PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        UV_CACHE_DIR=str(ROOT / ".cache/uv"), UV_PYTHON_DOWNLOADS="never",
    )
    return env
