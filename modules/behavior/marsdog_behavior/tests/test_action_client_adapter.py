"""Unit tests for asynchronous Action Client edge cases."""

from __future__ import annotations

import threading

from marsdog_behavior.action_client_adapter import ActionClientAdapter


class _Logger:
    def __init__(self):
        self.messages = []

    def warn(self, message):
        self.messages.append(("warn", message))

    def error(self, message):
        self.messages.append(("error", message))


class _Node:
    def __init__(self):
        self.logger = _Logger()

    def get_logger(self):
        return self.logger


class _Future:
    def __init__(self, result):
        self._result = result
        self.callback = None

    def result(self):
        return self._result

    def add_done_callback(self, callback):
        self.callback = callback


class _GoalHandle:
    accepted = True

    def __init__(self):
        self.cancel_requested = False
        self.result_future = _Future(object())

    def cancel_goal_async(self):
        self.cancel_requested = True
        return _Future(object())

    def get_result_async(self):
        return self.result_future


def _adapter() -> ActionClientAdapter:
    adapter = ActionClientAdapter.__new__(ActionClientAdapter)
    adapter._node = _Node()
    adapter._lock = threading.Lock()
    adapter._feedback_cache = {}
    adapter._result_cache = {}
    adapter._goal_handles = {}
    adapter._bhv_to_goal = {}
    adapter._behavior_names = {}
    adapter._canceled_goal_ids = set()
    return adapter


def test_rejected_goal_becomes_failure_result():
    adapter = _adapter()
    adapter._bhv_to_goal["goal-1"] = "goal-1"
    adapter._behavior_names["goal-1"] = "respond_owner_call"
    rejected = type("Rejected", (), {"accepted": False})()

    adapter._on_goal_response("goal-1", _Future(rejected))
    result = adapter.get_result("goal-1")

    assert result is not None
    assert result.status == "FAILURE"
    assert result.behavior_name == "respond_owner_call"
    assert result.reason == "goal rejected"


def test_cancel_before_goal_response_cancels_late_handle():
    adapter = _adapter()
    adapter._bhv_to_goal["goal-1"] = "goal-1"
    adapter._behavior_names["goal-1"] = "respond_owner_call"

    assert adapter.cancel_goal("goal-1") is True

    handle = _GoalHandle()
    adapter._on_goal_response("goal-1", _Future(handle))

    assert handle.cancel_requested is True
    assert handle.result_future.callback is not None

    handle.result_future.callback(handle.result_future)
    assert "goal-1" not in adapter._canceled_goal_ids
    assert "goal-1" not in adapter._behavior_names


def test_executor_behavior_name_can_use_compatibility_template():
    active = type("Active", (), {
        "behavior_name": "inspectTrashCan",
        "params": {"executor_behavior_name": "inspectKnownObject"},
    })()

    assert (
        ActionClientAdapter._executor_behavior_name(active)
        == "inspectKnownObject"
    )


def test_emotion_route_uses_executor_compatibility_template():
    active = type("Active", (), {
        "behavior_name": "expressJoyWithHuman",
        "params": {"executor_behavior_name": "expressJoy"},
    })()

    assert (
        ActionClientAdapter._executor_behavior_name(active)
        == "expressJoy"
    )


def test_executor_result_preserves_requested_behavior_name():
    adapter = _adapter()
    adapter._behavior_names["goal-1"] = "inspectTrashCan"
    result = type("Result", (), {
        "goal_id": "goal-1",
        "behavior_name": "inspectKnownObject",
        "status": "SUCCESS",
        "result": "completed",
        "reason": "",
        "reward": 1.0,
    })()
    wrapped = type("Wrapped", (), {"result": result})()

    adapter._on_result("goal-1", _Future(wrapped))
    completed = adapter.get_result("goal-1")

    assert completed.behavior_name == "inspectTrashCan"
