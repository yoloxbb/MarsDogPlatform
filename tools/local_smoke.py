"""Observe a full installed local run through public ROS interfaces only."""
import argparse
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get("MARSDOG_LOCAL_SIMULATION") == "1"
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String
    from marsdog_voice_interaction.srv import VoiceTask
    from marsdog_vision_interaction.srv import VisionTask
    rclpy.init()
    node = rclpy.create_node("marsdog_local_acceptance_probe")
    topics = [
        "/perception/audio_event", "/perception/visual_event", "/behavior/result_event",
        "/internal_need/state", "/emotion/state", "/waypoint_nav/status",
        "/development/nav2_events", "/development/lite3_io",
        "/debug/execute_behavior/goal", "/debug/execute_behavior/result",
    ]
    received = {topic: [] for topic in topics}
    for topic in topics:
        def callback(message, key=topic):
            try:
                received[key].append(json.loads(message.data))
            except json.JSONDecodeError:
                received[key].append({"raw": message.data})
        node.create_subscription(String, topic, callback, qos_profile_sensor_data)
    clients = [
        (node.create_client(VoiceTask, "/perception/voice/task"),
         VoiceTask.Request(task_id="local-smoke", task_type="get_interaction_state", params_json="{}")),
        (node.create_client(VisionTask, "/perception/vision/task"),
         VisionTask.Request(task_id="local-smoke", task_type="check_person", params_json="{}")),
    ]
    futures = []
    error = None
    started = time.monotonic()
    def completed():
        audio = received["/perception/audio_event"]
        results = received["/debug/execute_behavior/result"]
        goals = received["/debug/execute_behavior/goal"]
        matching_goals = {g["goal_id"] for g in goals
            if g.get("behavior_name") == "go_home"
            and g.get("params", {}).get("trigger_event") == "EVT_VOICE_COMMAND_GO_HOME"
            and any(g.get("params", {}).get("interaction_id") == e.get("interaction_id")
                    and e.get("event_type") == "EVT_VOICE_COMMAND_GO_HOME" for e in audio)}
        return (bool(matching_goals)
                and any(e.get("state") == "SUCCEEDED" and e.get("simulated") is True
                        for e in received["/development/nav2_events"])
                and any(e.get("goal_id") in matching_goals
                        and str(e.get("status")).lower() == "success" for e in results)
                and all(received[t] for t in topics if t != "/behavior/result_event")
                and len(futures) == 2 and all(f.done() and f.exception() is None and f.result().success for f in futures))

    try:
        while time.monotonic() - started < 80 and not completed():
            rclpy.spin_once(node, timeout_sec=0.05)
            if not futures and all(c.service_is_ready() for c, _ in clients):
                futures = [c.call_async(req) for c, req in clients]
        if not completed():
            raise RuntimeError("Missing integrated evidence; inspect smoke.json event samples")
        # The local profile must never expose hardware command publishers.
        forbidden = ["/simple_cmd", "/cmd_vel", "/api/sport/request", "/robot_status"]
        assert not any(node.get_publishers_info_by_topic(t) for t in forbidden), "Unexpected hardware I/O publisher"
    except BaseException as exc:
        error = str(exc)
    finally:
        report = {
            "status": "FAIL" if error else "PASS", "error": error,
            "scope": "Real installed module processes and ROS transport; synthetic perception/Nav2/Lite3 I/O",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "nodes": sorted(node.get_node_names()) if rclpy.ok() else [],
            "counts": {k: len(v) for k, v in received.items()},
            "samples": {k: v[-12:] for k, v in received.items()},
            "settlement_note": "go_home is a voice command, deliberately excluded from BT Needs settlement; separate energy contract gate covers settlement",
            "service_results": [{"success": f.result().success, "task_type": f.result().task_type}
                                for f in futures if f.done() and f.exception() is None],
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    print(json.dumps({"status": report["status"], "counts": report["counts"]}))
    if error:
        raise RuntimeError(error)


if __name__ == "__main__":
    main()
