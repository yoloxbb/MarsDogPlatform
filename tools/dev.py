"""Shared developer commands; each module still owns its code, lock and environment."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from runtime_environment import ROOT, clean_environment

def modules():
    records = json.loads((ROOT / "platform/modules.json").read_text())["modules"]
    return {name: value for name, value in records.items() if "development" in value}

def setup_command(name, uv, python, ros=False, intent_cpu=False):
    record = modules()[name]
    command = [str(uv), "sync", "--project", str(ROOT / record["path"]),
               "--locked", "--python", str(python), *record["development"]["sync_args"]]
    if ros and name in ("emotion", "behavior"):
        command += ["--extra", "ros"]
    if intent_cpu:
        if name != "voice":
            raise ValueError("--intent-cpu applies only to voice")
        command += ["--extra", "intent-cpu"]
    return command

def test_command(name, output, ros=False):
    record = modules()[name]
    source = ROOT / record["path"]
    if name == "voice":
        return [sys.executable, "-B", str(ROOT / "tools/check_voice_tests.py"),
                "--mode", "humble" if ros else "pure", "--output", str(output)], ROOT
    if name == "vision":
        return [sys.executable, "-B", str(ROOT / "tools/check_vision_tests.py"),
                "--output", str(output)], ROOT
    return [str(source / ".venv/bin/python"), "-B", "-m", "pytest",
            *record["development"]["test_paths"], "-q", "-p", "no:cacheprovider",
            "--junitxml=" + str(output / "junit.xml")], source

def junit_result(path, returncode):
    root = ET.parse(path).getroot()
    counts = {key: sum(int(suite.get(key, 0)) for suite in root.iter("testsuite"))
              for key in ("tests", "failures", "errors", "skipped")}
    skips = [{"case": case.get("classname", "") + "." + case.get("name", ""),
              "reason": case.find("skipped").get("message", "")}
             for case in root.iter("testcase") if case.find("skipped") is not None]
    passed = (returncode == 0 and counts["tests"] > counts["skipped"]
              and counts["failures"] == 0 and counts["errors"] == 0)
    return {"status": ("PASS_WITH_EXPLICIT_LIMITS" if counts["skipped"] else "PASS")
            if passed else "FAIL", "counts": counts, "skips": skips}

def run(command, **kwargs):
    print("+ " + " ".join(map(str, command)), flush=True)
    return subprocess.run(command, **kwargs)

def check():
    env = clean_environment()
    commands = [
        [sys.executable, "-B", str(ROOT / "tools/check_architecture.py")],
        [sys.executable, "-B", "-m", "unittest", "discover",
         "-s", "integration/platform/tests", "-v"],
    ]
    results = [run(command, cwd=ROOT, env=env).returncode for command in commands]
    return int(any(results))

def test(name, output, ros):
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "result.json"
    report_path.write_text('{"status":"RUNNING"}\n')
    try:
        source = ROOT / modules()[name]["path"]
        if not (source / ".venv/bin/python").is_file():
            raise RuntimeError("Run tools/dev.py setup " + name + " first")
        if (ros or name == "vision") and not Path("/opt/ros/humble/setup.bash").is_file():
            raise RuntimeError("Full ROS unit tests need an existing Humble host")
        command, cwd = test_command(name, output, ros)
        env = clean_environment()
        env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", QT_QPA_PLATFORM="offscreen")
        # Full Voice/Vision runners scope ROS themselves. Other unit suites remain pure.
        with (output / "runner.log").open("w") as log:
            result = run(command, cwd=cwd, env=env, stdout=log,
                         stderr=subprocess.STDOUT, timeout=600)
        if name in ("voice", "vision"):
            report = json.loads(report_path.read_text())
        else:
            report = junit_result(output / "junit.xml", result.returncode)
            report.update(command=command, scope="Existing module unit suite, no hardware")
        report.update(module=name, returncode=result.returncode)
        passed = result.returncode == 0 and report["status"] in ("PASS", "PASS_WITH_EXPLICIT_LIMITS")
        if not passed:
            report["status"] = "FAIL"
            print((output / "runner.log").read_text()[-6000:])
    except Exception as error:
        report, passed = {"status": "FAIL", "module": name, "error": str(error)}, False
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info", help="Show module paths, owners and test scope")
    commands.add_parser("check", help="Stdlib architecture and platform regression checks")
    setup = commands.add_parser("setup", help="Sync exactly one locked module environment")
    setup.add_argument("module", choices=modules())
    setup.add_argument("--uv", type=Path)
    setup.add_argument("--python", type=Path, default=Path("/usr/bin/python3.10"))
    setup.add_argument("--ros", action="store_true", help="Add Emotion/BT ROS NumPy extra")
    setup.add_argument("--intent-cpu", action="store_true", help="Keep/install optional Voice Qwen CPU extra")
    tests = commands.add_parser("test", help="Run module tests, retain counts and skip reasons")
    tests.add_argument("module", choices=modules())
    tests.add_argument("--ros", action="store_true", help="Use full Voice Humble suite; Vision always needs Humble")
    tests.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "info":
        print(json.dumps(modules(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "check":
        return check()
    if args.command == "test":
        output = (args.output or ROOT / "out/dev" / (args.module + ("-ros" if args.ros else ""))).resolve()
        return test(args.module, output, args.ros)
    uv = args.uv or (ROOT / ".tools/uv" if (ROOT / ".tools/uv").is_file()
                     else Path(shutil.which("uv") or "/missing/uv"))
    if not uv.is_file():
        parser.error("uv missing: use tools/bootstrap_uv.py or --uv /absolute/path/to/uv")
    if not args.python.is_file():
        parser.error("Python 3.10 is required; specify --python")
    try:
        command = setup_command(args.module, uv.resolve(), args.python, args.ros, args.intent_cpu)
    except ValueError as error:
        parser.error(str(error))
    env = clean_environment()
    env["UV_PYTHON_DOWNLOADS"] = "never"
    return run(command, cwd=ROOT, env=env).returncode

if __name__ == "__main__":
    sys.exit(main())
