"""P3a: actual ROS build and old/new installed BT adapter compatibility."""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import signal
import subprocess
import uuid
from baseline_lib import ROOT, WORKSPACE, verify_sources
from check_ros import ros_env, run_build


def main():
    assert verify_sources()["status"] == "PASS"
    work, report = ROOT / "work/p1-20260928", ROOT / "reports/p1-20260928"
    results = {"build": run_build(
        WORKSPACE / "marsdog-platform/modules/behavior", "p3-behavior", work, report,
        ros_env(), ROOT / "ros-tools/.venv",
    ), "probes": {}}
    if results["build"]["status"] == "PASS":
        for name, prefix in {
            "baseline": work / "ros-behavior-humble59/install",
            "migrated": Path(results["build"]["install"]),
        }.items():
            env = ros_env([work / "ros-idl-only-action/install", prefix])
            env.update(ROS_DOMAIN_ID=str(180 + secrets.randbelow(30)), ROS_LOCALHOST_ONLY="1",
                       RMW_IMPLEMENTATION="rmw_fastrtps_cpp", ROS_LOG_DIR=str(report / "p3-ros-logs"))
            endpoint = "/migration_behavior_" + uuid.uuid4().hex + "/execute_behavior"
            python = str(ROOT / "ros-tools/.venv/bin/python")
            output = report / f"p3-behavior-{name}-ros-probe.json"
            with (report / f"p3-behavior-{name}-server.log").open("w") as server_log:
                server = subprocess.Popen([
                    python, "-B", str(ROOT / "tools/ros_action_probe.py"), "server", "--endpoint", endpoint,
                ], cwd=work, env=env, stdout=server_log, stderr=subprocess.STDOUT)
                try:
                    command = [python, "-B", str(ROOT / "tools/ros_behavior_probe.py"),
                               "--install", str(prefix), "--endpoint", endpoint, "--output", str(output)]
                    process = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=45)
                    (report / f"p3-behavior-{name}-client.log").write_text(process.stdout + process.stderr)
                    results["probes"][name] = {
                        "status": "PASS" if process.returncode == 0 else "FAIL",
                        "command": command, "domain": env["ROS_DOMAIN_ID"], "localhost_only": True,
                        "result": json.loads(output.read_text()) if process.returncode == 0 else None,
                    }
                finally:
                    if server.poll() is None:
                        server.send_signal(signal.SIGINT)
                        try:
                            server.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            server.kill()
                            server.wait(timeout=5)
    results["original_sources"] = verify_sources()
    results["status"] = "PASS" if all(
        item["status"] == "PASS" for item in
        [results["build"], results["original_sources"], *results["probes"].values()]
    ) else "FAIL"
    (report / "p3-behavior-ros.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if results["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
