"""Run the original Vision unit suite on an existing Humble host (no devices)."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "modules/vision")
    parser.add_argument("--output", type=Path, default=ROOT / "out/vision-tests")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / "result.json"
    report.write_text('{"status":"RUNNING"}\n')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", CUDA_VISIBLE_DEVICES="")
    for key in list(env):
        if key.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "FASTDDS_", "CYCLONEDDS_")):
            env.pop(key)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE"):
        env.pop(key, None)
    try:
        assert Path("/opt/ros/humble/setup.bash").is_file(), "Humble required; do not fake rclpy"
        python = source / ".venv/bin/python"
        shell = "set -e\nsource /opt/ros/humble/setup.bash\n"
        shell += shlex.quote(str(python)) + " -B -c " + shlex.quote(
            "import json,os;print(json.dumps(dict(os.environ)))")
        result = subprocess.run(["bash", "--noprofile", "--norc", "-c", shell],
                                env=env, text=True, capture_output=True, check=True, timeout=30)
        env = json.loads(result.stdout.splitlines()[-1])
        env.update(ROS_LOCALHOST_ONLY="1", ROS_DOMAIN_ID="208")
        junit = output / "junit.xml"
        command = [str(python), "-B", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
                   "--junitxml=" + str(junit)]
        with (output / "tests.log").open("w") as log:
            result = subprocess.run(command, cwd=source, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=300)
        root = ET.parse(junit).getroot()
        counts = {k: sum(int(s.get(k, 0)) for s in root.iter("testsuite"))
                  for k in ("tests", "failures", "errors", "skipped")}
        skips = [{"case": c.get("name"), "reason": c.find("skipped").get("message", "")}
                 for c in root.iter("testcase") if c.find("skipped") is not None]
        allowed = all(s["case"].startswith("test_rga_image_parity_when_helper_is_explicitly_requested[")
                      and s["reason"] == "set MARSDOG_HAND_RGA_TEST_LIBRARY for an RGA parity smoke"
                      for s in skips) and len(skips) <= 3
        passed = result.returncode == 0 and counts["tests"] > counts["skipped"] and allowed
        data = {"status": "PASS_WITH_EXPLICIT_LIMITS" if passed and skips else "PASS" if passed else "FAIL",
                "counts": counts, "skips": skips, "source": str(source), "command": command,
                "scope": "Original unit suite on CPU; no camera/model/NPU hardware validation"}
        report.write_text(json.dumps(data, indent=2) + "\n")
        print(json.dumps(data, indent=2))
        raise SystemExit(0 if passed else 1)
    except Exception as error:
        report.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise

if __name__ == "__main__":
    main()
