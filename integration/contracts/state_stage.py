"""Emotion/Needs state and signal production -> real BT subscriptions."""
from copy import deepcopy
from dataclasses import asdict
import json
import random
from types import SimpleNamespace
from unittest.mock import patch
from worker_support import serve


def produce(request):
    from marsdog_core import MarsdogTimeController
    from marsdog_core.emotion_system import MarsdogEmotionSystem
    from marsdog_core.need_system import MarsdogNeedSystem
    from marsdog_ros2 import emotion_engine_node, internal_need_node
    outputs = {}
    with patch("time.time", return_value=1000.0), patch("time.monotonic", return_value=100.0), \
            patch.object(emotion_engine_node, "String", SimpleNamespace), \
            patch.object(internal_need_node, "String", SimpleNamespace):
        for name, operations in request.items():
            e = emotion_engine_node.EmotionEngineNode.__new__(emotion_engine_node.EmotionEngineNode)
            n = internal_need_node.InternalNeedNode.__new__(internal_need_node.InternalNeedNode)
            e.system = MarsdogEmotionSystem(randomGenerator=random.Random(17), timeProvider=lambda: 1000.0,
                                             eventTimeProvider=lambda: 100.0)
            n.system = MarsdogNeedSystem(randomGenerator=random.Random(17), timeProvider=lambda: 1000.0)
            messages = []
            for node, prefix in ((e, "/emotion"), (n, "/internal_need")):
                node.timeController = MarsdogTimeController(
                    1, "06:00", wallTimeProvider=lambda: 1000.0,
                    monotonicProvider=lambda: 100.0)
                node.statePublisher = SimpleNamespace(publish=lambda msg, prefix=prefix:
                    messages.append({"topic": prefix + "/state", "wire": msg.data}))
                node.signalPublisher = SimpleNamespace(publish=lambda msg, prefix=prefix:
                    messages.append({"topic": prefix + "/signal_event", "wire": msg.data}))
            steps = []
            for operation in operations:
                start = len(messages)
                for key, value in operation.get("emotions", {}).items():
                    e.system.SetEmotionValue(key, value)
                for key, value in operation.get("demands", {}).items():
                    n.system.SetDemandValue(key, value)
                for event in operation.get("audio", []):
                    e.OnAudioEventMessage(SimpleNamespace(data=json.dumps(event)))
                    n.OnAudioEventMessage(SimpleNamespace(data=json.dumps(event)))
                if operation.get("publish_need", True):
                    n.PublishState()
                if operation.get("publish_emotion", True):
                    e.PublishState()
                    e.PublishSignalEvents()
                steps.append(deepcopy(messages[start:]))
            outputs[name] = steps
    return outputs, emotion_engine_node.__file__


def behavior(request):
    from marsdog_behavior import ros_node
    outputs = {}
    callbacks = {"/emotion/state": "_on_emotion_state_ros2",
                 "/emotion/signal_event": "_on_emotion_signal_ros2",
                 "/internal_need/state": "_on_need_state_ros2",
                 "/internal_need/signal_event": "_on_need_signal_ros2"}
    for scenario in request:
        random.seed(17)
        with patch("time.time", return_value=1000.0), patch("time.monotonic", return_value=100.0):
            node = ros_node.BehaviorTreeRosNode(force_mock=True)
            candidates = []
            def capture(candidate):
                data = asdict(candidate)
                data.pop("candidate_id")
                data.pop("created_at")
                candidates.append(data)
                return True
            node._add_candidate = capture
            steps = []
            try:
                for messages in scenario["batches"]:
                    start = len(candidates)
                    for message in messages:
                        getattr(node, callbacks[message["topic"]])(SimpleNamespace(data=message["wire"]))
                    steps.append({
                        "emotions": {k: {key: value for key, value in asdict(v).items() if key != "last_update"} for k, v in node._blackboard.emotion_module.get_all_emotions().items()},
                        "needs": {k: {key: value for key, value in asdict(v).items() if key != "last_update"} for k, v in node._blackboard.need_module.get_all_needs().items()},
                        "candidates": deepcopy(candidates[start:]),
                        "pending_emotion_edges": deepcopy(node._pending_emotion_edges),
                    })
            finally:
                node.destroy_node()
            outputs[scenario["id"]] = steps
    return outputs, ros_node.__file__


if __name__ == "__main__":
    serve({"emotion": produce, "behavior": behavior})
