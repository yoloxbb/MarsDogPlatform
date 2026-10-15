"""Fault injection for Goal ownership, producer restarts and reordered inputs.

No ROS nodes, executors or hardware are started. Futures and side-effect ports
are faked; the Action adapter, BT action node and state callbacks are real.
"""
from __future__ import annotations

import json
import logging
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from bionic_dog_bt.actions import ExecuteActiveBehavior
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.blackboard import Blackboard
from bionic_dog_bt.constants import GOAL_RECOVERY_REQUIRED, GOAL_RUNNING, GOAL_TERMINAL
from bionic_dog_bt.datatypes import ActiveBehavior
from marsdog_behavior.action_client_adapter import ActionClientAdapter
from marsdog_behavior.result_event_mapper import ResultEventMapper
from marsdog_behavior.state_input_order import StateInputOrder
from marsdog_behavior import state_subscriptions as subscriptions


class Future:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error
        self.callback = None

    def result(self):
        if self.error:
            raise self.error
        return self.value

    def add_done_callback(self, callback):
        self.callback = callback

    def complete(self):
        self.callback(self)


def adapter_with_goal():
    adapter = ActionClientAdapter.__new__(ActionClientAdapter)
    adapter._node = NS(get_logger=lambda: logging.getLogger(__name__))
    adapter._lock = threading.Lock()
    for name in ("feedback_cache", "result_cache", "goal_handles", "bhv_to_goal",
                 "behavior_names", "goal_lifecycle", "send_futures", "result_futures",
                 "cancel_futures", "recovery"):
        setattr(adapter, "_" + name, {})
    adapter._bhv_to_goal["old-goal"] = "old-goal"
    adapter._behavior_names["old-goal"] = "follow_owner"
    adapter._goal_lifecycle["old-goal"] = GOAL_RUNNING
    return adapter


def terminal(status=4):
    return NS(status=status, result=NS(
        goal_id="server-id", behavior_name="executor_alias", status="SUCCESS",
        result="completed", reason="real server result", reward=1.0,
        metadata_json='{"stop_confirmed": true}',
    ))


