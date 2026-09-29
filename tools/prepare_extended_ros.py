"""Optional pinned Nav2/SLAM dependencies, never installed into the host OS."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.request
import time

from runtime_environment import ROOT

LOCK = ROOT / "third_party/extended-ros-deps.lock.json"
BASE = ROOT / "out/extended-ros"
PREFIX = BASE / "deps"
VIEW = BASE / "relocated"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inventory(root):
    return {p.relative_to(root).as_posix():
            (["link", str(p.readlink())] if p.is_symlink() else
             ["file", p.stat().st_mode & 0o777, sha(p)])
            for p in root.rglob("*") if p.is_symlink() or p.is_file()}

def prepare():
    if platform.machine() != "x86_64":
        raise RuntimeError("This lock is Ubuntu 22.04 amd64 only")
    records = json.loads(LOCK.read_text())["packages"]
    cache = BASE / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    def download(record):
        path = cache / record["url"].rsplit("/", 1)[-1]
        if not path.exists():
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(record["url"], timeout=45) as response:
                        payload = response.read()
                    break
                except (OSError, urllib.error.URLError):
                    if attempt == 2:
                        raise RuntimeError("Download failed: " + record["package"])
                    time.sleep(1 + attempt)
            if hashlib.sha256(payload).hexdigest() != record["sha256"]:
                raise RuntimeError("Download checksum mismatch: " + record["package"])
            path.write_bytes(payload)
        if sha(path) != record["sha256"]:
            raise RuntimeError("Cached checksum mismatch: " + str(path))
        return path
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        archives = list(executor.map(download, records))
    # Reconstruct expected bytes on each preparation; receipts alone are insufficient.
    with tempfile.TemporaryDirectory(prefix="verify-", dir=BASE) as tmp:
        extracted = Path(tmp) / "deps"
        for archive in archives:
            subprocess.run(["dpkg-deb", "--extract", str(archive), str(extracted)], check=True)
        if PREFIX.exists():
            if inventory(PREFIX) != inventory(extracted):
                raise RuntimeError("Optional dependency extraction has changed; retain it for diagnosis")
        else:
            extracted.rename(PREFIX)
    (BASE / "dependencies.json").write_text(json.dumps({
        "lock_sha256": sha(LOCK), "packages": records, "files": inventory(PREFIX)
    }, indent=2) + "\n")
    relocate()
    print("Verified optional ROS dependencies:", len(records), flush=True)


def relocate():
    # Debian CMake exports contain absolute /opt and /usr paths. Keep verified
    # payloads untouched; derive a separately audited, relocatable build view.
    with tempfile.TemporaryDirectory(prefix="relocate-", dir=BASE) as tmp:
        view = Path(tmp) / "prefix"
        shutil.copytree(PREFIX, view, symlinks=True)
        changes = []
        for link in view.rglob("*"):
            if link.is_symlink() and not link.exists():
                host = (Path("/") / link.relative_to(view)).parent / link.readlink()
                if host.is_file():
                    before = str(link.readlink())
                    link.unlink()
                    link.symlink_to(host.resolve())
                    changes.append({"file": link.relative_to(view).as_posix(),
                                    "host_link_before": before, "host_link_after": str(host.resolve())})
        for path in view.rglob("*"):
            if path.is_symlink() or path.suffix not in (".cmake", ".pc"):
                continue
            before = path.read_text()
            def replacement(match):
                raw = match.group(0)
                if (view / raw.lstrip("/")).exists():
                    return str(VIEW / raw.lstrip("/"))
                return raw
            after = re.sub(r"(?<![a-zA-Z0-9_}/.])/(?:opt/ros/humble|usr|lib)/[a-zA-Z0-9_./+~-]+", replacement, before)
            if after != before:
                path.write_text(after)
                changes.append({"file": path.relative_to(view).as_posix(),
                                "before": hashlib.sha256(before.encode()).hexdigest(),
                                "after": hashlib.sha256(after.encode()).hexdigest()})
        if VIEW.exists():
            if inventory(VIEW) != inventory(view):
                raise RuntimeError("Relocated dependency view has changed")
        else:
            view.rename(VIEW)
        (BASE / "relocations.json").write_text(json.dumps(changes, indent=2) + "\n")

def environment(env):
    receipt = BASE / "dependencies.json"
    if not receipt.is_file() or json.loads(receipt.read_text())["lock_sha256"] != sha(LOCK):
        raise RuntimeError("Run python3 tools/prepare_extended_ros.py first")
    ros = VIEW / "opt/ros/humble"
    def prepend(key, paths):
        env[key] = ":".join(str(p) for p in paths if p.exists()) + (":" + env[key] if env.get(key) else "")
    prepend("AMENT_PREFIX_PATH", [ros])
    prepend("CMAKE_PREFIX_PATH", [ros, VIEW / "usr"])
    prepend("LD_LIBRARY_PATH", [ros / "lib", VIEW / "usr/lib", VIEW / "usr/lib/x86_64-linux-gnu", VIEW / "lib/x86_64-linux-gnu"])
    prepend("LIBRARY_PATH", [VIEW / "usr/lib/x86_64-linux-gnu"])
    prepend("PKG_CONFIG_PATH", [ros / "lib/pkgconfig", VIEW / "usr/lib/x86_64-linux-gnu/pkgconfig"])
    prepend("PYTHONPATH", [ros / "local/lib/python3.10/dist-packages"])
    return env

if __name__ == "__main__":
    prepare()
