"""P2: preserve and verify original history, transform a COPY, import only Emotion."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from baseline_lib import ROOT, WORKSPACE, git, read_baseline, compare_files, verify_sources


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def main():
    if verify_sources()["status"] != "PASS":
        raise SystemExit("Approved sources changed")
    target = WORKSPACE / "marsdog-platform"
    if target.exists():
        raise SystemExit("Target already exists; no automatic overwrite")
    source = WORKSPACE / "MarsDogEmotion"
    archives = ROOT / "archives"
    archives.mkdir(exist_ok=True)
    bundle = archives / "emotion-cd1e047-all-refs.bundle"
    if bundle.exists():
        raise SystemExit("Archive already exists; inspect before retry")
    work = ROOT / "work/p2-emotion-history"
    work.mkdir()
    refs = git(source, "for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    objects = git(source, "rev-list", "--objects", "--all").splitlines()
    suspect = [row for row in objects if len(row.split(" ", 1)) > 1 and
               (Path(row.split(" ", 1)[1]).name in {".env", "id_rsa", "id_ed25519"}
                or Path(row.split(" ", 1)[1]).suffix in {".pem", ".key"})]
    if suspect:
        raise SystemExit("History contains credential-like paths; review before import")
    run(["git", "--no-optional-locks", "-C", str(source), "bundle", "create", str(bundle), "--all"])
    verification = run(["git", "--no-optional-locks", "-C", str(source), "bundle", "verify", str(bundle)])
    restored = work / "restored.git"
    run(["git", "clone", "--mirror", str(bundle), str(restored)])
    restored_refs = git(restored, "for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    if refs != restored_refs:
        raise SystemExit("Restored refs do not match source")
    run(["git", "-C", str(restored), "fsck", "--full"])
    original_commits = git(source, "rev-list", "--all", "--count").strip()
    if git(restored, "rev-list", "--all", "--count").strip() != original_commits:
        raise SystemExit("Restored history count differs")
    transformed = work / "transformed.git"
    run(["git", "clone", "--mirror", "--no-hardlinks", str(restored), str(transformed)])
    env = dict(os.environ, PATH=str(ROOT / ".venv/bin") + os.pathsep + os.environ["PATH"])
    run(["git", "-C", str(transformed), "filter-repo", "--force",
         "--to-subdirectory-filter", "modules/emotion"], env=env)
    run(["git", "clone", "--no-hardlinks", "--branch", "my-changes", str(transformed), str(target)])
    run(["git", "-C", str(target), "branch", "-m", "main"])
    run(["git", "-C", str(target), "remote", "remove", "origin"])
    differences = compare_files(target / "modules/emotion", read_baseline()["sources"]["emotion"]["files"])
    if differences:
        raise SystemExit(json.dumps(differences))
    imported_head = git(target, "rev-parse", "HEAD").strip()
    history_dir = target / "docs/migration/history"
    history_dir.mkdir(parents=True)
    shutil.copy2(transformed / "filter-repo/commit-map", history_dir / "emotion-commit-map.txt")
    manifest = {
        "source_id": "emotion", "source_path": str(source),
        "original_head": read_baseline()["sources"]["emotion"]["head"],
        "imported_head": imported_head, "original_refs": refs,
        "original_commit_count": int(original_commits),
        "archive": str(bundle), "archive_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "archive_verification": verification, "restore_fsck": "PASS",
        "restored_refs_equal": True, "tracked_file_content_and_modes_equal": True,
        "transform": "git-filter-repo 2.47.0 --to-subdirectory-filter modules/emotion (copy only)",
        "original_sources": verify_sources(),
    }
    (history_dir / "emotion-import.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (ROOT / "reports/p1-20260928/emotion-history-import.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"target": str(target), "original_commits": original_commits,
                      "imported_head": imported_head, "archive": str(bundle)}, indent=2))


if __name__ == "__main__":
    main()
