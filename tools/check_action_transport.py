"""Installed BT action transport: feedback and cancel ACK versus terminal ownership."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from marsdog import BUILD_TOOLS, INSTALL
from runtime_environment import ROOT, ros_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "out/action-transport")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "result.json"
    result_path.write_text('{"status":"RUNNING"}\n')
    report = {"status": "FAIL"}
    server = None
    try:
        env = ros_environment(INSTALL, domain=213)
        env["ROS_LOG_DIR"] = str(output / "ros-log")
        endpoint = "/compat_action_" + uuid.uuid4().hex
        # Reuse the frozen test-only probes; no migration/build or old repository is run.
        probes = ROOT / "integration/migration/tools"
        command = [str(BUILD_TOOLS / "python"), "-B", str(probes / "ros_action_probe.py"),
                   "server", "--endpoint", endpoint, "--interface-package", "marsdog_interfaces"]
        with (output / "server.log").open("w") as log:
            server = subprocess.Popen(command, cwd=output, env=env, stdout=log,
                                      stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("Test server exited before ready")
                if '"phase": "ready"' in (output / "server.log").read_text():
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("Test server readiness timeout")
            command = [str(BUILD_TOOLS / "python"), "-B", str(probes / "ros_behavior_probe.py"),
                       "--install", str(INSTALL), "--endpoint", endpoint,
                       "--interface-package", "marsdog_interfaces",
                       "--output", str(output / "observation.json")]
            with (output / "client.log").open("w") as client_log:
                result = subprocess.run(command, cwd=output, env=env, stdout=client_log,
                                        stderr=subprocess.STDOUT, timeout=60)
            if result.returncode:
                raise RuntimeError("Installed BT client failed; see client.log")
            report = json.loads((output / "observation.json").read_text())
            if report["status"] != "PASS" or report["ownership_retained_until_terminal"] is not True:
                raise RuntimeError("Missing terminal ownership proof")
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report = {"status": "FAIL", "error": str(error)}
    finally:
        forced = False
        if server is not None:
            if server.poll() is None:
                os.killpg(server.pid, signal.SIGINT)
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    forced = True
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait(timeout=5)
            report["server_returncode"] = server.returncode
            report["server_reaped"] = not Path("/proc/" + str(server.pid)).exists()
            if forced or not report["server_reaped"] or server.returncode != 0:
                report.update(status="FAIL", cleanup_forced=forced)
        result_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
