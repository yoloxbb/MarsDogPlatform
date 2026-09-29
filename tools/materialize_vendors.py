"""Materialize pinned vendor trees from verified local history bundles."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
from runtime_environment import vendor_archive_directory

ROOT = Path(__file__).resolve().parents[1]

def run(*command):
    return subprocess.run(command, check=True, capture_output=True).stdout

def verify_tree(destination, expected):
    actual = {}
    for path in destination.rglob("*"):
        if path.is_file() or path.is_symlink():
            name = path.relative_to(destination).as_posix()
            mode = "120000" if path.is_symlink() else "100755" if path.stat().st_mode & 0o111 else "100644"
            payload = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
            actual[name] = [mode, blob]
    if actual != expected:
        raise RuntimeError(f"Vendor contents/modes differ: {destination}; existing data was not overwritten")

def materialize(name, record, archive_dir):
    external = ROOT / ".external"
    external.mkdir(exist_ok=True)
    destination = external / name
    bundle = archive_dir / record["archive"]
    assert bundle.is_file(), f"Required preserved bundle: {bundle}"
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == record["archive_sha256"], "Bundle checksum differs"
    with tempfile.TemporaryDirectory(prefix="vendor-", dir=external) as temp:
        temporary = Path(temp)
        mirror = temporary / "source.git"
        run("git", "clone", "--mirror", str(bundle), str(mirror))
        revision = record["commit"] + (":" + record["subtree"] if record["subtree"] else "")
        tree = run("git", "-C", str(mirror), "rev-parse", revision + "^{tree}" if not record["subtree"] else revision).decode().strip()
        assert tree == record["tree"], "Pinned tree differs"
        entries = run("git", "-C", str(mirror), "ls-tree", "-r", "-z", tree).decode().rstrip("\0").split("\0")
        expected = {}
        for entry in entries:
            metadata, path = entry.split("\t", 1)
            mode, kind, blob = metadata.split()
            assert kind == "blob", "Submodules require their own pin"
            expected[path] = [mode, blob]
        if destination.exists():
            verify_tree(destination, expected)
            return {"status": "VERIFIED", "path": str(destination), "files": len(expected)}
        staging = temporary / "tree"
        staging.mkdir()
        payload = run("git", "-C", str(mirror), "archive", "--format=tar", tree)
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                assert not relative.is_absolute() and ".." not in relative.parts
                target = staging / relative
                assert target.resolve().is_relative_to(staging.resolve())
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
                    target.chmod(member.mode)
                elif member.issym():
                    assert not PurePosixPath(member.linkname).is_absolute()
                    assert (target.parent / member.linkname).resolve().is_relative_to(staging.resolve())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(member.linkname)
                else:
                    raise RuntimeError(f"Unsupported vendor archive entry: {member.name}")
        verify_tree(staging, expected)
        staging.rename(destination)
    return {"status": "MATERIALIZED", "path": str(destination), "files": len(expected)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, default=vendor_archive_directory())
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    lock = json.loads((ROOT / "third_party/sources.lock.json").read_text())
    selected = args.only or list(lock["sources"])
    assert set(selected) <= set(lock["sources"]), "Unknown vendor name"
    result = {n: materialize(n, lock["sources"][n], args.archive_dir.resolve()) for n in selected}
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
