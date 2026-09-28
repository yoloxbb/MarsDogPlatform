"""Actual installed BT ActionClientAdapter against the P1 fake action server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interface-package", choices=["marsdog_action_executor", "marsdog_interfaces"], default="marsdog_action_executor")
    args = parser.parse_args()
    import rclpy
    import marsdog_behavior.action_client_adapter as implementation
    from marsdog_behavior.config_paths import get_config_dir
    from bionic_dog_bt.datatypes import ActiveBehavior
    from bionic_dog_bt.constants import GOAL_CANCEL_REQUESTED, GOAL_TERMINAL

    path = Path(implementation.__file__).resolve()
    assert path.is_relative_to(args.install.resolve()), path
    assert get_config_dir().is_relative_to(args.install.resolve()), get_config_dir()
    rclpy.init()
    node = rclpy.create_node("migration_behavior_adapter_probe")
    adapter = implementation.ActionClientAdapter(node, args.endpoint)
    try:
        assert adapter._action_type.__module__.startswith(args.interface_package + ".action")
        assert adapter._client.wait_for_server(timeout_sec=15)

        def until(predicate, seconds=10.0):
            end = time.monotonic() + seconds
            while not predicate() and time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=0.01)
            assert predicate(), str({
                "error": "Timed out waiting for real adapter callback",
                "lifecycle": adapter._goal_lifecycle,
                "send_done": {k: v.done() for k, v in adapter._send_futures.items()},
                "result_done": {k: v.done() for k, v in adapter._result_futures.items()},
            })

        active = ActiveBehavior("p3-success", "recharge", 1, 1.0, 1.0, "Energy",
                                params={"energyValue": 88})
        goal = adapter.send_goal(active)
        until(lambda: adapter.get_goal_lifecycle(goal) == GOAL_TERMINAL)
        result = adapter.get_result(goal)
        assert result.status == "SUCCESS" and result.metadata == {"energyValue": 88}
        assert result.behavior_name == "recharge" and result.behavior_id == active.behavior_id
        feedback = adapter.get_feedback(goal)
        assert feedback is not None and feedback.safe_to_interrupt and feedback.progress == 0.25
        adapter.remove_goal(goal)
        assert not adapter.has_goal(goal)

        active = ActiveBehavior("p3-cancel", "test_cancel", 1, 1.0, 1.0, "Energy")
        goal = adapter.send_goal(active)
        until(lambda: goal in adapter._goal_handles)
        assert adapter.cancel_goal(goal)
        until(lambda: adapter._cancel_futures[goal].done())
        assert adapter._cancel_futures[goal].result().goals_canceling
        ack = time.monotonic()
        assert adapter.get_goal_lifecycle(goal) == GOAL_CANCEL_REQUESTED
        assert adapter.get_result(goal) is None
        adapter.remove_goal(goal)
        assert adapter.has_goal(goal), "Cancel ACK must retain ownership"
        until(lambda: adapter.get_goal_lifecycle(goal) == GOAL_TERMINAL)
        delay = time.monotonic() - ack
        assert delay >= 0.15, delay
        result = adapter.get_result(goal)
        assert result.status == "CANCELED"
        adapter.remove_goal(goal)
        assert not adapter.has_goal(goal)
        report = {
            "status": "PASS", "module_file": str(path), "config_dir": str(get_config_dir()),
            "type": args.interface_package + "/action/ExecuteBehavior",
            "scope": "Real installed BT adapter and generated original IDL; fake Action server; no hardware",
            "success_metadata": {"energyValue": 88}, "terminal_delay_after_cancel_ack_sec": round(delay, 3),
            "ownership_retained_until_terminal": True,
        }
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        adapter._client.destroy()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
