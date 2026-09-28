"""Installed Voice DDS/service check with temporary data and original mock provider."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get("ROS_LOCALHOST_ONLY") == "1"
    assert 180 <= int(os.environ["ROS_DOMAIN_ID"]) < 230
    import yaml
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from ament_index_python.packages import get_package_share_directory
    from marsdog_voice_interaction.srv import VoiceTask
    from marsdog_voice_interaction.nodes import voice_interaction_node as implementation
    from marsdog_voice_interaction.main import main as entry
    from marsdog_voice_interaction.utils.ros_entrypoint import _candidate_python
    from marsdog_voice_interaction.providers.mock_event import MockEventProvider

    install = args.install.resolve()
    source = args.source.resolve()
    module = Path(implementation.__file__).resolve()
    assert module.is_relative_to(install), module
    assert callable(entry)
    assert str(_candidate_python()) == os.environ["MARSDOG_PYTHON"]
    share = Path(get_package_share_directory("marsdog_voice_interaction")).resolve()
    assert share.is_relative_to(install)
    assets = {}
    for folder in ("config", "launch", "lib", "srv"):
        for original in (source / folder).rglob("*"):
            if not original.is_file() or "__pycache__" in original.parts:
                continue
            relative = original.relative_to(source)
            actual = share / relative
            assert actual.is_file(), actual
            assert actual.read_bytes() == original.read_bytes(), relative
            assets[str(relative)] = hashlib.sha256(actual.read_bytes()).hexdigest()
    assert (share / "package.xml").read_bytes() == (source / "package.xml").read_bytes()
    static = module.parents[1] / "api/static"
    for original in (source / "marsdog_voice_interaction/api/static").iterdir():
        assert (static / original.name).read_bytes() == original.read_bytes()
    fields = {"request": VoiceTask.Request.get_fields_and_field_types(),
              "response": VoiceTask.Response.get_fields_and_field_types()}
    assert set(fields["request"]) == {"task_id", "task_type", "params_json"}
    assert set(fields["response"]) == {"success", "task_id", "task_type",
                                      "result_json", "error_message", "latency_ms"}

    suffix = uuid.uuid4().hex
    prefix = "/migration_voice_" + suffix
    endpoints = ("/perception/audio_event", "/perception/voice/enrollment_event", "/perception/voice/task")
    with tempfile.TemporaryDirectory(prefix="voice-data-", dir=args.output.parent) as directory:
        temporary = Path(directory)
        config = yaml.safe_load((share / "config/voice.mock.yaml").read_text())
        config["mock"]["event_interval_sec"] = 3600.0
        config["logging"].update(dir=str(temporary / "log"), file=False, console=False)
        config["storage"]["root"] = str(temporary / "data")
        for key in ("command_lexicon", "object_target_routing"):
            config[key]["catalog"] = str(share / "config" / Path(config[key]["catalog"]).name)
        assert config["mock"]["enabled"] and config["mock"]["mode"] == "event"
        assert config["providers"] == {} and config["speaker_api"]["enabled"] is False
        config_path = temporary / "voice.yaml"
        config_path.write_text(yaml.safe_dump(config))
        ros_args = ["--ros-args", "-p", "config_path:=" + str(config_path)]
        for endpoint in endpoints:
            ros_args += ["-r", endpoint + ":=" + prefix + endpoint]
        rclpy.init(args=ros_args)
        executor = SingleThreadedExecutor()
        voice = probe = None
        try:
            voice = implementation.VoiceInteractionNode()
            assert set(voice._providers) == {"mock_event"}
            assert voice._speaker_api is None and voice._service is not None
            probe = Node("voice_migration_probe_" + suffix)
            events = []
            probe.create_subscription(String, endpoints[0], lambda msg: events.append(json.loads(msg.data)), 10)
            client = probe.create_client(VoiceTask, endpoints[2])
            executor.add_node(voice)
            executor.add_node(probe)

            def until(predicate, seconds=10.0):
                deadline = time.monotonic() + seconds
                while not predicate() and time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=0.05)
                assert predicate(), "Timed out waiting for isolated Voice ROS transport"

            until(lambda: client.service_is_ready() and voice._audio_pub.get_subscription_count() == 1)
            results = []

            def call(task_type, params, success=True):
                request = VoiceTask.Request(task_id=suffix, task_type=task_type,
                                            params_json=params if isinstance(params, str) else json.dumps(params))
                future = client.call_async(request)
                until(future.done)
                response = future.result()
                assert response is not None
                assert response.success is success, response.error_message
                assert response.task_id == suffix and response.task_type == task_type
                assert response.latency_ms >= 0
                payload = json.loads(response.result_json) if response.result_json else {}
                results.append({"task": task_type, "success": response.success,
                                "keys": sorted(payload), "error_present": bool(response.error_message)})
                return payload

            started = call("start_listening", {})
            assert started["listening"] and started["interaction_id"]
            identity = started["interaction_id"]
            held = call("hold_interaction", {"interaction_id": identity, "hold_token": suffix,
                                            "lease_sec": 5, "reason": "migration_test"})
            assert held["held"]
            call("get_interaction_state", {})
            call("release_interaction_hold", {"interaction_id": identity, "hold_token": suffix})
            call("unsupported_migration_task", {}, False)
            call("get_interaction_state", "{", False)
            stop = call("stop_listening", {})
            assert not stop["listening"]
            events.clear()
            # Inject the existing provider output only at the published-event boundary.
            # This checks DDS/JSON transport, not real microphone or model recognition.
            event = MockEventProvider({"enabled": True}).build_event("EVT_VOICE_COMMAND_SIT")
            voice._publish(event)
            until(lambda: any(e.get("event_type") == "EVT_VOICE_COMMAND_SIT" for e in events))
            received = next(e for e in events if e.get("event_type") == "EVT_VOICE_COMMAND_SIT")
            assert received["action"] == "SIT" and received["should_trigger_behavior_tree"] is True
            for node in (voice, probe):
                assert all(p.topic_name.startswith(prefix) for p in node.publishers
                           if p.topic_name not in ("/rosout", "/parameter_events"))
            result = {
                "status": "PASS", "module_file": str(module), "share": str(share),
                "scope": "Real installed Voice node and DDS pub/sub/service; original mock provider; no models/audio/HTTP server",
                "endpoint_prefix": prefix, "service_fields": fields,
                "asset_hashes": assets, "service_cases": results,
                "event": {key: received[key] for key in
                          ("event_type", "action", "should_trigger_behavior_tree")},
                "event_keys": sorted(received),
            }
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"status": "PASS", "service_cases": len(results), "event": result["event"]}))
        finally:
            executor.shutdown()
            if voice is not None:
                voice.destroy_node()
            if probe is not None:
                probe.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
