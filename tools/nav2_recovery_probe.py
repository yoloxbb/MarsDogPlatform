"""Black-box waypoint/Nav2 failures; no private module imports or recovery bypass."""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    assert os.environ.get("MARSDOG_LOCAL_SIMULATION") == "1"
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from marsdog_voice_interaction.srv import VoiceTask
    from std_srvs.srv import SetBool
    from std_msgs.msg import String
    from geometry_msgs.msg import PoseStamped, Twist
    from nav_msgs.msg import Path as NavPath
    from lifecycle_msgs.srv import GetState

    rclpy.init()
    node = rclpy.create_node("marsdog_nav2_failure_contracts")
    client = node.create_client(VoiceTask, "/waypoint_nav/task")
    freeze = node.create_client(SetBool, "/development/nav2/freeze")
    active = node.create_client(GetState, "/bt_navigator/get_state")
    statuses, poses, velocities, paths, cases = {}, [], [], [], []
    subscriptions = [
        node.create_subscription(String, "/waypoint_nav/status",
            lambda m: statuses.update({json.loads(m.data)["task_id"]: json.loads(m.data)}), qos_profile_sensor_data),
        node.create_subscription(PoseStamped, "/development/nav2/pose",
            lambda m: poses.append((m.pose.position.x, m.pose.position.y)), 10),
        node.create_subscription(Twist, "/development/nav2/cmd_vel",
            lambda m: velocities.append((m.linear.x, m.linear.y, m.angular.z)), 10),
        node.create_subscription(NavPath, "/plan",
            lambda m: paths.append([(p.pose.position.x, p.pose.position.y) for p in m.poses]), qos_profile_sensor_data),
    ]
    started = time.monotonic()
    counter = 0
    paused_pid = None
    def spin_until(predicate, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            rclpy.spin_once(node, timeout_sec=0.03)
        if not predicate():
            raise AssertionError("Deadline waiting for evidence; statuses=" + json.dumps(statuses))
    def call(service, request):
        spin_until(service.service_is_ready, 10)
        future = service.call_async(request)
        spin_until(future.done, 8)
        return future.result()
    def task(kind, task_id=None, **params):
        nonlocal counter
        counter += 1
        request = VoiceTask.Request(task_id=task_id or f"probe-query-{counter}", task_type=kind,
            params_json=json.dumps(dict(protocol_version="1.0", client_id="marsdog_action_executor", **params)))
        response = call(client, request)
        return response.success, json.loads(response.result_json)
    def goto(task_id, place, timeout=25):
        ok, payload = task("goto_place", task_id, place=place, timeout_sec=float(timeout))
        assert ok, payload
    def state(task_id, code=None, status=None, seconds=20):
        spin_until(lambda: task_id in statuses and
                   (code is None or statuses[task_id].get("code") == code) and
                   (status is None or statuses[task_id].get("state") == status), seconds)
        return statuses[task_id].copy()
    def record(name, data):
        cases.append({"name": name, "status": "PASS", "evidence": data})
        print(name, "PASS", flush=True)
    def switch(service, value):
        assert call(service, SetBool.Request(data=value)).success

    error = None
    try:
        spin_until(lambda: client.service_is_ready() and active.service_is_ready() and bool(poses), 20)
        spin_until(lambda: call(active, GetState.Request()).current_state.id == 3, 10)
        # Map metadata must be received by waypoint_nav before accepting named targets.
        spin_until(lambda: len(poses) >= 60, 5)
        goto("arrival", "A")
        arrival = state("arrival", status="SUCCEEDED")
        assert math.dist(poses[-1], (1.0, 1.0)) < 0.2, poses[-1]
        assert paths and any(abs(v[0]) > 0.01 for v in velocities)
        record("real_plan_and_arrival", {"terminal": arrival, "pose": poses[-1]})

        goto("cancel", "E")
        state("cancel", code="NAV2_ACCEPTED")
        ok, payload = task("cancel", target_task_id="cancel")
        assert ok, payload
        canceled = state("cancel", code="CLIENT_CANCELLED", status="INTERRUPTED")
        spin_until(lambda: velocities and max(map(abs, velocities[-1])) < 0.001, 2)
        record("cancel_waits_for_real_terminal", canceled)

        switch(freeze, True)
        goto("timeout", "E", timeout=0.8)
        timed_out = state("timeout", code="TIMEOUT", status="FAILED")
        record("timeout_cancels_before_failure", timed_out)
        switch(freeze, False)

        # Waypoint C lies on the synthetic wall at x=3; real Navfn must reject it.
        goto("blocked", "C")
        blocked = state("blocked", status="FAILED")
        assert blocked["code"] == "NAV2_FAILED", blocked
        record("unreachable_goal_is_failure", blocked)

        # Pause only this run's navigator while motion is explicitly frozen.
        # A timeout cannot attest a stopped robot until the actual result arrives.
        switch(freeze, True)
        goto("interrupted", "E", timeout=0.6)
        state("interrupted", code="NAV2_ACCEPTED")
        processes = json.loads((args.output.parent / "processes.json").read_text())
        paused_pid = next(p["pid"] for p in processes if p["name"] == "bt_navigator")
        cmdline = Path(f"/proc/{paused_pid}/cmdline").read_bytes()
        assert b"/nav2_bt_navigator/bt_navigator" in cmdline
        os.kill(paused_pid, signal.SIGSTOP)
        recovery = state("interrupted", code="RECOVERY_REQUIRED", status="RUNNING", seconds=3)
        ok, rejected = task("goto_place", "while-locked", place="A", timeout_sec=10.0)
        assert not ok and rejected["code"] == "RECOVERY_BLOCKED", rejected
        os.kill(paused_pid, signal.SIGCONT)
        paused_pid = None
        terminal = state("interrupted", status="FAILED", seconds=15)
        assert terminal["code"] == "TIMEOUT", terminal
        record("transport_interruption_holds_lock_until_real_result",
               {"locked": recovery, "rejected": rejected, "confirmed_terminal": terminal})
        switch(freeze, False)

        # Real planner must route around the wall before the next successful task.
        paths.clear()
        trajectory_start = len(poses)
        goto("recovered", "E", timeout=40)
        recovered = state("recovered", status="SUCCEEDED", seconds=40)
        assert math.dist(poses[-1], (5.0, 1.0)) < 0.2
        assert any(any(y > 2.5 for x,y in path) for path in paths), "No wall detour observed"
        trajectory = poses[trajectory_start:]
        clearance = min(math.hypot(max(3.0-x, 0.0, x-3.1), max(-y, 0.0, y-2.5))
                        for x,y in trajectory)
        assert clearance >= 0.15, ("Simulated footprint crossed wall", clearance)
        record("recovered_navigation_uses_obstacle_detour",
               {"terminal": recovered, "pose": poses[-1], "path": paths[-1],
                "executed_trajectory": trajectory[::10], "minimum_wall_clearance_m": clearance})
        ok, query = task("query", target_task_id="arrival")
        assert ok and query.get("found") and query["status"]["state"] == "SUCCEEDED", query
        record("previous_terminal_remains_queryable", query)
        assert all(not node.get_publishers_info_by_topic(t)
                   for t in ("/cmd_vel", "/simple_cmd", "/api/sport/request", "/robot_status"))
    except BaseException as exc:
        error = str(exc)
    finally:
        if paused_pid is not None:
            try: os.kill(paused_pid, signal.SIGCONT)
            except ProcessLookupError: pass
        report = {"status": "FAIL" if error else "PASS", "error": error, "cases": cases,
                  "elapsed_seconds": round(time.monotonic()-started, 3), "last_statuses": statuses,
                  "scope": "Real Nav2 lifecycle/action/planner/controller and waypoint persistence; synthetic inputs"}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()
    if error: raise RuntimeError(error)

if __name__ == "__main__":
    main()
