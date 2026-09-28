"""Exercise an installed, real Needs ROS node on test-only remapped endpoints."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import uuid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    import marsdog_ros2.internal_need_node as implementation

    module_path = Path(implementation.__file__).resolve()
    assert module_path.is_relative_to(args.install.resolve()), module_path
    suffix = uuid.uuid4().hex
    prefix = "/migration_emotion_" + suffix
    endpoints = (
        "/internal_need/state", "/internal_need/signal_event",
        "/perception/visual_event", "/perception/audio_event",
        "/perception/tactile_event", "/behavior/result_event",
        "/personality/state", "/simulation/time_state",
    )
    ros_args = ["--ros-args"]
    for endpoint in endpoints:
        ros_args += ["-r", endpoint + ":=" + prefix + endpoint]
    rclpy.init(args=ros_args)
    executor = SingleThreadedExecutor()
    need = probe = None
    try:
        need = implementation.InternalNeedNode()
        probe = Node("migration_emotion_probe_" + suffix)
        states = []
        probe.create_subscription(
            String, "/internal_need/state", lambda msg: states.append(json.loads(msg.data)), 10,
        )
        publisher = probe.create_publisher(String, "/behavior/result_event", 10)
        executor.add_node(need)
        executor.add_node(probe)

        def until(predicate, seconds=8.0):
            end = time.monotonic() + seconds
            while not predicate() and time.monotonic() < end:
                executor.spin_once(timeout_sec=0.1)
            assert predicate(), "Timed out waiting for ROS discovery/state"

        until(lambda: publisher.get_subscription_count() == 1 and bool(states))
        initial = states[-1]["demands"]["Energy"]["value"]
        event = {
            "event_id": suffix, "timestamp": time.time(),
            "action_type": "ACTION_RECHARGE", "demand_type": "Energy",
            "result_type": "COMPLETED",
            "metadata": {"recoveryMode": "charging", "energyValue": 88},
        }
        states.clear()
        publisher.publish(String(data=json.dumps(event)))
        until(lambda: bool(states) and states[-1]["demands"]["Energy"]["value"] == 12)
        settled = states[-1]["demands"]["Energy"]["value"]
        states.clear()
        event["metadata"]["energyValue"] = 42  # Same ID must not settle a second time.
        publisher.publish(String(data=json.dumps(event)))
        end = time.monotonic() + 2.5
        while time.monotonic() < end:
            executor.spin_once(timeout_sec=0.1)
        assert len(states) >= 2, "Expected periodic state publications after duplicate"
        duplicate_values = [state["demands"]["Energy"]["value"] for state in states]
        assert set(duplicate_values) == {12}, duplicate_values
        result = {
            "status": "PASS", "module_file": str(module_path),
            "initial_energy_need": initial, "settled_energy_need": settled,
            "duplicate_energy_need_samples": duplicate_values,
            "endpoint_prefix": prefix, "remapped_endpoints": endpoints,
            "scope": "Real installed InternalNeedNode and ROS pub/sub; synthetic result; no hardware",
        }
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    finally:
        if need is not None:
            need.destroy_node()
        if probe is not None:
            probe.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
