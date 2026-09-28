"""ROS discovery/build checks on snapshots; no hardware nodes are launched."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from baseline_lib import ROOT, clean_environment, read_baseline, verify_sources


def ros_env(prefixes=()) -> dict:
    env = clean_environment()
    scripts = ["/opt/ros/humble/setup.bash", *[str(p / "local_setup.bash") for p in prefixes]]
    script = "\n".join("source " + shlex.quote(s) for s in scripts)
    script += "\n" + shlex.quote(str(ROOT / ".venv/bin/python")) + " -B -c 'import os,json;print(json.dumps(dict(os.environ)))'"
    result = subprocess.run(["bash", "--noprofile", "--norc", "-c", script],
                            env=env, text=True, capture_output=True, check=True)
    loaded = json.loads(result.stdout.splitlines()[-1])
    loaded.update(
        PYTHONDONTWRITEBYTECODE="1",
        COLCON_EXTENSION_BLOCKLIST="colcon_core.event_handler.desktop_notification",
        CMAKE_BUILD_PARALLEL_LEVEL="2",
    )
    return loaded


def run_build(source: Path, label: str, work: Path, report: Path, env: dict,
              tool_env: Path | None = None) -> dict:
    log = report / f"ros-{label}-build.log"
    root = work / ("ros-" + label)
    root.mkdir(exist_ok=True)
    tools = tool_env or ROOT / ".venv"
    args = [
        str(tools / "bin/colcon"), "--log-base", str(root / "log"), "build",
        "--base-paths", str(source), "--build-base", str(root / "build"),
        "--install-base", str(root / "install"), "--executor", "sequential",
        "--event-handlers", "console_direct+",
        "--cmake-args", "-DBUILD_TESTING=OFF",
        "-DPython3_EXECUTABLE=" + str(tools / "bin/python"),
        "-DPYTHON_EXECUTABLE=" + str(tools / "bin/python"),
    ]
    start = time.monotonic()
    try:
        with log.open("w") as stream:
            process = subprocess.run(args, cwd=root, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=600)
        code = process.returncode
    except subprocess.TimeoutExpired:
        code = 124
    return {
        "status": "PASS" if code == 0 else "FAIL", "exit_code": code,
        "duration_sec": round(time.monotonic() - start, 3), "command": args,
        "log": str(log), "install": str(root / "install"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", default="")
    parser.add_argument("--humble-tools", action="store_true")
    parser.add_argument("--modules", nargs="+", choices=["emotion", "voice", "vision", "action", "behavior"],
                        default=["emotion", "voice", "vision", "action", "behavior"])
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Invalid run-id")
    if verify_sources()["status"] != "PASS":
        raise SystemExit("Baseline changed")
    if args.attempt and not args.attempt.replace("-", "").isalnum():
        raise SystemExit("Invalid attempt label")
    report, work = ROOT / "reports" / args.run_id, ROOT / "work" / args.run_id
    if args.attempt:
        report = report / args.attempt
        report.mkdir(exist_ok=True)
    results = {"scope": "Unmodified snapshot ROS packages; no hardware execution", "builds": {}}
    if not Path("/opt/ros/humble/setup.bash").exists():
        results.update(status="BLOCKED", reason="Humble installation missing")
        (report / "ros-checks.json").write_text(json.dumps(results, indent=2) + "\n")
        raise SystemExit(1)
    env = ros_env()
    inventory = subprocess.run([
        str(ROOT / ".venv/bin/python"), "-B", "-c",
        "import json;from ament_index_python.packages import get_packages_with_prefixes;"
        "print(json.dumps(get_packages_with_prefixes(),sort_keys=True))",
    ], env=env, text=True, capture_output=True, check=True)
    installed = json.loads(inventory.stdout)
    local = json.loads((ROOT / "baseline/interfaces.json").read_text())["packages"]
    local_names = {p["name"] for p in local}
    results["discovery"] = {
        "ros_distro": env.get("ROS_DISTRO"), "installed_packages": installed,
        "local_packages": sorted(local_names),
        "external_interface_availability": {
            name: installed.get(name) for name in
            ("marsdog_interfaces", "nav2_msgs", "unitree_api", "unitree_go", "transfer_interfaces")
        },
    }
    prefixes = []
    tool_env = ROOT / "ros-tools/.venv" if args.humble_tools else None
    for module in args.modules:
        label = module + ("-" + args.attempt if args.attempt else "")
        check = run_build(work / "sources" / module, label, work, report, ros_env(prefixes), tool_env)
        results["builds"][module] = check
        if check["status"] == "PASS":
            prefixes.append(Path(check["install"]))
        print("ROS", module, check["status"], flush=True)
        (report / "ros-checks.json").write_text(json.dumps(results, indent=2) + "\n")
    # This is explicitly an IDL diagnostic, NOT a substitute for Action's full build.
    diagnostic = work / "idl-only-action"
    diagnostic.mkdir(exist_ok=True)
    (diagnostic / "action").mkdir(exist_ok=True)
    idl = (work / "sources/action/action/ExecuteBehavior.action").read_bytes()
    (diagnostic / "action/ExecuteBehavior.action").write_bytes(idl)
    (diagnostic / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.8)\nproject(marsdog_action_executor)\n"
        "find_package(ament_cmake REQUIRED)\nfind_package(rosidl_default_generators REQUIRED)\n"
        'rosidl_generate_interfaces(${PROJECT_NAME} "action/ExecuteBehavior.action")\n'
        "ament_package()\n"
    )
    (diagnostic / "package.xml").write_text(
        '<package format="3"><name>marsdog_action_executor</name><version>0.0.0</version>'
        '<description>P1 diagnostic ONLY: unchanged historical IDL; no production executor.</description>'
        '<maintainer email="noreply@marsdog.local">P1 test harness</maintainer><license>MIT</license>'
        '<buildtool_depend>ament_cmake</buildtool_depend>'
        '<buildtool_depend>rosidl_default_generators</buildtool_depend>'
        '<exec_depend>rosidl_default_runtime</exec_depend>'
        '<member_of_group>rosidl_interface_packages</member_of_group>'
        '<export><build_type>ament_cmake</build_type></export></package>\n'
    )
    results["idl_only_diagnostic"] = run_build(
        diagnostic, "idl-only-action" + ("-" + args.attempt if args.attempt else ""),
        work, report, ros_env(), tool_env
    )
    results["idl_only_diagnostic"]["scope"] = (
        "Real rosidl generation of unchanged ExecuteBehavior.action in isolated test prefix; "
        "does NOT validate the production Action build or its dependencies."
    )
    results["original_sources"] = verify_sources()
    results["status"] = "PASS" if all(
        b["status"] == "PASS" for b in results["builds"].values()
    ) else "FAIL"
    (report / "ros-checks.json").write_text(json.dumps(results, indent=2) + "\n")
    raise SystemExit(0 if results["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
