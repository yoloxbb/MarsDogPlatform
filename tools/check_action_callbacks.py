"""Actual Action ROS callbacks with existing fake collaborators, never a hardware node."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from dev import junit_result
from runtime_environment import ROOT, ros_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "out/action-callbacks")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING"}
    (output / "result.json").write_text(json.dumps(report) + "\n")
    try:
        env = ros_environment(ROOT / "out/local/ros/install", domain=212)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        command = [str(ROOT / "modules/action/.venv/bin/python"), "-B", "-m", "pytest",
                   "tests/test_long_goal_arbitration.py", "tests/test_long_goal_runtime.py",
                   "tests/test_ros_goal_params_boundary.py", "-q", "-p", "no:cacheprovider",
                   "--junitxml=" + str(output / "junit.xml")]
        with (output / "tests.log").open("w") as log:
            result = subprocess.run(command, cwd=ROOT / "modules/action", env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=180)
        report = junit_result(output / "junit.xml", result.returncode)
        # A ROS import failure cannot silently turn these cases into skipped passes.
        if report["counts"]["skipped"]:
            report["status"] = "FAIL"
        report.update(command=command, scope="Humble types + real callbacks; fake collaborators; no node/hardware")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        report = {"status": "FAIL", "error": str(error)}
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
