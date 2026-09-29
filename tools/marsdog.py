#!/usr/bin/env python3
"""One entry point for the explicitly simulated Lite3 CPU development profile."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import platform
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from runtime_environment import ROOT, clean_environment, ros_environment

LOCAL = ROOT / "out/local"
INSTALL = LOCAL / "ros/install"
BUILD_TOOLS = ROOT / "platform/humble-build-tools/.venv/bin"
MODULES = ("emotion", "behavior", "action", "voice", "vision")
NATIVE = tuple(json.loads((ROOT / "platform/ros-build.json").read_text())["local_native_packages"])
ENTRY = {
    "emotion": "marsdog_ros2.emotion_engine_node",
    "behavior": "marsdog_behavior.ros_node",
    "action": "marsdog_action_executor.ros_node",
    "voice": "marsdog_voice_interaction.nodes.voice_interaction_node",
    "vision": "marsdog_vision_interaction.nodes.vision_interaction_node",
}
PROFILE = json.loads((ROOT / "config/profiles/lite3-local-cpu.json").read_text())


def run(command, env=None, **kwargs):
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=ROOT, env=env, check=True, **kwargs)


def prepare(args):
    if not Path("/opt/ros/humble/setup.bash").is_file():
        raise RuntimeError("Ubuntu 22.04 / Python 3.10 / ROS Humble must already be available")
    uv = shutil.which(args.uv)
    if uv is None:
        raise RuntimeError("Provide an installed uv executable with --uv; no automatic tool installation")
    env = clean_environment()
    env["UV_PYTHON_DOWNLOADS"] = "never"
    for module in ("platform/humble-build-tools", *("modules/" + n for n in MODULES)):
        command = [uv, "sync", "--project", ROOT / module, "--locked",
                   "--python", "/usr/bin/python3.10"]
        if module.endswith(("/voice", "/vision")):
            command += ["--no-install-project"]
        elif module.startswith("modules/"):
            command += ["--no-editable"]
        if module.endswith(("/emotion", "/behavior")):
            command += ["--extra", "ros"]
        if module.endswith(("/voice", "/vision")):
            command += ["--extra", "dev"]
        if module.endswith("/voice") and getattr(args, "voice_intent_cpu", False):
            command += ["--extra", "intent-cpu"]
        if module.endswith("/vision"):
            command += ["--extra", "models"]
        run(command, env=env)
    run([sys.executable, "-B", ROOT / "tools/prepare_ros_deps.py"], env=env)
    # The main CPU build needs the pinned UWB IDL/stub, not the ARM vendor library.
    run([sys.executable, "-B", ROOT / "tools/materialize_vendors.py",
         "--archive-dir", args.archive_dir, "--only", "uwb"], env=env)



def source_fingerprint():
    # Git supplies the relevant source inventory, including new untracked files,
    # without traversing .venv/build/cache. Vendor bytes are verified at prepare.
    names = subprocess.check_output([
        "git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
        "modules", "interfaces/ros2", "robotics/ros2/src", "third_party/*.json",
        "platform/humble-build-tools"], cwd=ROOT).decode().split("\0")
    digest = hashlib.sha256()
    for name in sorted(set(filter(None, names))):
        path = ROOT / name
        digest.update(name.encode() + b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def build(_args):
    LOCAL.mkdir(parents=True, exist_ok=True)
    env = ros_environment()
    env.update(CMAKE_BUILD_PARALLEL_LEVEL="2",
               COLCON_EXTENSION_BLOCKLIST="colcon_core.event_handler.desktop_notification")
    paths = [ROOT / "modules" / m for m in MODULES]
    paths += [ROOT / "interfaces/ros2/marsdog_interfaces",
              ROOT / "robotics/ros2/src/waypoint_nav", ROOT / ".external/uwb"]
    paths += [ROOT / "robotics/ros2/src" / n for n in NATIVE]
    assert all(p.is_dir() for p in paths), "Prepare pinned sources first"
    with (LOCAL / "build.log").open("w") as log:
        run([BUILD_TOOLS / "colcon", "--log-base", LOCAL / "ros/log", "build",
             "--base-paths", *paths, "--build-base", LOCAL / "ros/build",
             "--install-base", INSTALL, "--executor", "sequential",
             "--event-handlers", "console_direct+", "--cmake-args",
             "-DBUILD_TESTING=OFF", "-DBUILD_UWB_VENDOR_DRIVER=OFF",
             "-DPython3_EXECUTABLE=" + str(BUILD_TOOLS / "python"),
             "-DPYTHON_EXECUTABLE=" + str(BUILD_TOOLS / "python")],
            env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    receipt = {"source_sha256": source_fingerprint(), "python": sys.version,
               "platform": platform.platform(), "ros": "humble", "install": str(INSTALL),
               "source_paths": [str(p.relative_to(ROOT)) for p in paths],
               "options": {"BUILD_TESTING": "OFF", "BUILD_UWB_VENDOR_DRIVER": "OFF"}}
    (LOCAL / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("Build complete:", LOCAL / "build.log")


def doctor(_args):
    receipt = LOCAL / "build-receipt.json"
    if not receipt.is_file() or json.loads(receipt.read_text())["source_sha256"] != source_fingerprint():
        raise RuntimeError("Install is missing or stale: run python3 tools/marsdog.py build")
    env = ros_environment(INSTALL, PROFILE["ros_domain_id"])
    records = {}
    for module, entry in ENTRY.items():
        python = ROOT / "modules" / module / ".venv/bin/python"
        code = ("import importlib,json,sys;from pathlib import Path;"
                "m=importlib.import_module(" + repr(entry) + ");"
                "assert callable(m.main);"
                "assert Path(m.__file__).resolve().is_relative_to(Path(" + repr(str(INSTALL)) + "));"
                "from marsdog_interfaces.action import ExecuteBehavior;"
                "from marsdog_voice_interaction.srv import VoiceTask;"
                "from marsdog_vision_interaction.srv import VisionTask;"
                "from rclpy.node import Node;import rclpy;print(json.dumps({'python':sys.executable,'module':m.__file__}))")
        result = subprocess.run([str(python), "-B", "-c", code], cwd=LOCAL, env=env,
                                text=True, capture_output=True, timeout=45)
        if result.returncode:
            raise RuntimeError(module + " installed import failed: " + result.stderr[-4000:])
        records[module] = json.loads(result.stdout.splitlines()[-1])
    data = {"status": "PASS", "profile": PROFILE, "installed_modules": records,
            "install": str(INSTALL), "scope": "Installed imports and generated public IDL; runtime checked by smoke"}
    (LOCAL / "doctor.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))
    return env


def command(module, entry, params=None):
    python = BUILD_TOOLS / "python" if module is None else ROOT / "modules" / module / ".venv/bin/python"
    cmd = [str(python), "-B", "-c", "from " + entry + " import main; main()"]
    if params:
        cmd += ["--ros-args"]
        for key, value in params.items():
            value = str(value).lower() if isinstance(value, bool) else str(value)
            cmd += ["-p", key + ":=" + value]
    return cmd


def process_specs(directory):
    return [
        ("inputs", [str(BUILD_TOOLS / "python"), "-B", str(ROOT / "tools/local_inputs.py")]),
        ("time", command("emotion", "marsdog_ros2.time_controller_node",
                         {"time_scale": 1, "virtual_start_time": "10:00"})),
        ("personality", command("emotion", "marsdog_ros2.personality_node")),
        ("needs", command("emotion", "marsdog_ros2.internal_need_node")),
        ("emotion", command("emotion", ENTRY["emotion"])),
        ("waypoint", command(None, "waypoint_nav.waypoint_nav_dispatcher",
                             {"waypoints_file": directory / "waypoints.yaml",
                              "task_store_file": directory / "tasks.sqlite3"})),
        ("action", command("action", ENTRY["action"],
                           {"config_dir": directory / "action-config", "chassis_type": "lite3",
                            "lite3_enabled": True, "go2_enabled": False, "lite3_simulated_io": True,
                            "lite3_allow_proxies": True, "lite3_allow_unverified": False,
                            "uwb_follow_enabled": False, "wake_orientation_enabled": False,
                            "attention_tracking_enabled": False, "target_approach_enabled": False,
                            "navigation_enabled": True})),
        ("vision", command("vision", ENTRY["vision"],
                           {"config_path": directory / "vision.yaml", "log_dir": directory / "vision-log"})),
        ("behavior", command("behavior", ENTRY["behavior"])),
        # Voice last: its original mock provider emits wakeup then GO_HOME.
        ("voice", command("voice", ENTRY["voice"], {"config_path": directory / "voice.yaml"})),
    ]


def supervise(args, *, profile=PROFILE, local=LOCAL, specs=process_specs,
              probe_script="local_smoke.py", env_transform=None, shutdown_hook=None):
    env = doctor(args)
    if env_transform is not None:
        env = env_transform(env)
    local.mkdir(parents=True, exist_ok=True)
    directory = local / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + str(os.getpid()))
    directory.mkdir(parents=True)
    env.update(MARSDOG_LOCAL_SIMULATION="1", ROS_LOG_DIR=str(directory / "ros-log"),
               MARSDOG_VISION_PROJECT_DIR=str(INSTALL / "marsdog_vision_interaction/share/marsdog_vision_interaction"),
               MARSDOG_VISION_MODEL_DIR=str(directory / "absent-models"),
               MARSDOG_VISION_DATA_DIR=str(directory / "vision-data"))
    run([BUILD_TOOLS / "python", "-B", ROOT / "tools/prepare_local_configs.py",
         "--run", directory, "--install", INSTALL, "--profile", profile["name"]], env=env)
    lock = (LOCAL / (profile["name"] + ".lock")).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("This local profile is already running")
    children, streams = [], []
    stopping = False
    def stop_signal(_signum, _frame):
        nonlocal stopping
        stopping = True
    old_handlers = {s: signal.signal(s, stop_signal) for s in (signal.SIGINT, signal.SIGTERM)}
    data = {"status": "RUNNING", "profile": profile, "run_directory": str(directory)}
    error = None
    probe = None
    try:
        for name, cmd in specs(directory):
            if stopping:
                break
            stream = (directory / (name + ".log")).open("w")
            streams.append(stream)
            child_env = dict(env)
            child_env["MARSDOG_PYTHON"] = cmd[0]
            proc = subprocess.Popen(cmd, cwd=directory, env=child_env, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            children.append((name, proc, cmd))
            (directory / "processes.json").write_text(json.dumps([
                {"name": n, "pid": p.pid, "command": c} for n, p, c in children], indent=2) + "\n")
            print("Started", name, "PID", proc.pid, flush=True)
            time.sleep(0.25)
        if args.command == "smoke" and not stopping:
            stream = (directory / "probe.log").open("w")
            streams.append(stream)
            cmd = [str(BUILD_TOOLS / "python"), "-B", str(ROOT / "tools" / probe_script),
                   "--output", str(directory / "smoke.json")]
            probe = subprocess.Popen(cmd, cwd=directory, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            children.append(("probe", probe, cmd))
        started = time.monotonic()
        print("LOCAL SIMULATION profile:", profile["name"], "Logs:", directory, flush=True)
        while not stopping:
            for name, proc, _ in children:
                code = proc.poll()
                if name == "probe" and code is not None:
                    if code != 0:
                        raise RuntimeError("Integrated smoke failed; see " + str(directory / "probe.log"))
                    stopping = True
                elif code is not None:
                    raise RuntimeError(name + " exited unexpectedly (" + str(code) + "); see " + str(directory / (name + ".log")))
            if args.duration and time.monotonic() - started >= args.duration:
                stopping = True
            if args.command == "smoke" and time.monotonic() - started > 100:
                raise RuntimeError("Integrated smoke exceeded its deadline")
            time.sleep(0.1)
        if args.command == "smoke":
            if probe is None or probe.poll() != 0:
                raise RuntimeError("Smoke interrupted before completion")
            data["smoke"] = json.loads((directory / "smoke.json").read_text())
        data["status"] = "PASS"
    except BaseException as exc:
        error = exc
        data.update(status="FAIL", error=str(exc))
    finally:
        # Signal only process groups created by this supervisor, never pkill/system nodes.
        def signal_group(proc, sig):
            proc.poll()  # Reap the leader; its descendants may still be alive.
            try:
                os.killpg(proc.pid, sig)
                return True
            except ProcessLookupError:
                return False
        if shutdown_hook is not None:
            try:
                data["lifecycle_shutdown"] = shutdown_hook(env, directory, children)
            except BaseException as exc:
                data["lifecycle_shutdown"] = {"status": "FAIL", "error": str(exc)}
                if error is None:
                    error = exc
                    data.update(status="FAIL", error=str(exc))
        for _, proc, _ in children:
            signal_group(proc, signal.SIGINT)
        deadline = time.monotonic() + 8.0
        while any(signal_group(p, 0) for _, p, _ in children) and time.monotonic() < deadline:
            time.sleep(0.1)
        forced = []
        for name, proc, _ in children:
            if signal_group(proc, 0):
                forced.append(name)
                signal_group(proc, signal.SIGKILL)
            proc.wait(timeout=5)
        data["processes"] = [{"name": n, "pid": p.pid, "returncode": p.returncode, "command": c}
                             for n, p, c in children]
        data["forced_shutdowns"] = forced
        bad_exits = [n for n, p, _ in children if p.returncode != 0]
        if bad_exits and error is None:
            error = RuntimeError("Nonzero shutdown exits: " + ", ".join(bad_exits))
            data.update(status="FAIL", error=str(error))
        if forced:
            data.update(status="FAIL", error="Processes required forced shutdown: " + ", ".join(forced))
            error = error or RuntimeError(data["error"])
        for stream in streams:
            stream.close()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        (directory / "result.json").write_text(json.dumps(data, indent=2) + "\n")
        (local / "latest-run.json").write_text(json.dumps(data, indent=2) + "\n")
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    print(json.dumps({"status": data["status"], "report": str(directory / "result.json")}))
    if error:
        raise error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "build", "doctor", "up", "smoke", "replay", "models", "intent-replay"))
    parser.add_argument("--profile", choices=("lite3-local-cpu", "lite3-nav2-cpu"), default="lite3-local-cpu")
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--archive-dir", type=Path, default=ROOT.parent / "migration/archives")
    parser.add_argument("--duration", type=float, default=0, help="Bound up duration in seconds; zero runs until Ctrl-C")
    parser.add_argument("--manifest", type=Path, help="Annotated CPU replay asset manifest")
    parser.add_argument("--output", type=Path, help="CPU replay evidence directory")
    parser.add_argument("--check-only", action="store_true", help="Validate replay assets without inference")
    parser.add_argument("--model-archive", type=Path, help="Supplied models.zip for pinned CPU assets")
    parser.add_argument("--download", action="store_true", help="Fetch missing pinned CPU model assets")
    parser.add_argument("--intent-archive", type=Path, help="User-supplied Qwen CPU model ZIP")
    parser.add_argument("--voice-intent-cpu", action="store_true", help="Prepare optional CPU intent dependencies for Voice")
    args = parser.parse_args()
    if args.command == "intent-replay":
        if args.manifest is None:
            parser.error("intent-replay requires --manifest")
        from check_cpu_intent import main as intent_main
        replay_args = ["--manifest", str(args.manifest)]
        if args.output is not None:
            replay_args += ["--output", str(args.output)]
        raise SystemExit(intent_main(replay_args))
    if args.command == "models":
        if args.intent_archive is not None:
            if args.model_archive is not None:
                parser.error("Prepare one archive at a time")
            from prepare_qwen_intent import main as qwen_main
            model_args = ["--archive", str(args.intent_archive)]
            if args.output is not None:
                model_args += ["--output", str(args.output)]
            raise SystemExit(qwen_main(model_args))
        if args.model_archive is None:
            parser.error("models requires --model-archive")
        from prepare_cpu_models import main as models_main
        model_args = ["--archive", str(args.model_archive)]
        if args.output is not None:
            model_args += ["--output", str(args.output)]
        if args.download:
            model_args.append("--download")
        raise SystemExit(models_main(model_args))
    if args.command == "replay":
        if args.manifest is None:
            parser.error("replay requires --manifest")
        from check_perception_replay import main as replay_main
        replay_args = ["--manifest", str(args.manifest)]
        if args.output is not None:
            replay_args += ["--output", str(args.output)]
        if args.check_only:
            replay_args.append("--check-only")
        raise SystemExit(replay_main(replay_args))
    if args.duration < 0:
        parser.error("--duration must be nonnegative")
    if args.profile == "lite3-nav2-cpu":
        from nav2_profile import main as nav2_main
        return nav2_main(args, sys.modules[__name__])
    if args.command in ("up", "smoke"):
        supervise(args)
    else:
        {"prepare": prepare, "build": build, "doctor": doctor}[args.command](args)


if __name__ == "__main__":
    main()
