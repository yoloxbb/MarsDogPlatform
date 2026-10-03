"""Installed BT/Action decision scenarios with explicit protocol/visual/state fixtures."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from marsdog import process_specs, BUILD_TOOLS


def main():
    if sys.flags.optimize or os.environ.get("ROS_DOMAIN_ID") != "217" or os.environ.get("ROS_LOCALHOST_ONLY") != "1":
        raise RuntimeError("Decision scenarios require unoptimized isolated domain 217")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    args = parser.parse_args()
    directory, install = args.output.resolve(), args.install.resolve()
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    report = {"status": "RUNNING", "domain": 217, "cases": [], "processes": [],
              "scope": "Installed real BT/Action and DDS; fixture Voice/state/vision inputs, simulated Lite3/Nav2. "
                       "Target loss is stale visual rejection before dispatch; moving-target stop has separate Action tests."}
    children, streams = [], []
    node, active_case = None, None
    goals, results, wire_order = [], [], []
    def interrupt(signum, frame):
        raise KeyboardInterrupt("Decision scenarios interrupted")
    previous = signal.signal(signal.SIGTERM, interrupt)
    rclpy.init()
    try:
        env = dict(os.environ, MARSDOG_DECISION_TRACE_DIR=str(directory / "decisions"))
        subprocess.run([str(BUILD_TOOLS / "python"), "-B", str(ROOT / "tools/prepare_local_configs.py"),
                        "--run", str(directory), "--install", str(install)], env=env, check=True, timeout=30,
                       capture_output=True)
        for name, command in process_specs(directory):
            if name not in ("inputs", "waypoint", "action", "behavior"):
                continue
            command = list(command)
            if name in ("action", "behavior"):
                entry = "marsdog_action_executor.ros_node" if name == "action" else "marsdog_behavior.ros_node"
                origin = directory / (name + "-origin.json")
                command[command.index("-c") + 1] = (
                    "import importlib,json;from pathlib import Path;"
                    "m=importlib.import_module(" + repr(entry) + ");"
                    "assert Path(m.__file__).resolve().is_relative_to(Path(" + repr(str(install)) + "));"
                    "Path(" + repr(str(origin)) + ").write_text(json.dumps({'module':m.__file__,'installed':True}));m.main()")
            stream = (directory / (name + ".log")).open("w")
            streams.append(stream)
            children.append((name, subprocess.Popen(command, cwd=directory, env=dict(env, MARSDOG_PYTHON=command[0]),
                                                   stdout=stream, stderr=subprocess.STDOUT)))
        node = Node("decision_scenario_observer")
        def receive(message, target, kind):
            payload = json.loads(message.data)
            target.append(payload)
            wire_order.append({"kind": kind, "payload": payload, "monotonic_ns": time.monotonic_ns()})
        node.create_subscription(String, "/debug/execute_behavior/goal", lambda m: receive(m, goals, "goal"), 100)
        node.create_subscription(String, "/debug/execute_behavior/result", lambda m: receive(m, results, "result"), 100)
        topics = ("/perception/audio_event", "/perception/visual_event", "/internal_need/state",
                  "/internal_need/signal_event", "/emotion/state", "/emotion/signal_event")
        publishers = {topic: node.create_publisher(String, topic, 100) for topic in topics}
        def spin(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                for name, child in children:
                    if child.poll() is not None:
                        raise RuntimeError(name + " exited early")
                rclpy.spin_once(node, timeout_sec=0.03)
        def until(predicate, message, seconds=20):
            end = time.monotonic() + seconds
            while not predicate() and time.monotonic() < end:
                spin(0.03)
            if not predicate():
                raise RuntimeError(message)
        def publish(topic, payload):
            publishers[topic].publish(String(data=json.dumps(payload)))
        def traces():
            records = []
            for path in (directory / "decisions").glob("*.jsonl"):
                for line in path.read_text().splitlines():
                    try:
                        records.append(json.loads(line))
                    except ValueError:
                        pass
            return records
        base = json.loads((ROOT / "interfaces/application/audio-event-v2/baseline.json").read_text())["observed"]["voice"]["sit"][0]
        def audio(event, command_id, uid):
            data = deepcopy(base)
            data.update(event_type=event, specific_event_type=event, command_id=command_id,
                        interaction_id="decision-fixture-session", utterance_id=uid,
                        intent_source="explicit_protocol_fixture", slots=[],
                        asr_text="", action="NONE", intent="NONE")
            data["header"]["stamp"] = time.time()
            publish("/perception/audio_event", data)
            return data
        def goal(uid):
            return next((g for g in goals if g.get("params", {}).get("utterance_id") == uid), None)
        def terminal(g):
            return next((r for r in results if r.get("goal_id") == g["goal_id"]), None)
        def wait_goal(uid):
            until(lambda: goal(uid) is not None, "Missing Goal: " + uid)
            return goal(uid)
        def wait_terminal(g):
            until(lambda: terminal(g) is not None, "Missing terminal: " + g["goal_id"])
            spin(0.15)
            return terminal(g)
        def case(name):
            nonlocal active_case
            active_case = {"id": name, "status": "RUNNING"}
            report["cases"].append(active_case)
        def finish(**evidence):
            active_case.update(status="PASS", **evidence)
        until(lambda: node.count_publishers("/debug/execute_behavior/goal") > 0 and
              publishers["/perception/audio_event"].get_subscription_count() > 0, "BT/Action not ready", 35)
        state = json.loads((ROOT / "interfaces/application/state-v2/baseline.json").read_text())["observed"]["emotion"]
        def frames(name, index=0, wanted=None):
            for row in state[name][index]:
                if wanted is None or row["topic"] in wanted:
                    payload = json.loads(row["wire"])
                    payload["timestamp"] = time.time()
                    publish(row["topic"], payload)
        frames("default", wanted={"/internal_need/state", "/emotion/state"})
        spin(0.3)

        case("duplicate-event-one-goal")
        message = audio("EVT_VOICE_COMMAND_HOLD_POSITION", "CMD_HOLD_POSITION", "duplicate")
        first = wait_goal("duplicate")
        for _ in range(3):
            publish("/perception/audio_event", message)
            spin(0.1)
        wait_terminal(first)
        assert len([g for g in goals if g.get("params", {}).get("utterance_id") == "duplicate"]) == 1
        assert any(r.get("reason") == "duplicate_event" and r.get("utterance_id") == "duplicate" for r in traces())
        finish(goal_id=first["goal_id"])

        case("queued-command-after-terminal")
        audio("EVT_VOICE_COMMAND_WAIT", "CMD_WAIT", "queue-first")
        old = wait_goal("queue-first")
        audio("EVT_VOICE_COMMAND_HOLD_POSITION", "CMD_HOLD_POSITION", "queue-second")
        replacement = wait_goal("queue-second")
        wait_terminal(old)
        wait_terminal(replacement)
        history = traces()
        old_end = next(r["monotonic_ns"] for r in history if r["stage"] == "action_terminal" and r.get("goal_id") == old["goal_id"])
        new_start = next(r["monotonic_ns"] for r in history if r["stage"] == "goal_dispatch" and r.get("goal_id") == replacement["goal_id"])
        assert old_end <= new_start
        finish(first_goal=old["goal_id"], next_goal=replacement["goal_id"], terminal_precedes_dispatch=True)

        case("stop-preempts-running-goal")
        audio("EVT_VOICE_COMMAND_WAIT", "CMD_WAIT", "stop-first")
        old = wait_goal("stop-first")
        audio("EVT_VOICE_COMMAND_STOP", "CMD_STOP", "stop-command")
        stop = wait_goal("stop-command")
        previous_result = wait_terminal(old)
        wait_terminal(stop)
        history = traces()
        assert str(previous_result["status"]).upper() in {"CANCELED", "CANCELLED", "INTERRUPTED"}
        cancel = next(r for r in history if r["stage"] == "cancel_requested" and r.get("goal_id") == old["goal_id"])
        old_end = next(r for r in history if r["stage"] == "action_terminal" and r.get("goal_id") == old["goal_id"])
        new_start = next(r for r in history if r["stage"] == "goal_dispatch" and r.get("goal_id") == stop["goal_id"])
        assert cancel["monotonic_ns"] <= old_end["monotonic_ns"] <= new_start["monotonic_ns"]
        finish(canceled_goal=old["goal_id"], replacement_goal=stop["goal_id"], terminal=previous_result)

        case("stale-visual-target-no-goal")
        visual = json.loads((ROOT / "interfaces/application/visual-event-v1/baseline.json").read_text())["observed"]["vision"]["owner"]
        visual["header"]["stamp"] = time.time()
        publish("/perception/visual_event", visual)
        spin(2.2)
        audio("EVT_VOICE_COMMAND_OWNER_UNHAPPY", "CMD_OWNER_UNHAPPY", "lost-target")
        until(lambda: any(r.get("utterance_id") == "lost-target" and
                          r.get("reason") == "owner_visual_target_unavailable" for r in traces()),
              "Missing stale-target rejection")
        assert goal("lost-target") is None
        finish(reason="owner_visual_target_unavailable", dispatched=False)

        case("need-before-emotion-after-command")
        audio("EVT_VOICE_COMMAND_HOLD_POSITION", "CMD_HOLD_POSITION", "competition")
        blocker = wait_goal("competition")
        start_index = len(goals)
        frames("all_needs", wanted={"/internal_need/state"})
        frames("joy_cycle", wanted={"/emotion/state"})
        spin(0.2)
        for row in state["all_needs"][0]:
            value = json.loads(row["wire"])
            if value.get("event_type") == "NEED_BLADDER_TRIGGERED":
                publish(row["topic"], value)
        frames("joy_cycle", wanted={"/emotion/signal_event"})
        until(lambda: any(r.get("stage") == "candidate_queued" and r.get("trigger_event") == "EMO_JOY_TRIGGERED" for r in traces()),
              "Emotion candidate not queued")
        wait_terminal(blocker)
        until(lambda: any(g.get("params", {}).get("trigger_event") == "NEED_BLADDER_TRIGGERED" for g in goals[start_index:])
              and any(g.get("params", {}).get("trigger_event") == "EMO_JOY_TRIGGERED" for g in goals[start_index:]),
              "Missing need/emotion dispatch")
        relevant = [g for g in goals[start_index:] if g.get("params", {}).get("trigger_event") in
                    {"NEED_BLADDER_TRIGGERED", "EMO_JOY_TRIGGERED"}]
        assert [g["params"]["trigger_event"] for g in relevant[:2]] == ["NEED_BLADDER_TRIGGERED", "EMO_JOY_TRIGGERED"]
        for g in relevant:
            wait_terminal(g)
        frames("default", wanted={"/internal_need/state", "/emotion/state"})
        finish(dispatch_order=[g["behavior_name"] for g in relevant], priority_levels=[g["priority_level"] for g in relevant])

        spin(0.3)
        for g in goals:
            assert len([r for r in results if r.get("goal_id") == g["goal_id"]]) == 1, g
        forbidden = ("/simple_cmd", "/cmd_vel", "/api/sport/request", "/robot_status")
        report["no_hardware_publishers"] = not any(node.get_publishers_info_by_topic(t) for t in forbidden)
        assert report["no_hardware_publishers"]
        report.update(status="PASS", goals=goals, terminals=results, observations=wire_order,
                      provenance={name: json.loads((directory / (name + "-origin.json")).read_text()) for name in ("action", "behavior")})
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="FAIL", error=str(error), goals=goals, terminals=results, observations=wire_order)
        if active_case is not None and active_case["status"] != "PASS":
            active_case.update(status="FAIL", error=str(error))
    finally:
        for name, child in reversed(children):
            forced = False
            early = child.poll() is not None
            if not early:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    forced = True
                    child.kill()
                    child.wait(timeout=5)
            report["processes"].append({"name": name, "pid": child.pid, "returncode": child.returncode,
                                         "reaped": child.poll() is not None, "forced": forced})
            if early or forced or child.returncode != 0:
                report.update(status="FAIL", shutdown_error=name)
        for stream in streams:
            stream.close()
        signal.signal(signal.SIGTERM, previous)
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        (directory / "observation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
