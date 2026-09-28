"""Build/install Emotion with the Humble tool lock; run only remapped Needs smoke."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--ros-setup", type=Path, default=Path("/opt/ros/humble/setup.bash"))
    parser.add_argument("--python", default="/usr/bin/python3.10")
    args = parser.parse_args()
    if not args.ros_setup.is_file():
        raise SystemExit("BLOCKED: ROS Humble is not installed; this tool does not install ROS")
    out = ROOT / "out/emotion-ros"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps({"status": "RUNNING"}) + "\n")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UV_PYTHON_DOWNLOADS="never")
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache/uv"))
    for name in list(env):
        if name.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "CYCLONEDDS_")):
            env.pop(name)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE"):
        env.pop(name, None)
    commands = []

    def run(command, environment=env, timeout=600, record_stdout=True):
        commands.append(command)
        process = subprocess.run(command, cwd=out, env=environment, capture_output=True,
                                 text=True, timeout=timeout)
        with (out / "commands.log").open("a") as stream:
            stream.write(json.dumps(command) + "\n" +
                         (process.stdout if record_stdout else "[environment output omitted]\n") +
                         process.stderr)
        if process.returncode:
            raise RuntimeError(f"Command failed ({process.returncode}); see {out / 'commands.log'}")
        return process.stdout

    (out / "commands.log").write_text("")
    project = ROOT / "platform/humble-build-tools"
    run([args.uv, "sync", "--project", str(project), "--locked", "--python", args.python])
    python = project / ".venv/bin/python"

    def with_ros(scripts):
        shell = "set -e\n" + "\n".join("source " + shlex.quote(str(p)) for p in scripts)
        shell += "\n" + shlex.quote(str(python)) + " -B -c " + shlex.quote(
            "import os,json;print(json.dumps(dict(os.environ)))"
        )
        return json.loads(run(["bash", "--noprofile", "--norc", "-c", shell],
                              record_stdout=False).splitlines()[-1])

    ros = with_ros([args.ros_setup])
    ros.update(COLCON_EXTENSION_BLOCKLIST="colcon_core.event_handler.desktop_notification",
               CMAKE_BUILD_PARALLEL_LEVEL="2")
    install = out / "install"
    run([
        str(project / ".venv/bin/colcon"), "--log-base", str(out / "log"), "build",
        "--base-paths", str(ROOT / "modules/emotion"), "--build-base", str(out / "build"),
        "--install-base", str(install), "--executor", "sequential",
        "--event-handlers", "console_direct+", "--cmake-args", "-DBUILD_TESTING=OFF",
        "-DPython3_EXECUTABLE=" + str(python), "-DPYTHON_EXECUTABLE=" + str(python),
    ], ros)
    probe_env = with_ros([args.ros_setup, install / "local_setup.bash"])
    probe_env.update(ROS_DOMAIN_ID=str(180 + secrets.randbelow(30)), ROS_LOCALHOST_ONLY="1",
                     RMW_IMPLEMENTATION="rmw_fastrtps_cpp", ROS_LOG_DIR=str(out / "ros-logs"))
    try:
        run([str(python), "-B", str(ROOT / "tools/ros_emotion_probe.py"),
             "--install", str(install), "--output", str(out / "probe.json")], probe_env, 45)
        result = {"status": "PASS", "scope": "Emotion only; real remapped ROS node; no hardware",
                  "ros_domain_id": probe_env["ROS_DOMAIN_ID"], "commands": commands,
                  "probe": json.loads((out / "probe.json").read_text())}
    except Exception as error:
        result = {"status": "FAIL", "error": str(error), "commands": commands}
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        raise
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        out = ROOT / "out/emotion-ros"
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps({
            "status": "FAIL", "error": str(error), "log": str(out / "commands.log"),
        }, indent=2) + "\n")
        raise
