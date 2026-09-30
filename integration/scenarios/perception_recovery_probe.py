"""Scenario observer; only this test process pauses/restarts its own mock nodes."""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.flags.optimize:
        raise RuntimeError("Scenario assertions require Python without optimization")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    args = parser.parse_args()
    directory, install = args.output.resolve(), args.install.resolve()
    assert os.environ.get("MARSDOG_LOCAL_SIMULATION") == "1"
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    assert os.environ.get("ROS_DOMAIN_ID") == "216"
    import yaml
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String
    from marsdog_voice_interaction.srv import VoiceTask
    from marsdog_vision_interaction.srv import VisionTask
    import marsdog_behavior.perception_client_adapter as behavior
    assert Path(behavior.__file__).resolve().is_relative_to(install)
    share = lambda package: install / package / "share" / package
    voice_share = share("marsdog_voice_interaction") / "config"
    voice = yaml.safe_load((voice_share / "voice.mock.yaml").read_text())
    voice["mock"].update(seed=13, event_interval_sec=3600.0)
    voice["interaction"].update(idle_timeout_sec=3.0, max_duration_sec=0.0)
    voice["logging"].update(dir=str(directory / "voice-log"), file=True, console=True)
    voice["storage"]["root"] = str(directory / "voice-data")
    for name in ("command_lexicon", "object_target_routing"):
        voice[name]["catalog"] = str(voice_share / Path(voice[name]["catalog"]).name)
    vision = yaml.safe_load((share("marsdog_vision_interaction") / "config/vision.mock.yaml").read_text())
    vision["logging"]["dir"] = str(directory / "vision-log")
    vision["storage"]["root"] = str(directory / "vision-data")
    for name, config in (("voice", voice), ("vision", vision)):
        (directory / (name + ".yaml")).write_text(yaml.safe_dump(config, allow_unicode=True))
    report = {"status": "RUNNING", "domain": 216, "cases": [], "service_calls": [],
              "processes": [], "provenance": {
                  "behavior": {"installed": True, "module": behavior.__file__, "python": sys.executable}},
              "config_sha256": {n: hashlib.sha256((directory / (n + ".yaml")).read_bytes()).hexdigest()
                                for n in ("voice", "vision")}}
    children = []
    generations = {"voice": 0, "vision": 0}
    current = {}
    node = None
    active_case = None

    def start(name):
        generations[name] += 1
        key = name + "-" + str(generations[name])
        entry = ("marsdog_voice_interaction.nodes.voice_interaction_node" if name == "voice"
                 else "marsdog_vision_interaction.nodes.vision_interaction_node")
        provenance = directory / (key + "-origin.json")
        code = (
            "import importlib,json,sys;from pathlib import Path;"
            "m=importlib.import_module(" + repr(entry) + ");"
            "p=Path(m.__file__).resolve();assert p.is_relative_to(Path(" + repr(str(install)) + "));"
            "Path(" + repr(str(provenance)) + ").write_text(json.dumps({'installed':True,'module':str(p),'python':sys.executable}));"
            "m.main()")
        command = [str(ROOT / "modules" / name / ".venv/bin/python"), "-B", "-c", code,
                   "--ros-args", "-p", "config_path:=" + str(directory / (name + ".yaml"))]
        log = (directory / (key + ".log")).open("w")
        # Inherit the observer's process group so the outer guardian can reap all
        # descendants if the observer crashes, times out, or gets interrupted.
        process = subprocess.Popen(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT)
        child = {"name": key, "process": process, "log": log, "paused": False, "stopped": False, "forced": False}
        children.append(child)
        current[name] = child
        return child

    def stop(name):
        child = current[name]
        process = child["process"]
        if child["paused"]:
            process.send_signal(signal.SIGCONT)
            child["paused"] = False
        was_alive = process.poll() is None
        if was_alive:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child["forced"] = True
                process.kill()
                process.wait(timeout=5)
        child["stopped"] = True
        if not was_alive or process.returncode != 0 or child["forced"]:
            raise RuntimeError(child["name"] + " did not stop cleanly")

    def spin_for(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            for child in current.values():
                if not child["stopped"] and child["process"].poll() is not None:
                    raise RuntimeError(child["name"] + " exited unexpectedly")
            rclpy.spin_once(node, timeout_sec=min(0.03, max(0.0, end - time.monotonic())))

    def until(predicate, message, timeout=12):
        end = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= end:
                raise RuntimeError(message)
            spin_for(0.03)

    def case(name):
        nonlocal active_case
        active_case = {"id": name, "status": "RUNNING"}
        report["cases"].append(active_case)
        return active_case

    def finish(**evidence):
        active_case.update(status="PASS", **evidence)

    def call(client, service_type, kind, params=None, expected=True):
        until(client.service_is_ready, "Service unavailable: " + kind)
        request = service_type.Request(task_id="scenario-" + str(len(report["service_calls"])),
                                       task_type=kind, params_json=json.dumps(params or {}))
        started = time.monotonic()
        future = client.call_async(request)
        until(future.done, "Service timed out: " + kind)
        response = future.result()
        payload = json.loads(response.result_json) if response.result_json else {}
        record = {"task": kind, "params": params or {}, "success": response.success,
                  "result": payload, "error": response.error_message,
                  "elapsed_seconds": round(time.monotonic() - started, 3)}
        report["service_calls"].append(record)
        assert response.task_id == request.task_id and response.task_type == request.task_type
        assert response.success is expected, record
        return payload

    try:
        rclpy.init()
        node = rclpy.create_node("marsdog_business_recovery_probe")
        adapter = behavior.PerceptionClientAdapter(node, vision_task_timeout_sec=0.4)
        assert adapter._ros2_ready
        report["real_bt_adapter"] = True
        audio = []
        visual = deque(maxlen=20)
        adapter.set_on_audio_direct(lambda event, data: audio.append(dict(data)))
        node.create_subscription(String, "/perception/visual_event",
                                 lambda m: visual.append(json.loads(m.data)), qos_profile_sensor_data)
        voice_client = node.create_client(VoiceTask, "/perception/voice/task")
        vision_client = node.create_client(VisionTask, "/perception/vision/task")
        start("voice")
        start("vision")
        until(lambda: voice_client.service_is_ready() and vision_client.service_is_ready()
              and adapter.check_person()["present"], "Installed mock nodes never became ready")
        v = lambda kind, params=None, expected=True: call(voice_client, VoiceTask, kind, params, expected)

        case("voice-held-continuous-session")
        original = v("start_listening")["interaction_id"]
        assert v("start_listening", {"expected_interaction_id": original})["interaction_id"] == original
        hold = {"interaction_id": original, "hold_token": "scenario-token", "lease_sec": 8.0,
                "reason": "scenario test"}
        assert v("hold_interaction", hold)["renewed"] is False
        spin_for(3.4)
        state = v("get_interaction_state")
        assert state["interaction_active"] and state["hold_active"]
        assert state["interaction_id"] == original
        assert v("hold_interaction", hold)["renewed"] is True
        finish(interaction_id=original, held_past_idle=True, renewed_same_token=True)

        case("voice-stop-stale-requests")
        assert v("stop_listening")["ended"] is True
        until(lambda: any(e.get("interaction_id") == original and e.get("state") == "idle"
                          for e in audio), "BT adapter did not receive Voice idle event")
        second = v("start_listening")["interaction_id"]
        assert second != original
        current_hold = {**hold, "interaction_id": second}
        v("hold_interaction", current_hold)
        assert "mismatch" in v("start_listening", {"expected_interaction_id": original}, False)["error"]
        assert "mismatch" in v("hold_interaction", hold, False)["error"]
        assert "mismatch" in v("release_interaction_hold", hold, False)["error"]
        state = v("get_interaction_state")
        assert state["interaction_id"] == second and len(state["holds"]) == 1
        release = {"interaction_id": second, "hold_token": hold["hold_token"], "reset_idle_timer": True}
        assert v("release_interaction_hold", release)["released"] is True
        assert v("release_interaction_hold", release)["released"] is False
        finish(old_interaction=original, new_interaction=second, old_requests_rejected=True,
               current_hold_preserved=True, release_idempotent=True, idle_received_by_bt=True)

        case("voice-lease-expiry")
        v("hold_interaction", {**current_hold, "lease_sec": 0.8})
        spin_for(1.1)
        state = v("get_interaction_state")
        assert not state["hold_active"] and state["interaction_id"] == second
        spin_for(2.2)
        state = v("get_interaction_state")
        assert not state["interaction_active"] and not state["holds"]
        finish(expired_hold_removed=True, idle_timeout_recovered=True)

        case("voice-restart-rediscovery")
        before_restart = v("start_listening")["interaction_id"]
        v("hold_interaction", {**hold, "interaction_id": before_restart})
        stop("voice")
        until(lambda: not voice_client.service_is_ready(), "Old Voice service did not disappear")
        start("voice")
        state = v("get_interaction_state")
        assert not state["interaction_active"] and not state["holds"]
        new_id = v("start_listening")["interaction_id"]
        assert new_id != before_restart
        assert "mismatch" in v("hold_interaction", {**hold, "interaction_id": before_restart}, False)["error"]
        assert "mismatch" in v("release_interaction_hold", {**hold, "interaction_id": before_restart}, False)["error"]
        assert not v("get_interaction_state")["holds"]
        finish(old_interaction=before_restart, new_interaction=new_id,
               same_service_client_reconnected=True, old_hold_not_restored=True)

        snapshot = call(vision_client, VisionTask, "query_targets", {"target_types": ["human"]})
        old_epoch = snapshot["vision_epoch"]
        assert old_epoch and snapshot["targets"]
        old_target_ids = {t["target_id"] for t in snapshot["targets"]}

        case("vision-timeout-stale-cache")
        current["vision"]["process"].send_signal(signal.SIGSTOP)
        current["vision"]["paused"] = True
        spin_for(0.9)
        assert adapter.check_person() == {"present": False, "count": 0, "identity": "unknown"}
        delayed = []
        adapter.request_wake_speaker(delayed.append, max_bearing_error_deg=180.0)
        until(lambda: len(delayed) == 1, "BT vision request did not time out", timeout=3)
        assert delayed == [None]
        finish(stale_person_cleared=True, timed_out_target=None, callback_count=1)

        case("vision-resume-late-response")
        current["vision"]["process"].send_signal(signal.SIGCONT)
        current["vision"]["paused"] = False
        until(lambda: adapter.check_person()["present"], "BT visual cache did not recover")
        selected = []
        adapter.request_wake_speaker(selected.append, max_bearing_error_deg=180.0)
        until(lambda: len(selected) == 1, "Fresh target request did not recover")
        assert selected[0] and selected[0]["vision_epoch"] == old_epoch
        spin_for(0.8)
        assert delayed == [None], "Late response completed a timed-out decision twice"
        finish(recovered_target=selected[0]["target_id"], epoch=old_epoch,
               late_response_ignored=True, original_callback_count=len(delayed))

        case("vision-restart-new-epoch")
        stop("vision")
        until(lambda: not vision_client.service_is_ready(), "Old Vision service did not disappear")
        start("vision")
        until(lambda: bool(visual) and visual[-1].get("vision_epoch") != old_epoch
              and visual[-1].get("human_candidates"), "New Vision epoch never arrived")
        snapshot = call(vision_client, VisionTask, "query_targets", {"target_types": ["human"]})
        assert snapshot["vision_epoch"] != old_epoch and snapshot["targets"]
        new_ids = {t["target_id"] for t in snapshot["targets"]}
        assert not old_target_ids.intersection(new_ids)
        selected = []
        adapter.request_wake_speaker(selected.append, max_bearing_error_deg=180.0)
        until(lambda: len(selected) == 1, "BT query did not reconnect after Vision restart")
        assert selected[0] and selected[0]["vision_epoch"] == snapshot["vision_epoch"]
        finish(old_epoch=old_epoch, new_epoch=snapshot["vision_epoch"],
               selected_target=selected[0]["target_id"], old_target_ids_absent=True,
               same_service_client_reconnected=True)

        forbidden = ("/simple_cmd", "/cmd_vel", "/api/sport/request", "/robot_status")
        assert not any(node.get_publishers_info_by_topic(t) for t in forbidden)
        report["no_hardware_publishers"] = True
        report["status"] = "PASS"
    except BaseException as error:
        report.update(status="FAIL", error=type(error).__name__ + ": " + str(error))
        if active_case and active_case["status"] == "RUNNING":
            active_case.update(status="FAIL", error=report["error"])
    finally:
        for name, child in list(current.items()):
            if not child["stopped"]:
                try:
                    stop(name)
                except BaseException as error:
                    report.update(status="FAIL", cleanup_error=str(error))
        for child in children:
            child["log"].close()
            process = child["process"]
            report["processes"].append({"name": child["name"], "pid": process.pid,
                "returncode": process.poll(), "reaped": not Path("/proc", str(process.pid)).exists(),
                "forced": child["forced"]})
            path = directory / (child["name"] + "-origin.json")
            if path.is_file():
                report["provenance"][child["name"]] = json.loads(path.read_text())
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        (directory / "observation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
