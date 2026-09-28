"""Run the transport probe on localhost, isolated test namespace/domain, no ROS daemon."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
from baseline_lib import ROOT, verify_sources
from check_ros import ros_env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Invalid run-id")
    if verify_sources()["status"] != "PASS":
        raise SystemExit("Source baseline changed")
    report = ROOT / "reports" / args.run_id
    prefix = ROOT / "work" / args.run_id / "ros-idl-only-action/install"
    env = ros_env([prefix])
    env.update(ROS_DOMAIN_ID=str(180 + os.getpid() % 30), ROS_LOCALHOST_ONLY="1",
               RMW_IMPLEMENTATION="rmw_fastrtps_cpp", ROS_LOG_DIR=str(report / "ros-logs"))
    endpoint = f"/migration_p1_{os.getpid()}/execute_behavior"
    base = [str(ROOT / ".venv/bin/python"), "-B", str(ROOT / "tools/ros_action_probe.py")]
    results = {
        "status": "FAIL", "domain_id": env["ROS_DOMAIN_ID"], "localhost_only": True,
        "endpoint": endpoint, "scope": "IDL-only diagnostic prefix; never a production replacement",
    }
    with (report / "ros-action-server.log").open("w") as log:
        server = subprocess.Popen(base + ["server", "--endpoint", endpoint],
                                  env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            client = subprocess.run(base + ["client", "--endpoint", endpoint], env=env,
                                    text=True, capture_output=True, timeout=45)
            (report / "ros-action-client.log").write_text(client.stdout + client.stderr)
            results["client_exit_code"] = client.returncode
            if client.returncode == 0:
                results["observation"] = json.loads(client.stdout.splitlines()[-1])
                results["status"] = results["observation"]["status"]
        except subprocess.TimeoutExpired:
            results["error"] = "Client timed out"
        finally:
            if server.poll() is None:
                server.send_signal(signal.SIGINT)
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
    results["original_sources"] = verify_sources()
    (report / "ros-transport.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if results["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
