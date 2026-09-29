"""Run Voice's pure subset or complete Humble-dependent unit suite, without devices."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ROS_TESTS = ("test_command_lexicon.py", "test_logging_contract.py",
             "test_session_recovery.py", "test_speaker_node.py", "test_cpu_intent_lifecycle.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("pure", "humble"), required=True)
    parser.add_argument("--source", type=Path, default=ROOT / "modules/voice")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    output = (args.output or ROOT / ("out/voice-tests-" + args.mode)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "result.json"
    result_path.write_text('{"status":"RUNNING"}\n')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for name in list(env):
        if name.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "FASTDDS_", "CYCLONEDDS_")):
            env.pop(name)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE"):
        env.pop(name, None)
    python = source / ".venv/bin/python"
    try:
        if args.mode == "humble":
            assert Path("/opt/ros/humble/setup.bash").is_file(), "Humble is required"
            shell = "set -e\nsource /opt/ros/humble/setup.bash\n"
            shell += shlex.quote(str(python)) + " -B -c " + shlex.quote(
                "import json,os;print(json.dumps(dict(os.environ)))")
            result = subprocess.run(["bash", "--noprofile", "--norc", "-c", shell],
                                    env=env, capture_output=True, text=True, check=True, timeout=30)
            env = json.loads(result.stdout.splitlines()[-1])
            env.update(ROS_LOCALHOST_ONLY="1", ROS_DOMAIN_ID="209")
        junit = output / "junit.xml"
        command = [str(python), "-B", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
                   "--junitxml=" + str(junit)]
        if args.mode == "pure":
            command.extend("--ignore=tests/" + name for name in ROS_TESTS)
        with (output / "tests.log").open("w") as log:
            result = subprocess.run(command, cwd=source, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=300)
        suites = list(ET.parse(junit).getroot().iter("testsuite"))
        counts = {k: sum(int(s.get(k, 0)) for s in suites)
                  for k in ("tests", "failures", "errors", "skipped")}
        # Excluded files are explicit in the pure report; never count them as passes.
        passed = result.returncode == 0 and counts["tests"] > 0 and not any(
            counts[k] for k in ("failures", "errors", "skipped"))
        report = {"status": "PASS" if passed else "FAIL", "mode": args.mode,
                  "scope": "Existing unit tests; no actual microphone/models/ROS transport",
                  "excluded_files": list(ROS_TESTS) if args.mode == "pure" else [],
                  "source": str(source), "command": command, "counts": counts}
        result_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if passed else 1)
    except Exception as error:
        result_path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
