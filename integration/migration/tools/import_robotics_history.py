"""Selective Robotics history import; preserve the complete original in its bundle."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from baseline_lib import ROOT as WORK, WORKSPACE, git, read_baseline, verify_sources

PLATFORM = Path(__file__).resolve().parents[3]
MAPPING = {
    "sensor_ws/src/stereo_v4l2_camera/": "robotics/ros2/src/stereo_v4l2_camera/",
    "imu_ws/src/stereo_v4l2_camera/": "robotics/ros2/src/stereo_v4l2_camera/",
    "sensor_ws/src/wit_imu/": "robotics/ros2/src/wit_imu/",
    "imu_ws/src/wit_imu/": "robotics/ros2/src/wit_imu/",
    "slam_ws/src/person_3d_localization/": "robotics/ros2/src/person_3d_localization/",
    "slam_ws/src/behavior_ext_plugins/": "robotics/ros2/src/behavior_ext_plugins/",
    "slam_ws/src/robot_slam_bringup/": "robotics/ros2/src/robot_slam_bringup/",
    "slam_ws/src/stereo_slam_legacy_bringup/": "robotics/ros2/src/stereo_slam_legacy_bringup/",
    "go2_follow_ws/src/go2_uwb_local_follow/": "robotics/ros2/src/go2_uwb_local_follow/",
    "go2_follow_ws/src/go2_uwb_behavior/": "robotics/ros2/src/go2_uwb_behavior/",
}

def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs).stdout

def main():
    assert verify_sources()["status"] == "PASS"
    assert not git(PLATFORM, "status", "--porcelain=v1", "--untracked-files=all"), "Checkpoint platform first"
    baseline = read_baseline()["sources"]["robot"]
    record = json.loads((PLATFORM / "docs/migration/history/robot-archive.json").read_text())
    gate = json.loads((PLATFORM / "validation/p5-robotics/candidate.json").read_text())
    assert gate["status"] == "PASS_WITH_EXPLICIT_LIMITS"
    assert gate["counts"]["tests"] > 0 and all(t["status"] == "passed" for t in gate["ctest"])
    bundle = Path(record["archive"])
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == record["archive_sha256"]
    restored = WORK / "work/history-robot/restored.git"
    assert git(restored, "for-each-ref", "--format=%(refname) %(objectname)").splitlines() == record["original_refs"]
    transformed = WORK / "work/history-robot/selected.git"
    assert not transformed.exists(), "Inspect existing transformed history before retrying"
    before = git(PLATFORM, "rev-parse", "HEAD").strip()
    run(["git", "clone", "--mirror", "--no-hardlinks", str(restored), str(transformed)])
    command = ["git", "-C", str(transformed), "filter-repo", "--force"]
    for source, target in MAPPING.items():
        command += ["--path", source, "--path-rename", source + ":" + target]
    run(command, env=dict(os.environ, PATH=str(WORK / ".venv/bin") + os.pathsep + os.environ["PATH"]))
    commit_map = (transformed / "filter-repo/commit-map").read_text()
    mapping = dict(line.split() for line in commit_map.splitlines()[1:])
    incoming = mapping[baseline["head"]]
    source = WORKSPACE / baseline["path"]
    expected = {}
    for entry in git(source, "ls-tree", "-r", "-z", "HEAD").rstrip("\0").split("\0"):
        metadata, name = entry.split("\t", 1)
        for old, new in MAPPING.items():
            if name.startswith(old):
                expected[new + name[len(old):]] = metadata
    actual = {}
    for entry in git(transformed, "ls-tree", "-r", "-z", incoming).rstrip("\0").split("\0"):
        metadata, name = entry.split("\t", 1)
        actual[name] = metadata
    assert actual == expected, "Selected history changed current files or modes"
    for name in actual:
        assert not (PLATFORM / name).exists(), "Destination exists: " + name
    ref = "refs/migration/robot/import"
    run(["git", "-C", str(PLATFORM), "fetch", "--no-tags", str(transformed), incoming + ":" + ref])
    identity = ["-c", "user.name=MarsDog Migration", "-c", "user.email=migration@localhost"]
    run(["git", "-C", str(PLATFORM), *identity, "merge", "--no-commit", "--no-ff",
         "--allow-unrelated-histories", ref])
    assert verify_sources()["status"] == "PASS"
    run(["git", "-C", str(PLATFORM), *identity, "commit", "-m",
         "chore(robotics): preserve selected ROS package history and original interfaces"])
    history = PLATFORM / "docs/migration/history"
    (history / "robot-commit-map.txt").write_text(commit_map)
    manifest = dict(record, target_before=before, imported_head=incoming,
                    merge_commit=git(PLATFORM, "rev-parse", "HEAD").strip(),
                    selected_files=len(actual), path_mapping=MAPPING,
                    filtered_reachable_commits=int(git(transformed, "rev-list", "--all", "--count")),
                    exact_blobs_and_modes_equal=True,
                    limits=["behavior_ext_plugins retained byte-for-byte; full Nav2 build not verified",
                            "Complete 31-commit history including omitted/vendor paths is in verified bundle",
                            "Known C++ syntax defect deliberately imported unchanged; separate repair follows"])
    (history / "robot-import.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))

if __name__ == "__main__":
    main()
