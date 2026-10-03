"""Optional real Nav2 composition; all business modules retain their public APIs."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from runtime_environment import ROOT, local_transport
from prepare_extended_ros import environment, BASE, VIEW, LOCK, sha
from check_extended_ros_build import source_sha256

PROFILE = json.loads((ROOT / "config/profiles/lite3-nav2-cpu.json").read_text())

def nav_environment(env):
    env = environment(env)
    own = BASE / "install/behavior_ext_plugins"
    for key, suffix in (("AMENT_PREFIX_PATH", ""), ("LD_LIBRARY_PATH", "lib")):
        env[key] = str(own / suffix) + ":" + env.get(key, "")
    return local_transport(env, PROFILE["ros_domain_id"])

def specs(directory, base_specs, python, navigation_only=False):
    nodes = [
        ("nav_inputs", [str(python), "-B", str(ROOT / "tools/nav2_simulated_inputs.py")]),
    ]
    for package, executable in [
        ("nav2_controller", "controller_server"), ("nav2_planner", "planner_server"),
        ("nav2_behaviors", "behavior_server"), ("nav2_bt_navigator", "bt_navigator"),
        ("nav2_lifecycle_manager", "lifecycle_manager"),
    ]:
        nodes.append((executable, [str(VIEW / "opt/ros/humble/lib" / package / executable),
            "--ros-args", "--params-file", str(directory / "nav2.yaml"),
            "-r", "cmd_vel:=/development/nav2/cmd_vel"]))
    original = [(n, c) for n, c in base_specs(directory) if n != "inputs"]  # Keep auxiliary observers.
    if navigation_only:
        original = [(n, c) for n, c in original if n == "waypoint"]
    return nodes + original

def check():
    receipt = BASE / "nav2-plugin-build.json"
    if not receipt.is_file() or json.loads(receipt.read_text())["status"] != "PASS":
        raise RuntimeError("Build the optional Nav2 plugin first")
    data = json.loads(receipt.read_text())
    if (data.get("source_sha256") != source_sha256([ROOT / "robotics/ros2/src/behavior_ext_plugins"])
            or data.get("dependency_lock_sha256") != sha(LOCK)):
        raise RuntimeError("Optional Nav2 install is stale; rebuild lite3-nav2-cpu")
    for package, executable in [
        ("nav2_controller", "controller_server"), ("nav2_planner", "planner_server"),
        ("nav2_behaviors", "behavior_server"), ("nav2_bt_navigator", "bt_navigator"),
        ("nav2_lifecycle_manager", "lifecycle_manager")]:
        if not (VIEW / "opt/ros/humble/lib" / package / executable).is_file():
            raise RuntimeError("Missing optional Nav2 executable: " + executable)


def shutdown(env, directory, children):
    # Stop new requests and release application goals before finalizing Nav2.
    for names, timeout in ((("voice", "behavior"), 3.0), (("action",), 8.0)):
        group = [p for n,p,_ in children if n in names]
        for proc in group:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + timeout
        while any(p.poll() is None for p in group) and time.monotonic() < deadline:
            time.sleep(0.05)
        if any(p.poll() is None for p in group):
            raise RuntimeError("Application shutdown did not finish before Nav2 finalization: " + str(names))
    report = directory / "nav2-shutdown.json"
    with (directory / "nav2-shutdown.log").open("w") as log:
        subprocess.run([str(ROOT / "platform/humble-build-tools/.venv/bin/python"),
                        "-B", str(ROOT / "tools/nav2_shutdown.py"), str(report)],
                       env=env, cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                       timeout=10, check=True, start_new_session=True)
    return json.loads(report.read_text())

def main(args, driver):
    if args.command == "prepare":
        driver.prepare(args)
        driver.run(["/usr/bin/python3", "-B", ROOT / "tools/prepare_extended_ros.py"])
    elif args.command == "build":
        driver.build(args)
        driver.run(["/usr/bin/python3", "-B", ROOT / "tools/check_extended_ros_build.py", "nav2-plugin"])
    else:
        check()
        if args.command == "doctor":
            nav_environment(driver.doctor(args))
            print("Optional real Nav2 profile ready (runtime is verified by smoke)")
        else:
            driver.supervise(args, profile=PROFILE, local=ROOT / "out/nav2-local",
                              specs=lambda directory: specs(directory, driver.process_specs, driver.BUILD_TOOLS / "python"),
                              probe_script="nav2_smoke.py", env_transform=nav_environment,
                              shutdown_hook=shutdown)
