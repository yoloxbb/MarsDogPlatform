"""Full Voice -> BT -> Action -> waypoint -> real Nav2 acceptance."""
import json
from pathlib import Path
import time

def main():
    import argparse, os
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    assert os.environ.get("MARSDOG_LOCAL_SIMULATION") == "1"
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String
    from nav_msgs.msg import Path as NavPath
    from geometry_msgs.msg import PoseStamped, Twist
    from action_msgs.msg import GoalStatusArray
    rclpy.init()
    node = rclpy.create_node("marsdog_real_nav2_acceptance")
    received = {k: [] for k in ("audio", "goals", "results", "waypoint", "visual", "needs", "emotion")}
    subscriptions = []
    for key, topic in [
        ("audio", "/perception/audio_event"), ("goals", "/debug/execute_behavior/goal"),
        ("results", "/debug/execute_behavior/result"), ("waypoint", "/waypoint_nav/status"),
        ("visual", "/perception/visual_event"), ("needs", "/internal_need/state"),
        ("emotion", "/emotion/state")]:
        subscriptions.append(node.create_subscription(String, topic,
            lambda m, k=key: received[k].append(json.loads(m.data)), qos_profile_sensor_data))
    paths, poses, velocities, statuses = [], [], [], []
    subscriptions += [
        node.create_subscription(NavPath, "/plan", lambda m: paths.append(
            [[p.pose.position.x, p.pose.position.y] for p in m.poses]), qos_profile_sensor_data),
        node.create_subscription(PoseStamped, "/development/nav2/pose",
            lambda m: poses.append([m.pose.position.x, m.pose.position.y]), 10),
        node.create_subscription(Twist, "/development/nav2/cmd_vel",
            lambda m: velocities.append([m.linear.x, m.linear.y, m.angular.z]), 10),
        node.create_subscription(GoalStatusArray, "/navigate_to_pose/_action/status",
            lambda m: statuses.extend({"goal_id": bytes(s.goal_info.goal_id.uuid).hex(), "status": s.status}
                                     for s in m.status_list), qos_profile_sensor_data),
    ]
    def complete():
        ids = {g.get("goal_id") for g in received["goals"]
               if g.get("behavior_name") == "go_home"
               and any(e.get("event_type") == "EVT_VOICE_COMMAND_GO_HOME"
                       and e.get("interaction_id") == g.get("params", {}).get("interaction_id")
                       for e in received["audio"])}
        return (any(r.get("goal_id") in ids and str(r.get("status")).lower() == "success"
                    for r in received["results"])
                and any(s["status"] == 4 for s in statuses)
                and any(len(p) > 2 for p in paths)
                and any(abs(v[0]) + abs(v[1]) + abs(v[2]) > 0.01 for v in velocities)
                and len(poses) > 2
                and max((p[0]-poses[0][0])**2+(p[1]-poses[0][1])**2 for p in poses) > 0.04
                and all(received[k] for k in received))
    error = None
    started = time.monotonic()
    try:
        while time.monotonic() - started < 85 and not complete():
            rclpy.spin_once(node, timeout_sec=0.05)
        if not complete():
            raise RuntimeError("Missing real Nav2 plan, commanded movement or correlated business success")
        forbidden = ["/cmd_vel", "/simple_cmd", "/api/sport/request", "/robot_status"]
        assert all(not node.get_publishers_info_by_topic(t) for t in forbidden), "Unexpected hardware output"
        servers = node.get_node_names()
        assert "bt_navigator" in servers and "marsdog_local_simulated_inputs" not in servers
    except BaseException as exc:
        error = str(exc)
    finally:
        report = {"status": "FAIL" if error else "PASS", "error": error,
                  "scope": "Real Nav2 and business processes; ideal synthetic kinematics/map/localization",
                  "elapsed_seconds": round(time.monotonic()-started, 2),
                  "counts": {k: len(v) for k, v in received.items()},
                  "samples": {k: v[-8:] for k, v in received.items()},
                  "plans": paths[-4:], "initial_pose": poses[0] if poses else None,
                  "final_pose": poses[-1] if poses else None, "velocity_samples": velocities[-12:],
                  "nav2_statuses": statuses[-16:]}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()
    if error: raise RuntimeError(error)

if __name__ == "__main__":
    main()
