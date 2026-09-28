"""Import one independently approved module into the new repo; filter only a copy."""
from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser()
    # Extend only after a module-specific migration gate has been assessed.
    parser.add_argument("module", choices=["behavior"])
    parser.add_argument("--resume-prepared", action="store_true",
                        help="Reverify an already prepared archive/copy before importing")
    args = parser.parse_args()
    module = args.module
    assert verify_sources()["status"] == "PASS", "Original source drift"
    baseline = read_baseline()["sources"][module]
    source = WORKSPACE / baseline["path"]
    target = WORKSPACE / "marsdog-platform"
    assert not git(target, "status", "--porcelain=v1", "--untracked-files=all"), "Target must be clean"
    assert not (target / "modules" / module).exists(), "Module already imported"
    target_before = git(target, "rev-parse", "HEAD").strip()
    refs = git(source, "for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    branch = git(source, "symbolic-ref", "--short", "HEAD").strip()
    work = ROOT / "work" / ("history-" + module)
    bundle = ROOT / "archives" / f"{module}-{baseline['head'][:7]}-all-refs.bundle"
    if not args.resume_prepared:
        work.mkdir()
        assert not bundle.exists(), "Archive already exists; inspect instead of overwrite"
        run(["git", "--no-optional-locks", "-C", str(source), "bundle", "create", str(bundle), "--all"])
    run(["git", "--no-optional-locks", "-C", str(source), "bundle", "verify", str(bundle)])
    restored = work / "restored.git"
    if not args.resume_prepared:
        run(["git", "clone", "--mirror", str(bundle), str(restored)])
    assert git(restored, "for-each-ref", "--format=%(refname) %(objectname)").splitlines() == refs
    run(["git", "-C", str(restored), "fsck", "--full"])
    commits = int(git(source, "rev-list", "--all", "--count").strip())
    assert int(git(restored, "rev-list", "--all", "--count").strip()) == commits
    transformed = work / "transformed.git"
    env = dict(os.environ, PATH=str(ROOT / ".venv/bin") + os.pathsep + os.environ["PATH"])
    if not args.resume_prepared:
        run(["git", "clone", "--mirror", "--no-hardlinks", str(restored), str(transformed)])
        run(["git", "-C", str(transformed), "filter-repo", "--force",
             "--to-subdirectory-filter", "modules/" + module], env=env)
    incoming = git(transformed, "rev-parse", "refs/heads/" + branch).strip()
    commit_map = dict(line.split() for line in
                      (transformed / "filter-repo/commit-map").read_text().splitlines()[1:])
    assert commit_map[baseline["head"]] == incoming
    original_tree = git(source, "ls-tree", "-r", "HEAD").splitlines()
    imported_tree = git(transformed, "ls-tree", "-r", incoming).splitlines()
    expected_tree = [metadata + "\tmodules/" + module + "/" + path
                     for metadata, path in (line.split("\t", 1) for line in original_tree)]
    assert imported_tree == expected_tree, "Prefix import tree mismatch"
    ref = "refs/migration/" + module + "/import"
    run(["git", "-C", str(target), "fetch", "--no-tags", str(transformed), incoming + ":" + ref])
    run(["git", "-C", str(target), "-c", "user.name=MarsDog Migration",
         "-c", "user.email=migration@localhost", "merge", "--no-commit", "--no-ff",
         "--allow-unrelated-histories", ref])
    differences = compare_files(target / "modules" / module, baseline["files"])
    assert not differences, differences
    # Exact path set, not only a comparison of original paths that still exist.
    staged = git(target, "ls-files", "modules/" + module).splitlines()
    assert {p.removeprefix("modules/" + module + "/") for p in staged} == set(baseline["files"])
    assert verify_sources()["status"] == "PASS", "Original changed during import"
    run(["git", "-C", str(target), "-c", "user.name=MarsDog Migration",
         "-c", "user.email=migration@localhost", "commit", "-m",
         f"chore({module}): import verified history without implementation changes"])
    history = target / "docs/migration/history"
    shutil.copy2(transformed / "filter-repo/commit-map", history / (module + "-commit-map.txt"))
    manifest = {
        "source_id": module, "source_path": str(source), "original_head": baseline["head"],
        "original_refs": refs, "original_commit_count": commits, "target_before": target_before,
        "imported_head": incoming, "merge_commit": git(target, "rev-parse", "HEAD").strip(),
        "archive": str(bundle), "archive_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "restore_fsck": "PASS", "restored_refs_equal": True,
        "tracked_file_content_and_modes_equal": True, "tracked_files": len(staged),
        "transform": f"git-filter-repo 2.47.0 --to-subdirectory-filter modules/{module} (copy only)",
        "original_sources": verify_sources(),
    }
    (history / (module + "-import.json")).write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
