"""Regression tests for the transport/runtime architecture boundary."""

from __future__ import annotations

import time
from pathlib import Path

from bionic_dog_bt.blackboard import Blackboard
from bionic_dog_bt.mock_action_executor import MockActionExecutor
from bionic_dog_bt.yaml_loader import YAMLLoader
from marsdog_behavior.candidate_pool import CandidatePool
from marsdog_behavior.intent_mapper import BehaviorCandidate
from marsdog_behavior.runtime import BehaviorRuntime


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


def test_runtime_reports_timeout_as_terminal_event():
    config_path = (
        Path(__file__).resolve().parents[2] / "config" / "behaviors.yaml"
    )
    runtime = BehaviorRuntime(
        MockActionExecutor(YAMLLoader(str(config_path)))
    )
    runtime.candidate_pool.add(
        "respond_owner_call",
        1,
        need_type="external",
        timeout_sec=0.01,
    )
    runtime.tick()
    runtime.blackboard._behavior_start_time = time.time() - 1.0

    outcome = runtime.tick()

    assert outcome.completed_event is not None
    assert outcome.completed_event.status == "TIMEOUT"


def test_runtime_reports_interrupted_event_before_replacement():
    config_path = (
        Path(__file__).resolve().parents[2] / "config" / "behaviors.yaml"
    )
    runtime = BehaviorRuntime(
        MockActionExecutor(YAMLLoader(str(config_path)))
    )
    runtime.candidate_pool.add(
        "respond_owner_call",
        5,
        need_type="external",
        interrupt_policy="immediate",
    )
    runtime.tick()
    runtime.candidate_pool.add(
        "emergency_stop",
        0,
        need_type="system",
    )

    outcome = runtime.tick()

    assert outcome.completed_event is not None
    assert outcome.completed_event.status == "CANCELED"
    assert outcome.completed_event.behavior_name == "respond_owner_call"
    assert outcome.started_behavior is not None
    assert outcome.started_behavior.behavior_name == "emergency_stop"
    assert runtime.blackboard.current_behavior is not None
    assert runtime.blackboard.current_behavior.behavior_name == "emergency_stop"
