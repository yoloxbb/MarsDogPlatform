"""Build full original/new Action packages with the recorded official Nav2 artifact."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
from baseline_lib import ROOT, WORKSPACE, verify_sources
from check_ros import ros_env, run_build


def action_environment(prefixes=()):
    nav_root = ROOT / "work/nav2-msgs-1.1.20"
    provenance = json.loads((nav_root / "provenance.json").read_text())
    assert hashlib.sha256((nav_root / "nav2-msgs.deb").read_bytes()).hexdigest() == provenance["sha256"]
    nav = Path(provenance["prefix"])
    work = ROOT / "work/p1-20260928"
    env = ros_env([work / "ros-voice/install", work / "ros-vision/install", *prefixes])
    for key, value in {
        "CMAKE_PREFIX_PATH": str(nav), "AMENT_PREFIX_PATH": str(nav),
        "LD_LIBRARY_PATH": str(nav / "lib"),
        "PYTHONPATH": str(nav / "local/lib/python3.10/dist-packages"),
    }.items():
        env[key] = value + os.pathsep + env.get(key, "")
    return env, provenance


def main():
    assert verify_sources()["status"] == "PASS"
    work, report = ROOT / "work/p1-20260928", ROOT / "reports/p1-20260928"
    sources = {"baseline": work / "sources/action", "migrated": WORKSPACE / "marsdog-platform/modules/action"}
    results = {"builds": {}, "callbacks": {}}
    for name, source in sources.items():
        env, provenance = action_environment()
        results["nav2_provenance"] = provenance
        build = run_build(source, "p3-action-" + name, work, report, env, ROOT / "ros-tools/.venv")
        results["builds"][name] = build
        if build["status"] != "PASS":
            continue
        prefix = Path(build["install"])
        env, _ = action_environment([prefix])
        env.update(ROS_DOMAIN_ID=str(180 + secrets.randbelow(30)), ROS_LOCALHOST_ONLY="1",
                   QT_QPA_PLATFORM="offscreen", ROS_LOG_DIR=str(report / "p3-action-ros-logs"))
        python = source / ".venv/bin/python"
        # Must prove imports resolve to the installed ROS package, away from source cwd.
        probe = subprocess.run([
            str(python), "-B", "-c",
            "import json,importlib.metadata;from pathlib import Path;from marsdog_action_executor import ros_node;"
            "from marsdog_action_executor.ros2_compat import get_execute_behavior_action;"
            "from nav2_msgs.action import NavigateToPose;"
            "from rclpy.type_support import check_for_type_support;"
            "check_for_type_support(NavigateToPose);"
            "print(json.dumps({'module':ros_node.__file__,'config':str(ros_node.ActionExecutorNode._resolve_config_dir()),"
            "'numpy_version':importlib.metadata.version('numpy')}))",
        ], cwd=work, env=env, text=True, capture_output=True, timeout=30)
        (report / f"p3-action-{name}-import.log").write_text(probe.stdout + probe.stderr)
        if probe.returncode:
            results["callbacks"][name] = {"status": "FAIL", "stage": "installed import"}
            continue
        observed = json.loads(probe.stdout.splitlines()[-1])
        assert Path(observed["module"]).is_relative_to(prefix)
        assert Path(observed["config"]).is_relative_to(prefix)
        junit = report / f"p3-action-{name}-ros-callbacks-junit.xml"
        command = [str(python), "-B", "-m", "pytest", "--import-mode=importlib", "-q",
                   "-p", "no:cacheprovider", "--junitxml=" + str(junit)]
        command += [str(source / "tests" / f) for f in (
            "test_long_goal_arbitration.py", "test_long_goal_runtime.py",
            "test_ros_goal_params_boundary.py", "test_ros_shutdown_boundary.py",
        )]
        with (report / f"p3-action-{name}-ros-callbacks.log").open("w") as stream:
            process = subprocess.run(command, cwd=work, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=180)
        results["callbacks"][name] = {
            "status": "PASS" if process.returncode == 0 else "FAIL", "command": command,
            "installed_import": observed,
            "scope": "Actual installed Action callbacks with existing fake collaborators; production node not constructed",
        }
    results["original_sources"] = verify_sources()
    results["status"] = "PASS" if all(c["status"] == "PASS" for c in [
        *results["builds"].values(), *results["callbacks"].values(), results["original_sources"],
    ]) else "FAIL"
    (report / "p3-action-ros.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if results["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
