"""Static cross-module import and installed ROS dependency observations."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from baseline_lib import ROOT, WORKSPACE, read_baseline, verify_sources

PREFIXES = {
    "vision": ["marsdog_vision_interaction"],
    "voice": ["marsdog_voice_interaction"],
    "emotion": ["marsdog_core", "marsdog_ros2"],
    "behavior": ["marsdog_behavior", "bionic_dog_bt"],
    "action": ["marsdog_action_executor"],
}
ENDPOINTS = [
    ("/perception/visual_event", "std_msgs/msg/String", "vision", ["behavior", "emotion", "action"]),
    ("/perception/audio_event", "std_msgs/msg/String", "voice", ["behavior", "emotion"]),
    ("/perception/vision/object_detections", "std_msgs/msg/String", "vision", ["action"]),
    ("/perception/vision/task", "marsdog_vision_interaction/srv/VisionTask", "vision", ["behavior", "action"]),
    ("/perception/voice/task", "marsdog_voice_interaction/srv/VoiceTask", "voice", ["behavior"]),
    ("/emotion/state", "std_msgs/msg/String", "emotion", ["behavior", "vision"]),
    ("/emotion/signal_event", "std_msgs/msg/String", "emotion", ["behavior"]),
    ("/internal_need/state", "std_msgs/msg/String", "emotion", ["behavior"]),
    ("/internal_need/signal_event", "std_msgs/msg/String", "emotion", ["behavior"]),
    ("/behavior/result_event", "std_msgs/msg/String", "behavior", ["emotion"]),
    ("/behavior/attention_tracking", "std_msgs/msg/String", "behavior", ["action"]),
    ("/behavior/goal_lease", "std_msgs/msg/String", "behavior", ["action"]),
    ("/execute_behavior", "marsdog_action_executor/action/ExecuteBehavior", "action", ["behavior"]),
    ("/waypoint_nav/task", "marsdog_voice_interaction/srv/VoiceTask", "UNKNOWN", ["action"]),
    ("/waypoint_nav/status", "std_msgs/msg/String", "UNKNOWN", ["action"]),
    ("/person_3d_localization/locate_from_bbox", "person_3d_localization/srv/LocateFromBbox", "robot", ["vision"]),
    ("/go2/follow_uwb", "go2_uwb_behavior/action/FollowUwb", "robot", ["action"]),
    ("/go2/random_roam", "go2_uwb_behavior/action/RandomRoam", "robot", ["action"]),
    ("/go2/set_behavior", "go2_uwb_behavior/srv/SetBehavior", "robot", ["action"]),
    ("/navigate_to_pose", "nav2_msgs/action/NavigateToPose", "EXTERNAL_NAV2", ["action"]),
    ("/spin", "nav2_msgs/action/Spin", "EXTERNAL_NAV2", ["action"]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Invalid run-id")
    if verify_sources()["status"] != "PASS":
        raise SystemExit("Baseline changed")
    baseline = read_baseline()
    observations = []
    parse_errors = []
    for owner, prefixes in PREFIXES.items():
        source = baseline["sources"][owner]
        for name in source["files"]:
            if not name.endswith(".py") or Path(name).parts[0] not in prefixes:
                continue
            if "tests" in Path(name).parts:
                continue
            try:
                tree = ast.parse((WORKSPACE / source["path"] / name).read_text())
            except SyntaxError as exc:
                parse_errors.append({"source": owner, "path": name, "error": str(exc)})
                continue
            for node in ast.walk(tree):
                imports = ([a.name for a in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0
                           else [])
                for imported in imports:
                    if not imported:
                        continue
                    provider = next((o for o, names in PREFIXES.items()
                                     if imported.split(".")[0] in names), None)
                    if provider and provider != owner:
                        interface_only = ".srv" in imported or ".action" in imported
                        observations.append({
                            "consumer": owner, "provider": provider, "path": name,
                            "line": node.lineno, "import": imported,
                            "kind": "generated_interface" if interface_only else "implementation",
                            "note": "Legacy reference; provider has no action submodule" if
                            imported == "marsdog_ros2.action" else "",
                        })
    result = {
        "scope": "Static Python imports in five business modules; dynamic imports are not fully covered",
        "status": "PASS" if not parse_errors and not any(
            i["kind"] == "implementation" for i in observations) else "FAIL",
        "imports": observations, "parse_errors": parse_errors,
        "endpoint_registry": [
            {"endpoint": e, "type": t, "provider": p, "consumers": c,
             "verification": "static source evidence, not production graph discovery"}
            for e, t, p, c in ENDPOINTS
        ],
        "execute_behavior_type_caveat": "Both clients prefer external marsdog_interfaces when available; not installed on this host",
        "original_sources": verify_sources(),
    }
    (ROOT / "reports" / args.run_id / "boundaries.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "cross_module_imports": len(observations),
                      "registered_endpoints": len(ENDPOINTS)}))


if __name__ == "__main__":
    main()
