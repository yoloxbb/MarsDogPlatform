"""Arbitrary recorded WAV -> installed Voice -> DDS -> BT/Action observation.

Uses the existing presegmented-audio test boundary. No text injection, microphone,
speaker authentication fabrication, hardware publishers, or modified robot gates.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from ros_cpu_pipeline_probe import atomic_json, prepare_worker_request


def observer(request, directory):
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from marsdog_voice_interaction.srv import VoiceTask

    config = prepare_worker_request(request, directory)
    events, goals, terminals, feedback = [], [], [], []
    timestamps = []
    node, process = None, None
    result = {"status": "FAIL", "model_acceptance": False, "hardware_acceptance": False,
              "observer_pid": os.getpid(), "events": events, "goals": goals,
              "terminals": terminals, "feedback": feedback, "observations": timestamps,
              "expectation_errors": [], "real_asr_cases": 0, "text_fixture_cases": 0}
    def interrupt(signum, frame):
        raise KeyboardInterrupt("recording trial interrupted")
    previous = signal.signal(signal.SIGTERM, interrupt)
    rclpy.init(args=[])
    try:
        node = Node("recording_trial_observer")
        def subscribe(topic, target):
            def receive(message):
                payload = json.loads(message.data)
                target.append(payload)
                timestamps.append({"topic": topic, "payload": payload,
                                   "monotonic_ns": time.monotonic_ns(), "timestamp": time.time()})
            node.create_subscription(String, topic, receive, 100)
        subscribe(config["topics"]["audio_event"], events)
        subscribe("/debug/execute_behavior/goal", goals)
        subscribe("/debug/execute_behavior/result", terminals)
        subscribe("/debug/execute_behavior/feedback", feedback)
        client = node.create_client(VoiceTask, config["topics"]["voice_task"])
        def until(predicate, seconds=60):
            deadline = time.monotonic() + seconds
            while not predicate() and time.monotonic() < deadline:
                if process is not None and process.poll() is not None:
                    raise RuntimeError("Voice worker exited early: " + str(process.returncode))
                rclpy.spin_once(node, timeout_sec=0.05)
            if not predicate():
                raise TimeoutError("Trial observation did not complete")
        def call(kind):
            future = client.call_async(VoiceTask.Request(task_id="trial-" + kind,
                                                         task_type=kind, params_json="{}"))
            until(future.done, 10)
            response = future.result()
            if not response.success:
                raise RuntimeError(response.error_message)
            return json.loads(response.result_json)
        def audit():
            path = directory / "worker-state.json"
            return json.loads(path.read_text()) if path.exists() else {}
        with (directory / "worker.log").open("w") as stream:
            process = subprocess.Popen([sys.executable, "-B",
                str(Path(__file__).with_name("ros_cpu_pipeline_probe.py")), "--worker",
                "--request", str(directory / "worker-request.json"), "--output", str(directory)],
                cwd=directory, stdout=stream, stderr=subprocess.STDOUT)
            until(lambda: (directory / "worker-ready.json").exists() and client.service_is_ready(), 100)
            until(lambda: node.count_publishers("/debug/execute_behavior/goal") > 0
                  and node.count_subscribers(config["topics"]["audio_event"]) >= 2, 30)
            identity = call("start_listening")["interaction_id"]
            until(lambda: audit().get("capturing"))
            submitted_ns = time.monotonic_ns()
            atomic_json(directory / "input.json", {"sequence": 1, "case": {
                "id": "user-recording", "audio": request["trial"]["wav"]}})
            result["submitted_monotonic_ns"] = submitted_ns
            until(lambda: len(audit().get("asr", [])) == 1, 90)
            state = audit()
            result["worker"] = state
            recognized = state["asr"][0]["result"]
            if recognized.get("reason") != "ok" or not recognized.get("asr_text", "").strip():
                raise RuntimeError("ASR produced no usable transcript: " + str(recognized))
            until(lambda: not audit().get("intent_pending", False) and
                  any(e.get("intent_source") for e in events), 90)
            state = audit()
            uid = next(d["utterance_id"] for d in state["delivered"] if d["id"] == "user-recording")
            result.update(interaction_id=identity, utterance_id=uid, submitted_monotonic_ns=submitted_ns)
            def matching_events():
                return [e for e in events if e.get("interaction_id") == identity and e.get("utterance_id") == uid]
            def matching_goals():
                return [g for g in goals if g.get("params", {}).get("interaction_id") == identity
                        and g.get("params", {}).get("utterance_id") == uid]
            def rejections():
                rows = []
                for path in (directory / "structured").glob("behavior-*.jsonl*"):
                    for line in path.read_text().splitlines():
                        try:
                            entry = json.loads(line)
                        except ValueError:
                            continue
                        if entry.get("log_schema_version") != 2:
                            continue
                        row = {**entry["fields"], **entry["context"],
                               "stage": entry["event_name"].removeprefix("behavior.").replace(".", "_")}
                        if row.get("interaction_id") == identity and row.get("utterance_id") == uid:
                            rows.append(row)
                return [r for r in rows if r.get("stage") in (
                    "mapping_rejected", "candidate_rejected", "candidate_discarded", "candidate_expired")]
            # Let the separate subscriber and BT timer process the final envelope.
            deadline = time.monotonic() + 0.6
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.05)
            requested = any(e.get("should_trigger_behavior_tree") for e in matching_events())
            if requested:
                until(lambda: bool(matching_goals()) or bool(rejections()), 20)
            selected = matching_goals()
            if selected:
                until(lambda: all(any(t.get("goal_id") == g["goal_id"] for t in terminals) for g in selected),
                      request["trial"]["terminal_timeout"])
            selected_results = [t for t in terminals if t.get("goal_id") in {g["goal_id"] for g in selected}]
            if len(selected_results) != len(selected):
                raise RuntimeError("Each dispatched goal must have exactly one terminal observation")
            if not selected:
                outcome = "rejected_before_goal" if requested else "no_dispatch_requested"
            elif all(str(t.get("status", "")).upper() == "SUCCESS" for t in selected_results):
                outcome = "success"
            else:
                outcome = "action_failed_or_canceled"
            result.update(outcome=outcome, command_events=matching_events(), command_goals=selected,
                          command_terminals=selected_results, rejections=rejections())
            expected = request["trial"].get("expect_event")
            if expected and not any(e.get("event_type") == expected for e in matching_events()):
                result["expectation_errors"].append("expected_event_not_observed:" + expected)
            expected_outcome = request["trial"].get("expect_outcome")
            if expected_outcome and expected_outcome != outcome:
                result["expectation_errors"].append("expected_outcome:" + expected_outcome)
            forbidden = ("/simple_cmd", "/cmd_vel", "/api/sport/request", "/robot_status")
            result["no_hardware_publishers"] = not any(node.get_publishers_info_by_topic(t) for t in forbidden)
            if not result["no_hardware_publishers"]:
                raise RuntimeError("Forbidden hardware publisher in isolated trial")
            call("stop_listening")
            atomic_json(directory / "finish.json", {})
            until(lambda: process.poll() is not None, 25)
            final = json.loads((directory / "worker-final.json").read_text())
            result.update(worker=final, real_asr_cases=sum(x["kind"] == "real_sensevoice_cpu" for x in final["asr"]),
                          text_fixture_cases=sum(x["kind"] == "explicit_text_fixture_no_asr" for x in final["asr"]))
            if result["real_asr_cases"] != 1 or result["text_fixture_cases"] != 0:
                raise RuntimeError("A recording trial must use exactly one real ASR invocation")
            if final["asr"][0]["result"].get("reason") != "ok":
                raise RuntimeError("ASR failed: " + str(final["asr"][0]["result"]))
            result["status"] = "PASS"
    except (Exception, KeyboardInterrupt) as error:
        result.update(status="FAIL", error=str(error) or type(error).__name__)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        result["worker_returncode"] = process.returncode if process else None
        signal.signal(signal.SIGTERM, previous)
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        atomic_json(directory / "probe.json", result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get("ROS_LOCALHOST_ONLY") != "1" or os.environ.get("ROS_DOMAIN_ID") != "215":
        raise SystemExit("Trial requires isolated localhost domain 215")
    raise SystemExit(observer(json.loads(args.request.read_text()), args.output))
