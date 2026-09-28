"""Copy tracked files into a disposable test tree; leave all source repos intact."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
from baseline_lib import ROOT, WORKSPACE, read_baseline, verify_sources, compare_files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--modules", nargs="+", default=["emotion", "behavior", "action", "vision", "voice"])
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("run-id must contain only letters, digits, hyphens, underscores")
    verified = verify_sources()
    if verified["status"] != "PASS":
        raise SystemExit(json.dumps(verified))
    baseline = read_baseline()
    base = ROOT / "work" / args.run_id / "sources"
    for module in args.modules:
        source = baseline["sources"][module]
        origin = WORKSPACE / source["path"]
        destination = base / module
        if destination.exists():
            raise SystemExit(f"Refusing to replace snapshot {destination}")
        destination.mkdir(parents=True)
        for name in source["files"]:
            src, dst = origin / name, destination / name
            if not src.resolve().is_relative_to(origin.resolve()):
                raise SystemExit(f"External symlink requires manual inventory: {src}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                target = os.readlink(src)
                if Path(target).is_absolute():
                    raise SystemExit(f"Absolute symlink requires explicit handling: {src}")
                dst.symlink_to(target)
            else:
                shutil.copy2(src, dst)
        differences = compare_files(destination, source["files"])
        if differences:
            raise SystemExit(json.dumps(differences))
        print(f"{module}: byte/mode-equivalent snapshot at {destination}")
    record = ROOT / "reports" / args.run_id
    record.mkdir(parents=True, exist_ok=True)
    (record / "snapshots.json").write_text(json.dumps({
        "status": "PASS", "source_heads": {
            m: baseline["sources"][m]["head"] for m in args.modules
        }, "snapshot_root": str(base),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
