"""Installed Humble logging observer: native filters and structured output, no hardware."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from runtime_environment import ROOT, ros_environment
from log_runs import prepare_logging, finish_logging
from log_query import read_records, read_health


def probe(directory):
    import rclpy
    from rclpy.node import Node
    from marsdog_observability import __file__ as imported
    from marsdog import INSTALL
    assert Path(imported).resolve().is_relative_to(INSTALL)
    rclpy.init()
    node = Node("logging_regression_probe")
    collector = None
    log = (directory / "collector.log").open("w")
    try:
        env = dict(os.environ)
        env["MARSDOG_LOG_COMPONENT_MAP"] = json.dumps({"logging_regression_probe": "probe"})
        collector = subprocess.Popen([sys.executable, "-B", "-c",
            "from marsdog_observability.ros import main; main()"], cwd=directory, env=env,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 15
        while node.count_subscribers("/rosout") < 1:
            assert collector.poll() is None, "Collector exited before discovery"
            assert time.monotonic() < deadline, "Collector subscription not discovered"
            rclpy.spin_once(node, timeout_sec=0.05)
        for _ in range(3):
            node.get_logger().info("normal-info")
            node.get_logger().warning("normal-warning")
            node.get_logger().info("once-only", once=True)
            node.get_logger().info("throttled", throttle_duration_sec=60)
        wanted = Counter({"normal-info": 3, "normal-warning": 3, "once-only": 1, "throttled": 1})
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            rows, errors = read_records(directory)
            observed = [r for r in rows if r["event_name"] == "ros.message"]
            if Counter(r["message"] for r in observed) == wanted and not errors:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Native log filtering or collection mismatch")
        collector.send_signal(signal.SIGINT)
        collector.wait(timeout=8)
        assert collector.returncode == 0
        assert {r["fields"]["source_component"] for r in observed} == {"probe"}
        assert all(r["fields"]["file"] and r["fields"]["line"] > 0 for r in observed)
        assert {r["level"] for r in observed if r["message"] == "normal-warning"} == {"WARNING"}
        rows, errors = read_records(directory)
        assert not errors
        assert {r["run_id"] for r in rows} == {os.environ["MARSDOG_RUN_ID"]}
        health = read_health(directory)
        assert len(health) == 1
        assert health[0]["closed"] and not health[0]["writer_alive"]
        assert all(health[0][k] == 0 for k in ("pending", "dropped", "priority_dropped", "sink_errors"))
        return {"status": "PASS", "native_messages": dict(wanted), "source_location_preserved": True,
                "once_throttle_preserved": True, "no_collection_loop": True,
                "health": health, "installed_import": imported}
    finally:
        if collector is not None and collector.poll() is None:
            collector.send_signal(signal.SIGINT)
            try:
                collector.wait(timeout=8)
            except subprocess.TimeoutExpired:
                collector.kill()
                collector.wait(timeout=5)
        node.destroy_node()
        rclpy.shutdown()
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "out/logging-runtime")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        result = probe(args.output)
        (args.output / "observation.json").write_text(json.dumps(result, indent=2) + "\n")
        return
    from marsdog import INSTALL, LOCAL, BUILD_TOOLS, source_fingerprint
    assert json.loads((LOCAL / "build-receipt.json").read_text())["source_sha256"] == source_fingerprint()
    directory = args.output.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    env = ros_environment(INSTALL, domain=219)
    env["ROS_LOG_DIR"] = str(directory / "ros-log")
    env["MARSDOG_LOG_LEVEL"] = "INFO"
    env["MARSDOG_LOG_DISABLED"] = "0"
    prepare_logging(env, directory)
    report = {"status": "FAIL", "run_directory": str(directory), "domain": 219}
    try:
        with (directory / "probe.log").open("w") as log:
            subprocess.run([str(BUILD_TOOLS / "python"), "-B", str(Path(__file__).resolve()),
                            "--probe", "--output", str(directory)], env=env, cwd=directory,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=40)
        report.update(json.loads((directory / "observation.json").read_text()))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        report["error"] = str(exc)
    finally:
        finish_logging(directory, report["status"])
        (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
