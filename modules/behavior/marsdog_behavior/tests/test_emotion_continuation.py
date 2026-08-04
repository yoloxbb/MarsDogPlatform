from __future__ import annotations

import time

from bionic_dog_bt.blackboard import Blackboard
from marsdog_behavior.candidate_pool import CandidatePool
from marsdog_behavior.intent_mapper import IntentMapper
from marsdog_behavior.ros_node import BehaviorTreeRosNode


class _Perception:
    def request_emotion_context(self, callback) -> None:
        callback({"route": "solo", "target": None})


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def debug(self, *args, **kwargs) -> None:
        pass


def _node() -> BehaviorTreeRosNode:
    node = object.__new__(BehaviorTreeRosNode)
    node._blackboard = Blackboard()
    node._intent_mapper = IntentMapper()
    node._candidate_pool = CandidatePool()
    node._perception = _Perception()
    node._logger = _Logger()
    node._emotion_continuation_enabled = True
    node._emotion_continuation_interval_sec = 0.0
    node._emotion_continuation_max_cycles = 4
    node._emotion_continuation_max_duration_sec = 15.0
    node._emotion_continuation_emotions = {
        "Fear", "Anxiety", "Excite", "Joy", "Curious",
    }
    node._emotion_continuations = {}
    node._emotion_continuation_requests = set()
    return node


def _trigger(node: BehaviorTreeRosNode, emotion: str, value: float) -> None:
    node._blackboard.emotion_module.update_state(
        emotion, value, True
    )
    node._start_emotion_continuation(emotion)


def test_completed_triggered_emotion_enqueues_a_continuation() -> None:
    node = _node()
    _trigger(node, "Joy", 70.0)
    node._emotion_continuations["Joy"]["cycles"] = 1

    node._schedule_emotion_continuation("Joy", "SUCCESS")
    node._dispatch_due_emotion_continuation()

    [candidate] = node._candidate_pool.candidates
    assert candidate["behavior_name"] == "expressJoyAlone"
    assert candidate["params"]["emotion_continuation"] is True


def test_higher_priority_due_emotion_is_continued_first() -> None:
    node = _node()
    _trigger(node, "Joy", 90.0)
    _trigger(node, "Excite", 50.0)
    for session in node._emotion_continuations.values():
        session["cycles"] = 1
        session["next_at"] = time.monotonic() - 0.1

    node._dispatch_due_emotion_continuation()

    [candidate] = node._candidate_pool.candidates
    assert candidate["behavior_name"] == "expressExcitementAlone"


def test_recovery_and_cycle_limit_stop_continuation() -> None:
    node = _node()
    _trigger(node, "Fear", 80.0)
    node._emotion_continuations["Fear"]["cycles"] = 4
    node._schedule_emotion_continuation("Fear", "SUCCESS")
    assert "Fear" not in node._emotion_continuations

    _trigger(node, "Anxiety", 60.0)
    node._blackboard.emotion_module.set_triggered("Anxiety", False)
    node._dispatch_due_emotion_continuation()
    assert "Anxiety" not in node._emotion_continuations


def test_failure_does_not_loop_a_broken_emotion_action() -> None:
    node = _node()
    _trigger(node, "Curious", 55.0)
    node._schedule_emotion_continuation("Curious", "FAILED")
    assert "Curious" not in node._emotion_continuations