class ActionOwnershipTests(unittest.TestCase):
    def test_dispatch_exception_is_unknown_and_never_resends_motion_goal(self):
        adapter = adapter_with_goal()
        adapter._action_type = NS(Goal=NS)
        adapter._client = NS(server_is_ready=Mock(return_value=True),
                             send_goal_async=Mock(side_effect=RuntimeError("send failed")))
        active = NS(behavior_id="dispatch-goal", behavior_name="follow_owner",
                    priority_level=3, params={}, timeout_sec=0)
        with patch("marsdog_behavior.action_client_adapter.HAS_ROS2", True):
            goal_id = adapter.send_goal(active)
        for _ in range(3):
            adapter.tick()
        adapter._client.send_goal_async.assert_called_once()
        self.assertEqual(adapter.get_goal_lifecycle(goal_id), GOAL_RECOVERY_REQUIRED)
        self.assertIsNone(adapter.get_result(goal_id))
        adapter.remove_goal(goal_id)
        self.assertTrue(adapter.has_goal(goal_id))

    def test_transport_failure_never_releases_goal_or_dispatches_replacement(self):
        adapter = adapter_with_goal()
        adapter._on_result("old-goal", Future(error=RuntimeError("lost response")))
        adapter.remove_goal("old-goal")
        self.assertTrue(adapter.has_goal("old-goal"))
        self.assertEqual(adapter.get_goal_lifecycle("old-goal"), GOAL_RECOVERY_REQUIRED)
        self.assertIsNone(adapter.get_result("old-goal"))
        bb = Blackboard()
        bb.start_behavior(ActiveBehavior(
            behavior_id="old-goal", behavior_name="follow_owner", priority_level=3,
            value=50, confidence=1, need_type="external", timeout_sec=0,
            interrupt_policy="immediate",
        ), "old-goal")
        bb.active_behavior = ActiveBehavior(
            behavior_id="replacement", behavior_name="emergency_stop", priority_level=0,
            value=100, confidence=1, need_type="external", timeout_sec=0,
        )
        adapter.send_goal = Mock(side_effect=AssertionError("must retain old Goal"))
        action = ExecuteActiveBehavior("fault-test", bb, adapter)
        for _ in range(3):
            self.assertEqual(action.update(), Status.RUNNING)
        self.assertEqual(bb.current_goal_id, "old-goal")
        self.assertIsNone(bb.last_feedback_event)
        self.assertTrue(adapter.get_recovery_status("old-goal")["cancel_requested"])
        adapter.send_goal.assert_not_called()

    def test_retry_only_queries_result_and_consumes_real_terminal_once(self):
        adapter = adapter_with_goal()
        failed = Future(error=RuntimeError("transport"))
        recovered = Future(terminal())
        handle = NS(get_result_async=Mock(return_value=recovered))
        adapter._goal_handles["old-goal"] = handle
        with patch("marsdog_behavior.action_client_adapter.time.monotonic", return_value=10):
            adapter._on_result("old-goal", failed)
            adapter.tick()
        handle.get_result_async.assert_not_called()
        with patch("marsdog_behavior.action_client_adapter.time.monotonic", return_value=11):
            adapter.tick()
            adapter.tick()
        handle.get_result_async.assert_called_once_with()
        adapter._on_result("old-goal", failed)  # Superseded callback.
        recovered.complete()
        self.assertEqual(adapter.get_goal_lifecycle("old-goal"), GOAL_TERMINAL)
        result = adapter.get_result("old-goal")
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.behavior_id, "old-goal")
        self.assertEqual(result.behavior_name, "follow_owner")
        self.assertTrue(result.metadata["stop_confirmed"])
        self.assertIsNone(adapter.get_recovery_status("old-goal"))
        recovered.complete()
        self.assertIsNone(adapter.get_result("old-goal"))
        adapter.remove_goal("old-goal")
        adapter._on_result("old-goal", failed)
        recovered.complete()
        self.assertFalse(adapter.has_goal("old-goal"))
        self.assertIsNone(adapter.get_goal_lifecycle("old-goal"))

    def test_unknown_response_retains_cancel_intent_for_late_handle(self):
        adapter = adapter_with_goal()
        adapter._on_goal_response("old-goal", Future(error=RuntimeError("response lost")))
        self.assertTrue(adapter.cancel_goal("old-goal"))
        adapter.tick()  # No handle: must not resend the Goal.
        pending = Future(terminal())
        handle = NS(accepted=True, get_result_async=Mock(return_value=pending),
                    cancel_goal_async=Mock(return_value=Future()))
        adapter._on_goal_response("old-goal", Future(handle))
        handle.cancel_goal_async.assert_called_once_with()
        self.assertEqual(adapter.get_goal_lifecycle("old-goal"), GOAL_RECOVERY_REQUIRED)
        self.assertIsNone(adapter.get_result("old-goal"))
        pending.complete()
        self.assertEqual(adapter.get_result("old-goal").status, "SUCCESS")

    def test_query_creation_failure_and_ros_unknown_status_are_not_terminal(self):
        for handle in (
            NS(get_result_async=Mock(side_effect=RuntimeError("query failed"))),
            NS(get_result_async=Mock(return_value=Future(terminal(status=0)))),
        ):
            with self.subTest(handle=handle):
                adapter = adapter_with_goal()
                adapter._query_result("old-goal", handle)
                pending = adapter._result_futures.get("old-goal")
                if pending:
                    pending.complete()
                self.assertEqual(adapter.get_goal_lifecycle("old-goal"), GOAL_RECOVERY_REQUIRED)
                self.assertIsNone(adapter.get_result("old-goal"))
                adapter.remove_goal("old-goal")
                self.assertTrue(adapter.has_goal("old-goal"))

    def test_definite_rejection_still_finishes(self):
        adapter = adapter_with_goal()
        adapter._on_goal_response("old-goal", Future(NS(accepted=False)))
        self.assertEqual(adapter.get_result("old-goal").status, "FAILURE")
        adapter.remove_goal("old-goal")
        self.assertFalse(adapter.has_goal("old-goal"))


class ResultIdentityTests(unittest.TestCase):
    def test_restart_and_started_terminal_events_have_distinct_opaque_ids(self):
        first, restarted = ResultEventMapper(), ResultEventMapper()
        payloads = [first.build_started_event("eatNormally"),
                    first.build_result_event("eatNormally", "SUCCESS"),
                    restarted.build_result_event("eatNormally", "SUCCESS")]
        events = [json.loads(payload) for payload in payloads]
        self.assertEqual(len({event["event_id"] for event in events}), 3)
        for event in events:
            self.assertEqual(set(event), {"event_id", "timestamp", "action_type",
                                         "demand_type", "result_type", "metadata"})
        self.assertEqual(json.loads(payloads[-1])["event_id"], restarted.last_published_event_id)


def state_node():
    return NS(
        _logger=logging.getLogger(__name__), _blackboard=Blackboard(),
        _candidate_pool=NS(discard_emotion=Mock(), discard_need_except=Mock()),
        _invalidate_emotion_visual_request=Mock(), _stop_emotion_continuation=Mock(),
        _start_emotion_continuation=Mock(), _request_contextual_emotion_candidate=Mock(),
        _invalidate_need_visual_request=Mock(), _request_contextual_need_candidate=Mock(),
        _generate_need_candidate=Mock(), _pending_emotion_edges={},
        _pending_emotion_retry_at={}, _last_logged_emotion_state=None,
        _last_logged_need_state=None,
    )


