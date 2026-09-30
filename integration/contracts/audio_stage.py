"""Independent real-module workers. stdin/stdout is test transport, never ROS."""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
from types import SimpleNamespace
from unittest.mock import patch

FAMILIES = {
    "voice": ("marsdog_voice_interaction",),
    "behavior": ("marsdog_behavior", "bionic_dog_bt"),
    "emotion": ("marsdog_core", "marsdog_ros2"),
    "action": ("marsdog_action_executor",),
    "vision": ("marsdog_vision_interaction",),
}


def produce(request):
    from marsdog_voice_interaction.messages import audio_event
    from marsdog_voice_interaction.messages.intent_event_router import route_classification_events
    from marsdog_voice_interaction.core.command_lexicon import CommandLexicon

    lexicon = CommandLexicon(Path("config/command_catalog.yaml"))
    outputs = {}
    with patch.object(audio_event, "now_stamp", return_value=1000.0):
        for name, spec in request.items():
            if spec["kind"] == "catalog":
                match = lexicon.match(spec["text"])
                if match is None:
                    raise ValueError("Fixture no longer matches catalog: " + name)
                events = [match.to_event(asr_text=spec["text"], language="zh")]
            elif spec["kind"] == "classification":
                events = route_classification_events(**spec["classification"])
            elif spec["kind"] == "normalize":
                events = [spec["payload"]]
            else:
                raise ValueError(spec["kind"])
            # The ROS node normally supplies correlation IDs. This test exercises
            # codecs/routing and consumers, not ASR/model/session generation.
            outputs[name] = [
                audio_event.normalize_audio_event(
                    {**event, **spec.get("context", {})} if isinstance(event, dict) else event
                ) for event in events
            ]
    return outputs, audio_event.__file__


def consume_behavior(scenarios):
    from marsdog_behavior import ros_node

    outputs = {}
    for scenario in scenarios:
        random.seed(17)
        with patch("time.time", return_value=1000.0), patch("time.monotonic", return_value=100.0):
            node = ros_node.BehaviorTreeRosNode(force_mock=True)
            candidates = []

            def capture(candidate):
                value = asdict(candidate)
                # Only generated bookkeeping identifiers/timestamps are omitted.
                value.pop("candidate_id")
                value.pop("created_at")
                candidates.append(value)
                return True

            node._add_candidate = capture
            steps = []
            try:
                for wire in scenario["wires"]:
                    start = len(candidates)
                    node._perception._on_audio_ros2(SimpleNamespace(data=wire))
                    session = node._voice_session
                    steps.append({
                        "candidates": candidates[start:],
                        "session": asdict(session) if session is not None else None,
                        "voice_session_generation": node._voice_session_generation,
                        "audio_target_generation": node._audio_target_generation,
                    })
            finally:
                node.destroy_node()
            outputs[scenario["id"]] = steps
    return outputs, ros_node.__file__


def consume_emotion(scenarios):
    from marsdog_core import emotion_system, need_system
    from marsdog_ros2.perception_adapter import ApplyAudioEventMessage

    outputs = {}
    for scenario in scenarios:
        emotion = emotion_system.MarsdogEmotionSystem(
            randomGenerator=random.Random(17), timeProvider=lambda: 1000.0,
            eventTimeProvider=lambda: 100.0,
        )
        needs = need_system.MarsdogNeedSystem(
            randomGenerator=random.Random(17), timeProvider=lambda: 1000.0,
        )
        steps = []
        for wire in scenario["wires"]:
            message = SimpleNamespace(data=wire)
            applied_emotion = ApplyAudioEventMessage(emotion, message)
            applied_needs = ApplyAudioEventMessage(needs, message)
            steps.append({
                "applied_emotion": applied_emotion, "applied_needs": applied_needs,
                "emotions": dict(emotion.state.emotions),
                "demands": dict(needs.state.demands),
                "owner_present": needs.state.ownerPresent,
                "sleeping": needs.IsSleeping(),
            })
        outputs[scenario["id"]] = steps
    return outputs, emotion_system.__file__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("voice", "behavior", "emotion"), required=True)
    args = parser.parse_args()
    request = json.load(sys.stdin)
    foreign = [
        name for stage, names in FAMILIES.items() if stage != args.stage
        for name in names if importlib.util.find_spec(name) is not None
    ]
    if foreign or importlib.util.find_spec("rclpy") is not None:
        raise RuntimeError("Worker must be module-isolated and ROS-free: " + repr(foreign))
    with contextlib.redirect_stdout(sys.stderr):
        observed, module_file = {
            "voice": produce, "behavior": consume_behavior, "emotion": consume_emotion,
        }[args.stage](request)
    loaded_foreign = [
        name for stage, names in FAMILIES.items() if stage != args.stage
        for name in sys.modules if any(name == prefix or name.startswith(prefix + ".") for prefix in names)
    ]
    if loaded_foreign:
        raise RuntimeError("Foreign business imports: " + repr(loaded_foreign))
    print(json.dumps({
        "observed": observed,
        "provenance": {
            "stage": args.stage, "pid": os.getpid(), "python": sys.executable,
            "prefix": sys.prefix, "module_file": str(Path(module_file).resolve()),
            "foreign_business_modules": loaded_foreign, "ros_importable": False,
        },
    }, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
