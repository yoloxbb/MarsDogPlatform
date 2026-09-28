"""Regression tests for the transport/runtime architecture boundary."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from bionic_dog_bt.arbitration import evaluate_preemption
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.blackboard import Blackboard
from bionic_dog_bt.constants import (
    GOAL_CANCEL_REQUESTED,
    GOAL_RUNNING,
    GOAL_TERMINAL,
)
from bionic_dog_bt.datatypes import BehaviorFeedbackEvent, ExecutorFeedback
from bionic_dog_bt.mock_action_executor import MockActionExecutor
from bionic_dog_bt.yaml_loader import YAMLLoader
from marsdog_behavior.candidate_pool import CandidatePool
from marsdog_behavior.execution_manager import ExecutionManager
from marsdog_behavior.intent_mapper import BehaviorCandidate
from marsdog_behavior.runtime import BehaviorRuntime


class _DeferredExecutor:
    """Executor whose cancel response and terminal Result are independent."""

    def __init__(self):
        self.sent = []
        self.cancel_requests = []
        self.removed = []
        self.lifecycle = {}
        self.feedback = {}
        self.results = {}

    def send_goal(self, active):
        goal_id = active.behavior_id
        self.sent.append(goal_id)
        self.lifecycle[goal_id] = GOAL_RUNNING
        self.feedback[goal_id] = ExecutorFeedback(
            behavior_id=active.behavior_id,
            behavior_name=active.behavior_name,
            status="RUNNING",
            progress=0.1,
            safe_to_interrupt=True,
        )
        return goal_id

    def cancel_goal(self, goal_id):
        self.cancel_requests.append(goal_id)
        self.lifecycle[goal_id] = GOAL_CANCEL_REQUESTED
        return True

    def tick(self):
        pass

    def get_feedback(self, goal_id):
        return self.feedback.get(goal_id)

    def get_result(self, goal_id):
        return self.results.pop(goal_id, None)

    def remove_goal(self, goal_id):
        if self.lifecycle.get(goal_id) != GOAL_TERMINAL:
            return
        self.removed.append(goal_id)
        self.lifecycle.pop(goal_id, None)
        self.feedback.pop(goal_id, None)

    def has_goal(self, goal_id):
        return goal_id in self.lifecycle

    def get_goal_lifecycle(self, goal_id):
        return self.lifecycle.get(goal_id)

    def set_feedback(self, goal_id, *, safe, status="RUNNING"):
        current = self.feedback[goal_id]
        self.feedback[goal_id] = ExecutorFeedback(
            behavior_id=current.behavior_id,
            behavior_name=current.behavior_name,
            status=status,
            progress=current.progress,
            safe_to_interrupt=safe,
        )

    def complete(self, goal_id, status):
        current = self.feedback[goal_id]
        self.lifecycle[goal_id] = GOAL_TERMINAL
        self.results[goal_id] = BehaviorFeedbackEvent(
            behavior_id=current.behavior_id,
            behavior_name=current.behavior_name,
            status=status,
            result=status.lower(),
            reason="real Action result",
        )


def _deferred_runtime():
    executor = _DeferredExecutor()
    runtime = BehaviorRuntime(executor)
    runtime.candidate_pool.add(
        "old_navigation",
        5,
        candidate_id="old-goal",
        interrupt_policy="immediate",
        ttl_sec=0.0,
    )
    started = runtime.tick()
    assert started.started_behavior is not None
    return runtime, executor


def _queue_replacement(runtime, *, name="new_navigation", priority=1):
    assert runtime.candidate_pool.add(
        name,
        priority,
        candidate_id=f"{name}-goal",
        ttl_sec=0.0,
    )


def test_candidate_metadata_survives_queue_and_runtime_conversion():
    candidate = BehaviorCandidate(
        behavior_name="respond_owner_call",
        source="audio_direct",
        trigger_event="EVT_VOICE_COMMAND_SIT",
        intent="command_sit",
        priority_level=1,
        intensity=0.0,
        interrupt_policy="safe_point",
        ttl_sec=4.0,
    )
    pool = CandidatePool()

    assert pool.add(**candidate.to_pool_dict())
    queued = pool.select_best(Blackboard())
    active = BehaviorRuntime.candidate_to_active_behavior(queued)

    assert queued["value"] == 0.0
    assert active.behavior_id == candidate.candidate_id
    assert active.interrupt_policy == "safe_point"
    assert queued["ttl_sec"] == 4.0
    assert active.created_at == candidate.created_at


def test_candidate_pool_preserves_non_selected_candidates():
    pool = CandidatePool()
    blackboard = Blackboard()
    pool.add("low_priority", 5, dedup_key=("low",))
    pool.add("high_priority", 1, dedup_key=("high",))

    selected = pool.select_best(blackboard)

    assert selected["behavior_name"] == "high_priority"
    assert [item["behavior_name"] for item in pool.candidates] == ["low_priority"]


def test_runtime_candidate_gate_keeps_blocked_work_queued():
    interaction_active = True
    config_path = (
        Path(__file__).resolve().parents[2] / "config" / "behaviors.yaml"
    )
    runtime = BehaviorRuntime(
        MockActionExecutor(YAMLLoader(str(config_path))),
        candidate_gate=lambda candidate: (
            not interaction_active or candidate["priority_level"] <= 1
        ),
    )
    runtime.candidate_pool.add(
        "expressCalmAlone",
        5,
        dedup_key=("emotion", "calm"),
    )

    assert runtime._can_run_candidate_now(
        runtime.candidate_pool.candidates[0]
    ) is False
    assert runtime.candidate_pool.select_best(
        runtime.blackboard,
        can_run=runtime._can_run_candidate_now,
    ) is None
    assert runtime.candidate_pool.size() == 1

    interaction_active = False
    selected = runtime.candidate_pool.select_best(
        runtime.blackboard,
        can_run=runtime._can_run_candidate_now,
    )
    assert selected["behavior_name"] == "expressCalmAlone"


def test_same_behavior_name_is_unique_across_different_event_keys():
    pool = CandidatePool()

    assert pool.add(
        "shared_behavior",
        4,
        dedup_key=("need", "NEED_SOCIAL_TRIGGERED"),
    ) is True
    assert pool.add(
        "shared_behavior",
        1,
        dedup_key=("audio_direct", "EVT_VOICE_COMMAND_TEST"),
    ) is False
    assert pool.size() == 1


def test_allow_repeat_never_bypasses_queued_or_inflight_uniqueness():
    pool = CandidatePool()
    blackboard = Blackboard()

    assert pool.add(
        "expressCalmAlone",
        5,
        candidate_id="calm-1",
        dedup_key=("emotion", "calm", "first"),
        allow_repeat=True,
    ) is True
    assert pool.add(
        "expressCalmAlone",
        5,
        dedup_key=("emotion", "calm", "queued-repeat"),
        allow_repeat=True,
    ) is False

    selected = pool.select_best(blackboard)
    assert selected["candidate_id"] == "calm-1"
    assert pool.is_inflight("expressCalmAlone")
    assert pool.add(
        "expressCalmAlone",
        5,
        dedup_key=("emotion", "calm", "running-repeat"),
        allow_repeat=True,
    ) is False

    assert pool.release_inflight("expressCalmAlone", "stale-id") is False
    assert pool.is_inflight("expressCalmAlone")
    assert pool.release_inflight("expressCalmAlone", "calm-1") is True
    assert pool.add(
        "expressCalmAlone",
        5,
        dedup_key=("emotion", "calm", "after-terminal"),
        allow_repeat=True,
    ) is True


def test_candidate_pool_discards_expired_candidates():
    pool = CandidatePool()
    pool.add(
        "expired",
        1,
        ttl_sec=0.1,
        created_at=time.time() - 1.0,
        dedup_key=("expired",),
    )

    assert pool.select_best(Blackboard()) is None
    assert pool.size() == 0


def test_expired_candidate_does_not_block_same_event():
    pool = CandidatePool()
    dedup_key = ("audio_direct", "EVT_VOICE_COMMAND_SIT")
    pool.add(
        "respond_owner_call",
        1,
        ttl_sec=0.1,
        created_at=time.time() - 1.0,
        dedup_key=dedup_key,
    )

    assert pool.is_duplicate("respond_owner_call", dedup_key) is False
    assert pool.add(
        "respond_owner_call",
        1,
        dedup_key=dedup_key,
    ) is True


def test_candidate_in_cooldown_remains_queued():
    pool = CandidatePool()
    blackboard = Blackboard()
    blackboard.set_cooldown("waiting", 5.0)
    pool.add("waiting", 1, ttl_sec=10.0)

    assert pool.select_best(blackboard) is None
    assert pool.size() == 1


def test_allow_repeat_still_respects_post_completion_cooldown():
    pool = CandidatePool()
    blackboard = Blackboard()
    blackboard.set_cooldown("repeatable", 5.0)
    pool.add("repeatable", 5, allow_repeat=True)

    assert pool.select_best(blackboard) is None
    assert pool.size() == 1


def test_candidate_blocked_by_runtime_predicate_remains_queued():
    pool = CandidatePool()
    blackboard = Blackboard()
    pool.add("deferred", 3, ttl_sec=0.0, dedup_key=("need", "Hunger"))

    assert pool.select_best(
        blackboard,
        can_run=lambda candidate: False,
    ) is None
    assert pool.size() == 1
    assert pool.candidates[0]["behavior_name"] == "deferred"


def test_runtime_reports_a_behavior_start_only_once():
    config_path = (
        Path(__file__).resolve().parents[2] / "config" / "behaviors.yaml"
    )
    executor = MockActionExecutor(YAMLLoader(str(config_path)))
    runtime = BehaviorRuntime(executor)
    runtime.candidate_pool.add(
        "respond_owner_call",
        1,
        value=95.0,
        need_type="external",
        candidate_id="candidate-1",
    )

    first = runtime.tick()
    second = runtime.tick()

    assert first.started_behavior is not None
    assert first.started_behavior.behavior_id == "candidate-1"
    assert second.started_behavior is None
    assert runtime.candidate_pool.is_inflight("respond_owner_call")
    assert runtime.candidate_pool.add(
        "respond_owner_call",
        1,
        dedup_key=("another", "event"),
        allow_repeat=True,
    ) is False


def test_runtime_releases_selected_candidate_that_was_not_dispatched():
    class _RejectingTree:
        def reset(self):
            pass

        def tick(self):
            return Status.FAILURE

    config_path = (
        Path(__file__).resolve().parents[2] / "config" / "behaviors.yaml"
    )
    runtime = BehaviorRuntime(
        MockActionExecutor(YAMLLoader(str(config_path)))
    )
    runtime.tree = _RejectingTree()
    runtime.candidate_pool.add(
        "respond_owner_call",
        1,
        candidate_id="not-dispatched",
    )

    outcome = runtime.tick()

    assert outcome.started_behavior is None
    assert not runtime.candidate_pool.is_inflight("respond_owner_call")
    assert runtime.candidate_pool.add("respond_owner_call", 1) is True


def test_runtime_timeout_stays_cancel_requested_until_real_result():
    runtime, executor = _deferred_runtime()
    runtime.blackboard.current_behavior.timeout_sec = 0.01
    runtime.blackboard._behavior_start_time = time.time() - 1.0

    outcome = runtime.tick()

    assert outcome.completed_event is None
    assert runtime.blackboard.timeout_requested is True
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
    assert runtime.blackboard.current_goal_id == "old-goal"
    assert runtime.candidate_pool.is_inflight("old_navigation")
    assert executor.cancel_requests == ["old-goal"]


def test_cancel_ack_without_result_does_not_start_replacement():
    runtime, executor = _deferred_runtime()
    _queue_replacement(runtime)

    outcome = runtime.tick()

    assert outcome.completed_event is None
    assert outcome.started_behavior is None
    assert executor.sent == ["old-goal"]
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
    assert runtime.blackboard.current_goal_id == "old-goal"
    assert runtime.blackboard.active_behavior.behavior_id == "new_navigation-goal"
    assert runtime.candidate_pool.is_inflight("old_navigation")
    assert runtime.candidate_pool.is_inflight("new_navigation")

    second = runtime.tick()
    assert second.completed_event is None
    assert executor.sent == ["old-goal"]


@pytest.mark.parametrize("status", ["CANCELED", "SUCCESS", "FAILURE"])
def test_cancel_then_real_terminal_result_is_authoritative(status):
    runtime, executor = _deferred_runtime()
    _queue_replacement(runtime)
    runtime.tick()

    executor.complete("old-goal", status)
    terminal = runtime.tick()

    assert terminal.completed_event is not None
    assert terminal.completed_event.status == status
    assert terminal.completed_event.reason == "real Action result"
    assert "old-goal" in executor.removed
    assert not runtime.candidate_pool.is_inflight("old_navigation")
    assert executor.sent == ["old-goal"]

    started = runtime.tick()
    assert started.started_behavior is not None
    assert started.started_behavior.behavior_id == "new_navigation-goal"
    assert executor.sent == ["old-goal", "new_navigation-goal"]


def test_safe_to_interrupt_false_keeps_candidate_queued():
    runtime, executor = _deferred_runtime()
    executor.set_feedback("old-goal", safe=False)
    runtime.tick()
    _queue_replacement(runtime)

    outcome = runtime.tick()

    assert outcome.selected_candidate is None
    assert executor.cancel_requests == []
    assert executor.sent == ["old-goal"]
    assert runtime.candidate_pool.size() == 1


@pytest.mark.parametrize("feedback_status", ["DISPATCHED", "RECOVERY_REQUIRED"])
def test_non_interruptible_feedback_status_blocks_normal_preemption(
    feedback_status,
):
    runtime, executor = _deferred_runtime()
    executor.set_feedback(
        "old-goal",
        safe=True,
        status=feedback_status,
    )
    runtime.tick()
    _queue_replacement(runtime)

    outcome = runtime.tick()

    assert outcome.selected_candidate is None
    assert executor.cancel_requests == []
    assert runtime.blackboard.current_goal_id == "old-goal"
    assert runtime.candidate_pool.size() == 1


def test_emergency_cancel_ack_does_not_release_navigation_lock():
    runtime, executor = _deferred_runtime()
    executor.set_feedback("old-goal", safe=False, status="RECOVERY_REQUIRED")
    runtime.tick()
    _queue_replacement(runtime, name="emergency_stop", priority=0)

    outcome = runtime.tick()

    assert outcome.started_behavior is None
    assert executor.cancel_requests == ["old-goal"]
    assert executor.sent == ["old-goal"]
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
    assert runtime.candidate_pool.is_inflight("old_navigation")


def test_late_old_goal_result_cannot_clear_new_goal():
    runtime, executor = _deferred_runtime()
    _queue_replacement(runtime)
    runtime.tick()
    executor.complete("old-goal", "CANCELED")
    runtime.tick()
    runtime.tick()
    assert runtime.blackboard.current_goal_id == "new_navigation-goal"

    executor.results["old-goal"] = BehaviorFeedbackEvent(
        behavior_id="old-goal",
        behavior_name="old_navigation",
        status="SUCCESS",
        result="late",
        reason="duplicate late callback",
    )
    outcome = runtime.tick()

    assert outcome.completed_event is None
    assert runtime.blackboard.current_goal_id == "new_navigation-goal"
    assert runtime.blackboard.current_behavior.behavior_id == "new_navigation-goal"


def test_cancel_current_interaction_waits_for_real_result():
    runtime, executor = _deferred_runtime()
    runtime.blackboard.current_behavior.params["interaction_id"] = "voice-1"

    requested = runtime.cancel_current_interaction(
        "voice-1",
        reason="session closed",
    )

    assert requested is True
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
    assert runtime.blackboard.current_goal_id == "old-goal"
    assert runtime.candidate_pool.is_inflight("old_navigation")
    assert runtime.blackboard.last_feedback_event is None


def test_voice_idle_keeps_behavior_scoped_emotion_goal_running():
    runtime, executor = _deferred_runtime()
    runtime.blackboard.current_behavior.params.update({
        "interaction_id": "voice-1",
        "lifecycle_scope": "behavior",
    })

    requested = runtime.cancel_current_interaction(
        "voice-1", reason="voice_idle",
    )

    assert requested is False
    assert runtime.blackboard.current_goal_id == "old-goal"
    assert runtime.candidate_pool.is_inflight("old_navigation")
    assert runtime.blackboard.goal_lifecycle != GOAL_CANCEL_REQUESTED


@pytest.mark.parametrize("behavior_name", ["follow_owner", "play_alone"])
def test_voice_idle_keeps_long_goal_running_without_tree_timeout(behavior_name):
    executor = _DeferredExecutor()
    runtime = BehaviorRuntime(executor)
    assert runtime.candidate_pool.add(
        behavior_name, 1,
        candidate_id="long-goal",
        timeout_sec=0.0,
        params={
            "interaction_id": "voice-1",
            "lifecycle_scope": "behavior",
            "completion_policy": "until_preempted",
            "cancel_on_voice_idle": False,
        },
    )
    runtime.tick()
    runtime.blackboard._behavior_start_time -= 1000.0

    assert runtime.cancel_current_interaction("voice-1", reason="voice_idle") is False
    assert runtime.tick().completed_event is None
    assert executor.cancel_requests == []
    assert runtime.blackboard.current_goal_id == "long-goal"
    assert runtime.blackboard.current_behavior.behavior_id == "long-goal"

    assert runtime.cancel_current_for_shutdown() is True
    assert executor.cancel_requests == ["long-goal"]
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED


@pytest.mark.parametrize(
    ("long_name", "long_event", "command_name", "command_event", "command_rank"),
    [
        ("follow_owner", "EVT_VOICE_COMMAND_FOLLOW",
         "lie_down", "EVT_VOICE_COMMAND_LIE_DOWN", 1),
        ("play_alone", "EVT_VOICE_COMMAND_PLAY_ALONE",
         "lie_down", "EVT_VOICE_COMMAND_LIE_DOWN", 9),
        ("follow_owner", "EVT_VOICE_COMMAND_FOLLOW",
         "play_alone", "EVT_VOICE_COMMAND_PLAY_ALONE", 9),
        ("play_alone", "EVT_VOICE_COMMAND_PLAY_ALONE",
         "follow_owner", "EVT_VOICE_COMMAND_FOLLOW", 1),
    ],
)
def test_voice_command_replaces_long_voice_goal_only_after_safe_result(
    long_name, long_event, command_name, command_event, command_rank,
):
    executor = _DeferredExecutor()
    runtime = BehaviorRuntime(executor)
    assert runtime.candidate_pool.add(
        long_name, 1, value=95.0,
        sub_priority=1, semantic_rank=1, modality_rank=1,
        candidate_id="old-goal", timeout_sec=0.0,
        params={
            "source": "audio_direct",
            "trigger_event": long_event,
            "completion_policy": "until_preempted",
            "interaction_id": "voice-1",
        },
    )
    runtime.tick()
    executor.set_feedback("old-goal", safe=False)
    runtime.tick()
    assert runtime.candidate_pool.add(
        command_name, 1, value=80.0,
        sub_priority=command_rank, semantic_rank=1, modality_rank=1,
        candidate_id="new-goal", ttl_sec=0.0,
        params={
            "source": "audio_direct",
            "trigger_event": command_event,
            "interaction_id": "voice-2",
        },
    )

    assert runtime.tick().selected_candidate is None
    assert executor.cancel_requests == []
    assert runtime.candidate_pool.size() == 1

    executor.set_feedback("old-goal", safe=True, status="RECOVERY_REQUIRED")
    runtime.tick()
    assert runtime.tick().selected_candidate is None
    assert executor.cancel_requests == []

    executor.set_feedback("old-goal", safe=True)
    # Runtime arbitrates against the last feedback already on its blackboard.
    runtime.tick()
    runtime.tick()
    assert executor.cancel_requests == ["old-goal"]
    assert executor.sent == ["old-goal"]
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
    assert runtime.blackboard.active_behavior.behavior_name == command_name

    executor.complete("old-goal", "CANCELED")
    runtime.tick()
    assert executor.sent == ["old-goal"]
    runtime.tick()
    assert executor.sent == ["old-goal", "new-goal"]


@pytest.mark.parametrize(
    ("long_name", "long_event"),
    [
        ("follow_owner", "EVT_VOICE_COMMAND_FOLLOW"),
        ("play_alone", "EVT_VOICE_COMMAND_PLAY_ALONE"),
    ],
)
def test_hardware_wake_replaces_long_voice_goal_only_after_safe_result(
    long_name, long_event,
):
    executor = _DeferredExecutor()
    runtime = BehaviorRuntime(executor)
    assert runtime.candidate_pool.add(
        long_name, 1, value=100.0,
        sub_priority=1, semantic_rank=1, modality_rank=1,
        candidate_id="old-goal", timeout_sec=0.0,
        params={
            "source": "audio_direct",
            "trigger_event": long_event,
            "completion_policy": "until_preempted",
            "interaction_id": "voice-1",
        },
    )
    runtime.tick()
    executor.set_feedback("old-goal", safe=False)
    runtime.tick()
    assert runtime.candidate_pool.add(
        "respond_owner_call", 1, value=80.0,
        sub_priority=1, semantic_rank=2, modality_rank=1,
        candidate_id="wake-goal", ttl_sec=0.0,
        params={
            "source": "audio_direct",
            "trigger_event": "EVT_VOICE_WAKEUP",
            "interaction_id": "voice-2",
            "session_role": "wake_orientation",
        },
    )

    assert runtime.tick().selected_candidate is None
    assert executor.cancel_requests == []
    assert runtime.candidate_pool.size() == 1

    executor.set_feedback("old-goal", safe=True, status="RECOVERY_REQUIRED")
    runtime.tick()
    assert runtime.tick().selected_candidate is None
    assert executor.cancel_requests == []

    executor.set_feedback("old-goal", safe=True)
    runtime.tick()
    runtime.tick()
    assert executor.cancel_requests == ["old-goal"]
    assert executor.sent == ["old-goal"]
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
    assert runtime.blackboard.active_behavior.behavior_name == "respond_owner_call"

    executor.complete("old-goal", "CANCELED")
    runtime.tick()
    assert executor.sent == ["old-goal"]
    runtime.tick()
    assert executor.sent == ["old-goal", "wake-goal"]


@pytest.mark.parametrize(
    ("active_source", "active_event", "active_name", "current_event", "policy"),
    [
        ("audio_reaction", "EVT_VOICE_WAKEUP", "respond_owner_call",
         "EVT_VOICE_COMMAND_FOLLOW", "until_preempted"),
        ("audio_direct", "EVT_VOICE_CALL_NAME", "respond_owner_call",
         "EVT_VOICE_COMMAND_FOLLOW", "until_preempted"),
        ("audio_direct", "EVT_VOICE_WAKEUP", "lie_down",
         "EVT_VOICE_COMMAND_FOLLOW", "until_preempted"),
        ("audio_direct", "EVT_VOICE_WAKEUP", "respond_owner_call",
         "EVT_VOICE_COMMAND_LIE_DOWN", "until_preempted"),
        ("audio_direct", "EVT_VOICE_WAKEUP", "respond_owner_call",
         "EVT_VOICE_COMMAND_FOLLOW", "bounded"),
    ],
)
def test_wake_override_is_limited_to_hardware_wake_and_long_follow_or_play(
    active_source, active_event, active_name, current_event, policy,
):
    allowed, _ = evaluate_preemption(
        1, 80.0, active_name,
        1, 100.0, "immediate",
        ExecutorFeedback(
            behavior_id="old-goal",
            behavior_name="follow_owner",
            status="RUNNING",
            safe_to_interrupt=True,
        ),
        {
            "source": active_source,
            "trigger_event": active_event,
            "semantic_rank": 2,
            "modality_rank": 1,
            "sub_priority": 1,
        },
        {
            "source": "audio_direct",
            "trigger_event": current_event,
            "completion_policy": policy,
            "semantic_rank": 1,
            "modality_rank": 1,
            "sub_priority": 1,
        },
    )
    assert allowed is False


@pytest.mark.parametrize(
    ("active_source", "active_event", "current_source", "current_event"),
    [
        ("audio_reaction", "EVT_VOICE_COMMAND_LIE_DOWN",
         "audio_direct", "EVT_VOICE_COMMAND_FOLLOW"),
        ("audio_direct", "EVT_VOICE_COMMAND_LIE_DOWN",
         "need", "EVT_VOICE_COMMAND_FOLLOW"),
        ("audio_direct", "EVT_VOICE_WAKEUP",
         "audio_direct", "EVT_VOICE_COMMAND_FOLLOW"),
    ],
)
def test_long_voice_override_rejects_non_command_or_non_voice_source(
    active_source, active_event, current_source, current_event,
):
    allowed, _ = evaluate_preemption(
        1, 80.0, "lie_down",
        1, 95.0, "immediate",
        ExecutorFeedback(
            behavior_id="old-goal",
            behavior_name="follow_owner",
            status="RUNNING",
            safe_to_interrupt=True,
        ),
        {
            "source": active_source,
            "trigger_event": active_event,
            "semantic_rank": 1,
            "modality_rank": 1,
            "sub_priority": 9,
        },
        {
            "source": current_source,
            "trigger_event": current_event,
            "completion_policy": "until_preempted",
            "semantic_rank": 1,
            "modality_rank": 1,
            "sub_priority": 1,
        },
    )
    assert allowed is False


def test_voice_idle_discards_only_session_owned_pending_replacement():
    runtime, executor = _deferred_runtime()
    _queue_replacement(runtime, name="voice_waiting", priority=1)
    runtime.tick()
    pending = runtime.blackboard.active_behavior
    assert pending is not None
    pending.params["interaction_id"] = "voice-1"

    assert runtime.discard_pending_interaction("voice-1") is True
    assert runtime.blackboard.active_behavior is None
    assert not runtime.candidate_pool.is_inflight("voice_waiting")
    assert runtime.blackboard.current_goal_id == "old-goal"
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
    assert executor.sent == ["old-goal"]


def test_visual_safety_preempts_long_voice_goal_after_real_result():
    executor = _DeferredExecutor()
    runtime = BehaviorRuntime(executor)
    assert runtime.candidate_pool.add(
        "follow_owner", 1, value=100.0,
        sub_priority=1, semantic_rank=1, modality_rank=1,
        candidate_id="follow-goal", timeout_sec=0.0,
        params={"completion_policy": "until_preempted"},
    )
    runtime.tick()
    assert runtime.candidate_pool.add(
        "respond_person_fall", 1, value=100.0,
        sub_priority=12, semantic_rank=0, modality_rank=2,
        candidate_id="fall-goal",
    )

    runtime.tick()
    assert executor.cancel_requests == ["follow-goal"]
    assert executor.sent == ["follow-goal"]
    assert runtime.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
    assert runtime.blackboard.current_behavior.behavior_name == "follow_owner"

    executor.complete("follow-goal", "CANCELED")
    runtime.tick()
    runtime.tick()
    assert executor.sent == ["follow-goal", "fall-goal"]


def test_safety_semantics_sort_before_sensor_source():
    pool = CandidatePool()
    assert pool.add(
        "respond_touch_back", 1, value=100.0,
        sub_priority=0, semantic_rank=3, modality_rank=0,
    )
    assert pool.add(
        "respond_person_fall", 1, value=100.0,
        sub_priority=12, semantic_rank=0, modality_rank=2,
    )
    assert pool.select_best(Blackboard())["behavior_name"] == (
        "respond_person_fall"
    )


def test_execution_manager_cancel_keeps_current_goal_until_result():
    executor = _DeferredExecutor()
    manager = ExecutionManager(executor)
    blackboard = Blackboard()
    active = BehaviorRuntime.candidate_to_active_behavior({
        "behavior_name": "managed_navigation",
        "priority_level": 3,
        "value": 50.0,
        "candidate_id": "managed-goal",
    })

    manager.send_goal(active, blackboard)
    assert manager.cancel_current(blackboard) is True
    assert manager.current_goal_id == "managed-goal"
    assert manager.has_active_goal()
    assert blackboard.current_goal_id == "managed-goal"
    assert blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED

    assert manager.tick(blackboard) is None
    assert manager.current_goal_id == "managed-goal"
    executor.complete("managed-goal", "SUCCESS")

    result = manager.tick(blackboard)
    assert result is not None
    assert result.status == "SUCCESS"
    assert manager.current_goal_id is None
    assert "managed-goal" in executor.removed