def emotion_snapshot(stamp, triggered=False):
    return {"schema_version": "2.0", "timestamp": stamp, "emotions": {"Joy": {
        "value": 80 if triggered else 10, "triggered": triggered,
        "triggerThreshold": 70, "triggerOperator": "gte",
    }}}


def emotion_signal(stamp):
    return {"schema_version": "2.0", "timestamp": stamp,
            "event_type": "EMO_JOY_TRIGGERED", "emotion": "Joy", "value": 80,
            "triggerThreshold": 70, "triggerOperator": "gte"}


def need_snapshot(stamp):
    return {"schema_version": "2.0", "timestamp": stamp, "demands": {"Hunger": {
        "value": 10, "level": "NORMAL", "levelEvent": "NEED_HUNGER_RECOVERED",
        "triggered": False, "urgent": False, "overflow": False, "levelActive": False,
        "triggerThreshold": 70, "triggerOperator": "gt",
        "urgentThreshold": None, "urgentOperator": None,
        "overflowThreshold": 90, "overflowOperator": "gt",
    }}}


def need_signal(stamp):
    return {"schema_version": "2.0", "timestamp": stamp,
            "event_type": "NEED_HUNGER_TRIGGERED", "demand": "Hunger", "value": 80,
            "level": "TRIGGERED", "previousLevel": "NORMAL", "trigger": "LEVEL_CHANGED",
            "triggerThreshold": 70, "triggerOperator": "gt",
            "urgentThreshold": None, "urgentOperator": None,
            "overflowThreshold": 90, "overflowOperator": "gt"}


def deliver(callback, node, payload):
    callback(node, NS(data=json.dumps(payload)))


class InputOrderTests(unittest.TestCase):
    def test_emotion_recovery_blocks_old_signal_but_accepts_new_edge(self):
        node = state_node()
        deliver(subscriptions.on_emotion_state_ros2, node, emotion_snapshot(200))
        deliver(subscriptions.on_emotion_signal_ros2, node, emotion_signal(100))
        self.assertFalse(node._blackboard.emotion_module.is_triggered("Joy"))
        node._request_contextual_emotion_candidate.assert_not_called()
        deliver(subscriptions.on_emotion_signal_ros2, node, emotion_signal(201))
        self.assertTrue(node._blackboard.emotion_module.is_triggered("Joy"))
        node._request_contextual_emotion_candidate.assert_called_once()

    def test_emotion_signal_blocks_old_snapshot(self):
        node = state_node()
        deliver(subscriptions.on_emotion_signal_ros2, node, emotion_signal(200))
        deliver(subscriptions.on_emotion_state_ros2, node, emotion_snapshot(100))
        self.assertTrue(node._blackboard.emotion_module.is_triggered("Joy"))
        node._stop_emotion_continuation.assert_not_called()

    def test_invalid_new_snapshot_does_not_advance_watermark(self):
        node = state_node()
        invalid = emotion_snapshot(300)
        invalid["emotions"]["Fear"] = {"value": "bad"}
        deliver(subscriptions.on_emotion_state_ros2, node, invalid)
        deliver(subscriptions.on_emotion_signal_ros2, node, emotion_signal(200))
        self.assertTrue(node._blackboard.emotion_module.is_triggered("Joy"))
        node._request_contextual_emotion_candidate.assert_called_once()

    def test_need_state_and_signal_share_watermark_in_both_directions(self):
        node = state_node()
        deliver(subscriptions.on_need_state_ros2, node, need_snapshot(200))
        self.assertEqual(node._blackboard.need_module.get_level("Hunger"), "NORMAL")
        deliver(subscriptions.on_need_signal_ros2, node, need_signal(100))
        self.assertFalse(node._blackboard.need_module.is_triggered("Hunger"))
        node._request_contextual_need_candidate.assert_not_called()
        deliver(subscriptions.on_need_signal_ros2, node, need_signal(201))
        deliver(subscriptions.on_need_state_ros2, node, need_snapshot(200))
        self.assertTrue(node._blackboard.need_module.is_triggered("Hunger"))
        node._request_contextual_need_candidate.assert_called_once()

    def test_channel_isolation_equal_time_and_legacy_messages(self):
        guard = StateInputOrder()
        self.assertTrue(guard.accept("emotion", "Joy", {"timestamp": 200}))
        self.assertTrue(guard.accept("emotion", "Fear", {"timestamp": 100}))
        self.assertTrue(guard.accept("need", "Hunger", {"timestamp": 100}))
        self.assertTrue(guard.accept("emotion", "Joy", {"timestamp": 200}))
        self.assertTrue(guard.accept("emotion", "Joy", {}))
        self.assertFalse(guard.accept("emotion", "Joy", {"timestamp": 199}))
        for invalid in (True, "300", float("nan"), float("inf")):
            self.assertFalse(guard.accept("emotion", "Joy", {"timestamp": invalid}))
        self.assertTrue(guard.accept("emotion", "Joy", {"timestamp": 201}))


if __name__ == "__main__":
    unittest.main()
