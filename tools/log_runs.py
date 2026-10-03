"""Run metadata and offline retention planning; no module runtime imports."""
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

COMPONENT_MAP = {
    "voice_interaction": "voice", "vision_interaction": "vision", "camera_driver": "vision", "vision_debug_viewer": "vision",
    "behavior_tree_node": "behavior", "action_executor_node": "action",
    "emotion_engine_node": "emotion", "internal_need_node": "emotion",
    "time_controller_node": "emotion", "personality_node": "emotion",
    "midnight_test_node": "emotion", "one1000_tactile_node": "emotion",
}


def prepare_logging(env, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    run_id = directory.name + "-" + uuid.uuid4().hex[:8]
    env.update(MARSDOG_RUN_ID=run_id, MARSDOG_LOG_DIR=str(directory / "structured"),
               MARSDOG_LOG_COMPONENT_MAP=json.dumps(COMPONENT_MAP))
    manifest = {"log_manifest_version": 1, "run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
                "state": "active", "directory": str(directory), "components": COMPONENT_MAP,
                "managed_log_directories": ["structured", "ros-log", "voice-log", "vision-log"],
                "managed_root_logs": True,
                "policy": {"max_bytes_per_structured_file": env.get("MARSDOG_LOG_MAX_BYTES", 20*1024*1024),
                           "backups": env.get("MARSDOG_LOG_BACKUPS", 4),
                           "queue_size": env.get("MARSDOG_LOG_QUEUE_SIZE", 1024)}}
    (directory / "log-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def finish_logging(directory, status):
    path = Path(directory) / "log-manifest.json"
    if not path.exists():
        return
    value = json.loads(path.read_text())
    value.update(state="closed", outcome=status, ended_at=datetime.now(timezone.utc).isoformat())
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def managed_files(directory):
    """Only fixed log locations of newly managed runs, never config/data/model files."""
    files = []
    for folder in ("structured", "ros-log", "voice-log", "vision-log"):
        base = directory / folder
        if base.is_symlink() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if (path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(directory.resolve())
                    and not any(parent.is_symlink() for parent in path.parents if parent != directory.parent)
                    and (".log" in path.name or ".jsonl" in path.name or path.name.endswith(".health.json"))):
                files.append(path)
    files.extend(p for p in directory.glob("*.log*") if p.is_file() and not p.is_symlink())
    return sorted(set(files))


def retention_plan(root, keep_runs=20, max_total_bytes=1024*1024*1024):
    root = Path(root).resolve()
    candidates = []
    active_bytes = 0
    for directory in root.iterdir():
        if directory.is_symlink() or not directory.is_dir():
            continue
        marker = directory / "log-manifest.json"
        if marker.is_symlink() or not marker.is_file():
            continue
        data = json.loads(marker.read_text())
        if data.get("log_manifest_version") != 1 or data.get("directory") != str(directory.resolve()):
            continue
        files = managed_files(directory)
        size = sum(p.stat().st_size for p in files)
        if data.get("state") == "closed":
            candidates.append((data.get("started_at", ""), directory, files, size))
        else:
            active_bytes += size
    candidates.sort(reverse=True, key=lambda row: row[0])
    retained = active_bytes
    prune = []
    for index, (_, directory, files, size) in enumerate(candidates):
        if index < keep_runs and retained + size <= max_total_bytes:
            retained += size
        else:
            prune.extend({"path": str(p), "bytes": p.stat().st_size, "run": str(directory)} for p in files)
    return {"files": prune, "bytes": sum(p["bytes"] for p in prune), "active_bytes": active_bytes,
            "retained_bytes": retained, "active_budget_exceeded": active_bytes > max_total_bytes}


def apply_retention(plan, root):
    root = Path(root).resolve()
    # Recompute ownership and state before each unlink; never delete whole run directories.
    for item in plan["files"]:
        path, directory = Path(item["path"]), Path(item["run"])
        if not directory.resolve().is_relative_to(root) or directory.is_symlink():
            raise ValueError("Retention target is outside the managed root")
        marker = directory / "log-manifest.json"
        data = {} if marker.is_symlink() else json.loads(marker.read_text())
        if (data.get("state") != "closed" or data.get("log_manifest_version") != 1
                or data.get("directory") != str(directory.resolve())):
            raise ValueError("Run became active or untrusted")
        if path not in managed_files(directory) or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Log ownership changed")
        path.unlink()
