"""Real visual producer and consumers, with explicit test-only capture ports."""
from copy import deepcopy
from dataclasses import asdict
import random
from types import SimpleNamespace
from unittest.mock import patch
from worker_support import serve


def produce(request):
    from marsdog_vision_interaction.messages import visual_event
    outputs = {}
    with patch.object(visual_event, "now_stamp", return_value=1000.0):
        for name, payload in request.items():
            outputs[name] = visual_event.normalize_visual_event(payload)
    return outputs, visual_event.__file__


def behavior(request):
    from marsdog_behavior import ros_node
    outputs = {}
    for case in request:
        random.seed(17)
        clock = [100.0]
        with patch("time.time", return_value=1000.0), patch("time.monotonic", side_effect=lambda: clock[0]):
            node = ros_node.BehaviorTreeRosNode(force_mock=True)
            candidates = []
            def capture(candidate):
                value = asdict(candidate)
                value.pop("candidate_id")
                value.pop("created_at")
                candidates.append(value)
                return True
            node._add_candidate = capture
            adapter = node._perception
            steps = []
            try:
                for step in case["steps"]:
                    clock[0] += step.get("advance", 0.0)
                    start = len(candidates)
                    error = None
                    if "wire" in step:
                        try:
                            adapter._on_visual_ros2(SimpleNamespace(data=step["wire"]))
                        except Exception as exc:
                            error = type(exc).__name__ + ": " + str(exc)
                    steps.append({
                        "error": error, "candidates": deepcopy(candidates[start:]),
                        "person": adapter._check_person_ros2(),
                        "human_candidates": deepcopy(adapter._cached_human_candidates),
                        "objects": deepcopy(adapter._cached_objects),
                        "active_edges": sorted(adapter._active_direct_visual_events),
                        "vision_epoch": adapter._cached_vision_epoch,
                    })
            finally:
                node.destroy_node()
            outputs[case["id"]] = steps
    return outputs, ros_node.__file__


def emotion(request):
    from marsdog_core import emotion_system, need_system
    from marsdog_ros2.perception_adapter import ApplyVisualEventMessage
    outputs = {}
    for case in request:
        clock = [100.0]
        e = emotion_system.MarsdogEmotionSystem(
            randomGenerator=random.Random(17), timeProvider=lambda: 1000.0,
            eventTimeProvider=lambda: clock[0])
        n = need_system.MarsdogNeedSystem(randomGenerator=random.Random(17), timeProvider=lambda: 1000.0)
        steps = []
        for step in case["steps"]:
            clock[0] += step.get("advance", 0.0)
            accepted = []
            if "wire" in step:
                for system in (e, n):
                    try:
                        accepted.append({"events": ApplyVisualEventMessage(system, SimpleNamespace(data=step["wire"]))})
                    except Exception as exc:
                        accepted.append({"error": type(exc).__name__ + ": " + str(exc)})
            steps.append({"accepted": accepted, "emotions": dict(e.state.emotions),
                          "demands": dict(n.state.demands), "owner_present": n.state.ownerPresent})
        outputs[case["id"]] = steps
    return outputs, emotion_system.__file__


def action(request):
    from marsdog_action_executor import ros_node
    outputs = {}
    names = ("attention_controller", "target_approach_adapter", "visual_target_approach_adapter",
             "wake_orientation_adapter", "person_nav_approach_adapter")
    for case in request:
        steps = []
        for step in case["steps"]:
            received = []
            ports = {name: SimpleNamespace(update_visual=lambda payload, name=name:
                     received.append({"port": name, "payload": deepcopy(payload)})) for name in names}
            accepted = None
            if "wire" in step:
                accepted = ros_node._dispatch_visual_event(step["wire"], **ports)
            steps.append({"accepted": accepted, "delivery_order": received})
        outputs[case["id"]] = steps
    return outputs, ros_node.__file__


if __name__ == "__main__":
    serve({"vision": produce, "behavior": behavior, "emotion": emotion, "action": action})
