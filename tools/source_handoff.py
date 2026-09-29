"""Export or verify a clean main-repository history bundle for internal source transfer."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from runtime_environment import ROOT

def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def clean_snapshot(root):
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Commit reviewed changes first; dirty sources cannot be exported")
    branch = git(root, "symbolic-ref", "--short", "HEAD")
    return {"commit": git(root, "rev-parse", "HEAD"), "branch": branch,
            "refs": git(root, "show-ref").splitlines()}

def create(root, destination, archive_dir=None):
    snapshot = clean_snapshot(root)
    pins = json.loads((root / "third_party/sources.lock.json").read_text())["sources"]
    archives = {}
    for record in pins.values():
        name, checksum = record["archive"], record["archive_sha256"]
        if Path(name).name != name or name in (".", ".."):
            raise RuntimeError("Invalid locked archive name")
        if name in archives and archives[name] != checksum:
            raise RuntimeError("Conflicting vendor archive hashes")
        archives[name] = checksum
    if archive_dir is not None:
        for name, checksum in archives.items():
            if not (archive_dir / name).is_file() or sha(archive_dir / name) != checksum:
                raise RuntimeError("Missing or changed locked vendor archive: " + name)
    destination.mkdir(parents=True, exist_ok=False)
    bundle = destination / "marsdog-platform.bundle"
    git(root, "bundle", "create", str(bundle), "--all")
    git(root, "bundle", "verify", str(bundle))
    files = {bundle.name: sha(bundle)}
    if archive_dir is not None:
        (destination / "vendor-archives").mkdir()
        for name, checksum in archives.items():
            target = destination / "vendor-archives" / name
            shutil.copy2(archive_dir / name, target)
            if sha(target) != checksum:
                raise RuntimeError("Archive changed while copying: " + name)
            files["vendor-archives/" + name] = checksum
    if clean_snapshot(root) != snapshot:
        raise RuntimeError("Source changed during export; do not use this incomplete export")
    manifest = {"schema_version": 1, "scope": "Internal source/history transfer, not a hardware release",
                "source": snapshot, "files": files,
                "required_vendor_archives": archives, "vendors_included": archive_dir is not None,
                "excluded": ["untracked and ignored files", "models", "Python environments",
                             "ROS build/install", "download caches", "host device configuration"],
                "target_board": "UNKNOWN; rebuild for the board OS/ABI, never copy WSL binaries"}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (destination / "README.txt").write_text(
        "Internal source transfer. Verify before cloning:\n"
        "  python3 /trusted/checkout/tools/source_handoff.py verify --directory THIS_DIRECTORY\n"
        "  git clone marsdog-platform.bundle marsdog-platform\n"
        "In the clone read README.md and docs/development/QUICKSTART.md.\n"
        "If included, use --archive-dir /absolute/path/to/vendor-archives for ROS preparation.\n"
        "Package digests detect corruption, not publisher identity. No hardware release claim.\n")
    return manifest

def verify(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema_version") != 1 or "marsdog-platform.bundle" not in manifest["files"]:
        raise RuntimeError("Invalid source manifest")
    for relative, expected in manifest["files"].items():
        path = directory / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or not path.resolve().is_relative_to(directory.resolve()):
            raise RuntimeError("Unsafe manifest path")
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError("Missing or changed file: " + relative)
    if manifest["vendors_included"]:
        for name, checksum in manifest["required_vendor_archives"].items():
            if manifest["files"].get("vendor-archives/" + name) != checksum:
                raise RuntimeError("Missing locked vendor archive: " + name)
    bundle = directory / "marsdog-platform.bundle"
    with tempfile.TemporaryDirectory(prefix="marsdog-bundle-verify-") as temporary:
        bare = Path(temporary) / "verify.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(bare)], check=True)
        git(bare, "bundle", "verify", str(bundle.resolve()))
    heads = git(directory, "bundle", "list-heads", str(bundle.resolve())).splitlines()
    for ref in manifest["source"]["refs"]:
        if ref not in heads:
            raise RuntimeError("Bundle is missing a recorded ref: " + ref)
    expected_head = manifest["source"]["commit"] + " refs/heads/" + manifest["source"]["branch"]
    if expected_head not in heads:
        raise RuntimeError("Source branch/commit differs")
    return {"status": "PASS", "commit": manifest["source"]["commit"],
            "verified_files": len(manifest["files"]),
            "vendors_included": manifest["vendors_included"]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("create")
    export.add_argument("--directory", type=Path, required=True, help="New directory; never overwritten")
    export.add_argument("--archive-dir", type=Path, help="Include only pinned vendor bundles (internal distribution)")
    check = sub.add_parser("verify")
    check.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (create(ROOT, args.directory.resolve(), args.archive_dir.resolve() if args.archive_dir else None)
                  if args.command == "create" else verify(args.directory.resolve()))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}))
        return 1

if __name__ == "__main__":
    sys.exit(main())
