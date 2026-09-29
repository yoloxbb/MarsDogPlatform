"""Build preserved Nav2/OpenVINS/RTAB sources in an optional CPU overlay."""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time

from runtime_environment import ROOT, ros_environment, vendor_archive_directory
from prepare_extended_ros import environment, BASE, VIEW, sha, inventory

TOOLS = ROOT / "platform/humble-build-tools/.venv/bin"
INSTALL = BASE / "install"


def source_sha256(paths):
    digest = hashlib.sha256()
    for directory in paths:
        for path in sorted(directory.rglob("*")):
            if path.is_file() or path.is_symlink():
                digest.update(str(path.relative_to(ROOT)).encode() + bytes([0]))
                digest.update(str(path.lstat().st_mode & 0o777).encode() + bytes([0]))
                digest.update(str(path.readlink()).encode() if path.is_symlink() else path.read_bytes())
    return digest.hexdigest()


def rtabmap_build_copy(source):
    work = BASE / "vendor-source/rtabmap"
    generated = "rtabmap/corelib/src/resources/DatabaseSchema.sql"
    if not work.exists():
        work.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, work, symlinks=True)
    actual = inventory(work)
    # The one documented upstream CONFIGURE_FILE output may exist only in the
    # build copy. Everything else must still equal the sealed source snapshot.
    actual.pop(generated, None)
    expected = inventory(source)
    if generated in expected or actual != expected:
        raise RuntimeError("RTAB source/build copy differs from its fixed snapshot")
    return work

def build(layer, jobs=2):
    paths = {
        "nav2-plugin": [ROOT / "robotics/ros2/src/behavior_ext_plugins"],
        "openvins": [ROOT / ".external/openvins"],
        "rtabmap": [ROOT / ".external/rtabmap/src"],
    }[layer]
    if layer == "rtabmap":
        work = rtabmap_build_copy(paths[0])
        # Only upstream core generates files in-source. ROS wrappers stay on the
        # sealed snapshot and retain their already verified incremental build.
        build_paths = [work / "rtabmap", paths[0] / "rtabmap_ros"]
    else:
        build_paths = paths
    build_base = BASE / "build"
    env = environment(ros_environment(INSTALL if (INSTALL / "local_setup.bash").exists() else None, 212))
    env.update(CMAKE_BUILD_PARALLEL_LEVEL=str(jobs), MAKEFLAGS="-j" + str(jobs),
               COLCON_EXTENSION_BLOCKLIST="colcon_core.event_handler.desktop_notification")
    # Isolated system headers/libs; source snapshots remain byte-identical.
    env["CPLUS_INCLUDE_PATH"] = str(VIEW / "usr/include")
    command = [str(TOOLS / "colcon"), "--log-base", str(BASE / "logs" / layer), "build",
               "--base-paths", *map(str, build_paths), "--build-base", str(build_base),
               "--install-base", str(INSTALL), "--executor", "sequential",
               "--event-handlers", "console_direct+", "--cmake-clean-cache", "--cmake-args",
               "-DCMAKE_BUILD_TYPE=Release",
               "-DPYTHON_EXECUTABLE=" + str(TOOLS / "python"),
               "-DPython3_EXECUTABLE=" + str(TOOLS / "python")]
    if layer == "nav2-plugin":
        command += ["-DBUILD_TESTING=OFF"]
    elif layer == "openvins":
        command += ["-DBUILD_TESTING=ON", "-DENABLE_ROS=ON"]
    else:
        command += ["-DBUILD_TESTING=OFF", "-DWITH_OPENVINS=ON",
                    "-DWITH_QT=ON", "-DWITH_TORCH=OFF", "-DWITH_CUDASIFT=OFF"]
    source_hash = source_sha256(paths)
    log = BASE / (layer + "-build.log")
    started = time.monotonic()
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=10800)
    report = {"status": "PASS" if result.returncode == 0 else "FAIL", "layer": layer,
              "command": command, "returncode": result.returncode, "parallel_compile_jobs": jobs,
              "elapsed_seconds": round(time.monotonic() - started, 2),
              "source_paths": [str(p.relative_to(ROOT)) for p in paths],
              "build_source_paths": [str(p.relative_to(ROOT)) for p in build_paths],
              "source_sha256": source_hash,
              "sources_unchanged_during_build": source_hash == source_sha256(paths),
              "source_lock_sha256": sha(ROOT / "third_party/sources.lock.json"),
              "dependency_lock_sha256": sha(ROOT / "third_party/extended-ros-deps.lock.json"),
              "log": str(log), "scope": "CPU compilation only, no hardware/estimator accuracy claim"}
    if not report["sources_unchanged_during_build"]:
        report["status"] = "FAIL"
        result.returncode = 1
    (BASE / (layer + "-build.json")).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    if result.returncode:
        print(log.read_text()[-6000:], flush=True)
    return result.returncode

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layers", nargs="+", choices=["nav2-plugin", "openvins", "rtabmap"])
    parser.add_argument("--archive-dir", type=Path,
                        default=vendor_archive_directory())
    parser.add_argument("--jobs", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    BASE.mkdir(parents=True, exist_ok=True)
    with (BASE / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from materialize_vendors import materialize
        pins = json.loads((ROOT / "third_party/sources.lock.json").read_text())["sources"]
        for layer in args.layers:
            if layer in ("openvins", "rtabmap"):
                materialize(layer, pins[layer], args.archive_dir.resolve())
        failures = [layer for layer in args.layers if build(layer, args.jobs)]
    sys.exit(bool(failures))
