"""One real module per process. JSON stdin/stdout is TEST transport only."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import random
import sys

FAMILIES = {
    "action": ("marsdog_action_executor",),
    "behavior": ("marsdog_behavior", "bionic_dog_bt"),
    "emotion": ("marsdog_core", "marsdog_ros2"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=FAMILIES, required=True)
    args = parser.parse_args()
    request = json.load(sys.stdin)
    foreign = [
        name for stage, names in FAMILIES.items() if stage != args.stage
        for name in names if importlib.util.find_spec(name) is not None
    ]
    if foreign:
        raise SystemExit(f"Cross-module environment contamination: {foreign}")
    if importlib.util.find_spec("rclpy") is not None:
        raise SystemExit("Pure contract worker must not inherit a ROS environment")

    if args.stage == "action":
        from marsdog_action_executor import ros_node
        result = ros_node._make_result(
            "fixture-goal", "fixture-behavior", request["behavior_name"],
            status=request["status"], metadata=request.get("metadata"),
        )
        response = {
            "behavior_name": result.behavior_name, "status": result.status,
            "metadata_json": result.metadata_json,
            "transport": "existing_python_fallback_not_ROS",
        }
        module_file = ros_node.__file__
    elif args.stage == "behavior":
        from marsdog_behavior import result_event_mapper
        mapper = result_event_mapper.ResultEventMapper()
        event = mapper.build_result_event(
            request["behavior_name"], request["status"],
            json.loads(request["metadata_json"]),
        )
        response = {"event": json.loads(event) if event else None}
        module_file = result_event_mapper.__file__
    else:
        from marsdog_core import need_system
        from marsdog_ros2.behavior_result_adapter import ApplyBehaviorResultMessage
        system = need_system.MarsdogNeedSystem(
            configDir=request.get("config_dir"), randomGenerator=random.Random(17),
            timeProvider=lambda: 1000.0,
        )
        for name, value in request["initial"].items():
            system.SetDemandValue(name, value)
        before = dict(system.state.demands)
        accepted = [
            ApplyBehaviorResultMessage(system, json.dumps(event))
            for event in request["events"]
        ]
        response = {
            "before": before, "after": dict(system.state.demands), "accepted": accepted,
            "sleeping": system.IsSleeping(),
        }
        module_file = need_system.__file__
    response["provenance"] = {
        "stage": args.stage, "pid": os.getpid(), "python": sys.executable,
        "prefix": sys.prefix, "module_file": str(Path(module_file).resolve()),
        "foreign_business_modules": foreign,
    }
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
