"""Capture the approved seven-repository baseline; refuses to replace it."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from baseline_lib import ROOT, WORKSPACE, SOURCES, git, tracked_files, inventory_package


def main() -> None:
    destination = ROOT / "baseline/sources.json"
    if destination.exists():
        raise SystemExit("Baseline already exists; use check_baseline.py. Never rebase a failure away.")
    baseline = {
        "schema_version": 1, "captured_at": datetime.now(timezone.utc).isoformat(),
        "workspace_at_capture": str(WORKSPACE), "sources": {},
    }
    interfaces = {"schema_version": 1, "idl": [], "packages": []}
    for source_id, (relative, expected_head) in SOURCES.items():
        repo = WORKSPACE / relative
        head = git(repo, "rev-parse", "HEAD").strip()
        status = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        if head != expected_head or status:
            raise SystemExit(f"Approved clean baseline changed: {source_id}")
        files = tracked_files(repo)
        baseline["sources"][source_id] = {
            "path": relative, "head": head, "status_porcelain": status,
            "ignored_paths": git(repo, "ls-files", "--others", "--ignored",
                                 "--exclude-standard", "--directory").splitlines(),
            "files": files,
        }
        for name, record in files.items():
            path = repo / name
            if Path(name).suffix in {".srv", ".msg", ".action"}:
                interfaces["idl"].append({
                    "source": source_id, "path": name, "sha256": record["sha256"],
                    "content": path.read_text(),
                })
            elif path.name == "package.xml":
                interfaces["packages"].append({
                    "source": source_id, "path": name, **inventory_package(path),
                })
        print(f"{source_id}: {len(files)} tracked paths captured")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n")
    (destination.parent / "interfaces.json").write_text(
        json.dumps(interfaces, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"{len(interfaces['packages'])} package manifests; {len(interfaces['idl'])} IDL files")


if __name__ == "__main__":
    main()
