"""Checksum-verified local ROS dependencies, extracted without modifying the OS."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    assert platform.machine() == "x86_64", "This development lock is Ubuntu amd64 only"
    directory = ROOT / "out/ros-deps"
    directory.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "third_party/local-ros-deps.lock.json").read_text())
    records = [r for r in lock["packages"] if not args.only or r["package"] in args.only]
    if args.only:
        assert len(records) == len(set(args.only)), "Unknown package"
    for record in records:
        filename = record["url"].rsplit("/", 1)[-1]
        archive = directory / filename
        if not archive.exists():
            cached = args.cache / filename if args.cache else None
            if cached and cached.is_file():
                payload = cached.read_bytes()
            else:
                with urllib.request.urlopen(record["url"], timeout=60) as response:
                    payload = response.read()
            assert hashlib.sha256(payload).hexdigest() == record["sha256"], filename
            archive.write_bytes(payload)
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == record["sha256"], filename
        target = directory / record["package"]
        marker = target / "archive.sha256"
        with tempfile.TemporaryDirectory(prefix="extract-", dir=directory) as temp:
            extracted = Path(temp) / "payload"
            subprocess.run(["dpkg-deb", "--extract", str(archive), str(extracted)], check=True)
            def inventory(root):
                result = {}
                for item in root.rglob("*"):
                    relative = item.relative_to(root).as_posix()
                    if relative == "archive.sha256":
                        continue
                    if item.is_symlink():
                        result[relative] = ("link", str(item.readlink()))
                    elif item.is_file():
                        result[relative] = ("file", item.stat().st_mode & 0o777,
                                            hashlib.sha256(item.read_bytes()).hexdigest())
                return result
            if target.exists():
                assert marker.is_file() and marker.read_text().strip() == record["sha256"], str(target)
                assert inventory(target) == inventory(extracted), "Extracted ROS dependency changed: " + str(target)
            else:
                (extracted / "archive.sha256").write_text(record["sha256"] + "\n")
                extracted.rename(target)
        print(record["package"] + ": " + record["version"], flush=True)

if __name__ == "__main__":
    main()
