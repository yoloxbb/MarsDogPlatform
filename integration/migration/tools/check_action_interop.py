"""Check four old/new BT and generated Action-type combinations on real DDS."""
from __future__ import annotations

import json
import argparse
from pathlib import Path
import secrets
import signal
import subprocess
import uuid
from baseline_lib import ROOT, verify_sources
from check_p3_action import action_environment

TOOLS = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["baseline", "migrated"], nargs="+", default=["baseline", "migrated"])
    parser.add_argument("--behavior", choices=["baseline", "migrated"], nargs="+", default=["baseline", "migrated"])
    parser.add_argument("--udp-only", action="store_true", help="Diagnostic loopback-only transport profile")
    args = parser.parse_args()
    assert verify_sources()["status"] == "PASS"
    work, report = ROOT / "work/p1-20260928", ROOT / "reports/p1-20260928"
    results = {"combinations": {}, "scope": "Real BT adapters and full-build Action IDL; fake server; no production execution"}
    for action in args.action:
        action_prefix = work / ("ros-p3-action-" + action) / "install"
        for behavior, bt_prefix in {
            "baseline": work / "ros-behavior-humble59/install",
            "migrated": work / "ros-p3-behavior/install",
        }.items():
            if behavior not in args.behavior:
                continue
            label = "action-" + action + "-bt-" + behavior
            server_env, _ = action_environment([action_prefix])
            client_env, _ = action_environment([action_prefix, bt_prefix])
            domain = str(80 + secrets.randbelow(20))
            for env in (server_env, client_env):
                env.update(ROS_DOMAIN_ID=domain, ROS_LOCALHOST_ONLY="1", RMW_IMPLEMENTATION="rmw_fastrtps_cpp",
                           ROS_LOG_DIR=str(report / "p3-interop-logs"))
                if args.udp_only:
                    env["FASTRTPS_DEFAULT_PROFILES_FILE"] = str(TOOLS.parent / "fixtures/fastdds-local-udp.xml")
            endpoint = "/migration_interop_" + uuid.uuid4().hex + "/execute_behavior"
            python = str(ROOT / "ros-tools/.venv/bin/python")
            output = report / ("p3-interop-" + label + ".json")
            with (report / ("p3-interop-" + label + "-server.log")).open("w") as stream:
                server = subprocess.Popen([
                    python, "-B", str(TOOLS / "ros_action_probe.py"), "server", "--endpoint", endpoint,
                ], cwd=work, env=server_env, stdout=stream, stderr=subprocess.STDOUT)
                try:
                    command = [python, "-B", str(TOOLS / "ros_behavior_probe.py"), "--install", str(bt_prefix),
                               "--endpoint", endpoint, "--output", str(output)]
                    client = subprocess.run(command, cwd=work, env=client_env, capture_output=True, text=True, timeout=45)
                    (report / ("p3-interop-" + label + "-client.log")).write_text(client.stdout + client.stderr)
                    results["combinations"][label] = {
                        "status": "PASS" if client.returncode == 0 else "FAIL", "domain": domain,
                        "transport": "loopback_udp" if args.udp_only else "default",
                        "type_prefix": str(action_prefix),
                        "result": json.loads(output.read_text()) if client.returncode == 0 else None,
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
    results["status"] = "PASS" if all(c["status"] == "PASS" for c in [
        *results["combinations"].values(), results["original_sources"],
    ]) else "FAIL"
    name = "p3-action-bt-interop.json" if len(results["combinations"]) == 4 else "p3-action-bt-interop-diagnostic.json"
    (report / name).write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"status": results["status"], "combinations": list(results["combinations"])}))
    raise SystemExit(0 if results["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
