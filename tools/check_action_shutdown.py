"""Verify installed Action publishes stop before exiting for SIGINT and SIGTERM."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from runtime_environment import ROOT, ros_environment
from marsdog import INSTALL, BUILD_TOOLS, process_specs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "out/action-shutdown")
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if not args.probe:
        env = ros_environment(INSTALL, 214)
        env.update(MARSDOG_LOCAL_SIMULATION="1", ROS_LOG_DIR=str(directory / "ros-log"))
        subprocess.run([str(BUILD_TOOLS / "python"), "-B", str(Path(__file__)),
                        "--probe", "--output", str(directory)], env=env, check=True)
        return
    assert os.environ.get("MARSDOG_LOCAL_SIMULATION") == "1"
    assert os.environ.get("ROS_DOMAIN_ID") == "214"
    import rclpy
    from std_msgs.msg import String
    rclpy.init()
    node = rclpy.create_node("action_shutdown_regression_probe")
    events = []
    sub = node.create_subscription(String, "/development/lite3_io",
                                   lambda m: events.append(json.loads(m.data)), 20)
    cases = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        run = directory / (sig.name + "-" + str(time.time_ns()))
        subprocess.run([str(BUILD_TOOLS / "python"), "-B", str(ROOT / "tools/prepare_local_configs.py"),
                        "--run", str(run), "--install", str(INSTALL)], check=True)
        command = next(c for n,c in process_specs(run) if n == "action")
        with (run / "action.log").open("w") as log:
            proc = subprocess.Popen(command, cwd=run, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    rclpy.spin_once(node, timeout_sec=0.05)
                    ready = "/execute_behavior/_action/send_goal" in dict(node.get_service_names_and_types())
                    if ready and node.get_publishers_info_by_topic("/development/lite3_io"):
                        break
                    assert proc.poll() is None, "Action exited before ROS action became ready"
                else:
                    raise AssertionError("Action never became ready")
                events.clear()
                proc.send_signal(sig)
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline and proc.poll() is None:
                    rclpy.spin_once(node, timeout_sec=0.03)
                proc.wait(timeout=1)
                # Drain already-delivered DDS samples after producer exit.
                end = time.monotonic() + 0.3
                while time.monotonic() < end:
                    rclpy.spin_once(node, timeout_sec=0.02)
                assert proc.returncode == 0, (sig.name, (run / "action.log").read_text()[-2000:])
                stops = [e for e in events if e.get("kind") == "twist" and e.get("simulated") is True
                         and all(e.get(k) == 0.0 for k in ("linear_x", "linear_y", "angular_z"))]
                assert stops, "No zero-velocity command observed before Action exit"
                assert all(not node.get_publishers_info_by_topic(t)
                           for t in ("/simple_cmd", "/cmd_vel", "/api/sport/request", "/robot_status"))
                cases.append({"signal": sig.name, "status": "PASS", "returncode": proc.returncode,
                              "zero_commands": stops, "pid_reaped": not Path(f"/proc/{proc.pid}").exists()})
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
    node.destroy_node()
    rclpy.shutdown()
    report = {"status": "PASS", "cases": cases, "scope": "Installed Action and real ROS transport; simulated Lite3 I/O only"}
    (directory / "result.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
