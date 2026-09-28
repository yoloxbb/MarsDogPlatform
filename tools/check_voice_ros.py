"""Build Voice with separate Humble tools and exercise installed test-only endpoints."""
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
    parser.add_argument("--source", type=Path, default=ROOT / "modules/voice")
    parser.add_argument("--output", type=Path, default=ROOT / "out/voice-ros")
    parser.add_argument("--runtime-python", type=Path)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.output.resolve()
    runtime = args.runtime_python or source / ".venv/bin/python"
    # Preserve the venv invocation path, not its system-Python symlink target.
    runtime = runtime.absolute()
    assert runtime.is_file(), "Prepare locked Voice runtime first"
    setup = Path("/opt/ros/humble/setup.bash")
    assert setup.is_file(), "BLOCKED: Humble is required; this tool does not install ROS"
    out.mkdir(parents=True, exist_ok=True)
    result_file = out / "result.json"
    result_file.write_text('{"status":"RUNNING"}\n')
    log = out / "commands.log"
    log.write_text("")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UV_PYTHON_DOWNLOADS="never")
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache/uv"))
    for name in list(env):
        if name.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "CYCLONEDDS_", "FASTDDS_")):
            env.pop(name)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE", "UV_PROJECT_ENVIRONMENT"):
        env.pop(name, None)
    commands = []
    try:
        def run(command, environment=env, timeout=600, hidden=False):
            commands.append(command)
            process = subprocess.run(command, cwd=out, env=environment, capture_output=True,
                                     text=True, timeout=timeout)
            with log.open("a") as stream:
                stream.write(json.dumps(command) + "\n" +
                             ("[environment omitted]\n" if hidden else process.stdout) + process.stderr)
            if process.returncode:
                raise RuntimeError(f"Command failed ({process.returncode}); see {log}")
            return process.stdout

        tools = ROOT / "platform/humble-build-tools"
        run([args.uv, "sync", "--project", str(tools), "--locked", "--python", "/usr/bin/python3.10"])
        python = tools / ".venv/bin/python"

        def with_ros(scripts):
            shell = "set -e\n" + "\n".join("source " + shlex.quote(str(p)) for p in scripts)
            shell += "\n" + shlex.quote(str(python)) + " -B -c " + shlex.quote(
                "import os,json;print(json.dumps(dict(os.environ)))")
            return json.loads(run(["bash", "--noprofile", "--norc", "-c", shell], hidden=True).splitlines()[-1])

        ros = with_ros([setup])
        ros.update(COLCON_EXTENSION_BLOCKLIST="colcon_core.event_handler.desktop_notification",
                   CMAKE_BUILD_PARALLEL_LEVEL="2")
        install = out / "install"
        run([str(tools / ".venv/bin/colcon"), "--log-base", str(out / "log"), "build",
             "--base-paths", str(source), "--build-base", str(out / "build"), "--install-base", str(install),
             "--executor", "sequential", "--event-handlers", "console_direct+",
             "--cmake-args", "-DBUILD_TESTING=OFF", "-DPython3_EXECUTABLE=" + str(python),
             "-DPYTHON_EXECUTABLE=" + str(python)], ros)
        probe_env = with_ros([setup, install / "local_setup.bash"])
        probe_env.update(ROS_DOMAIN_ID=str(180 + secrets.randbelow(40)), ROS_LOCALHOST_ONLY="1",
                         ROS_LOG_DIR=str(out / "ros-log"), MARSDOG_PYTHON=str(runtime),
                         RMW_IMPLEMENTATION="rmw_fastrtps_cpp",
                         FASTRTPS_DEFAULT_PROFILES_FILE=str(ROOT / "integration/migration/fixtures/fastdds-local-udp.xml"))
        run([str(runtime), "-B", str(ROOT / "tools/ros_voice_probe.py"), "--install", str(install),
             "--source", str(source), "--output", str(out / "probe.json")], probe_env, timeout=60)
        result = {"status": "PASS", "source": str(source), "commands": commands,
                  "scope": "Humble build and installed Voice mock transport, no hardware",
                  "probe": json.loads((out / "probe.json").read_text())}
        result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"status": "PASS", "result": str(result_file)}))
    except Exception as error:
        result_file.write_text(json.dumps({"status": "FAIL", "error": str(error),
                                          "commands": commands}, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
