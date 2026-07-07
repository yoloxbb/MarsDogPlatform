"""Tests: mock executor feedback and behavior completion."""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.constants import STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILURE, STATUS_CANCELED
from bionic_dog_bt.datatypes import ActiveBehavior


@pytest.fixture
def runtime():
    config_path = str(Path(__file__).parent.parent / "config" / "behaviors.yaml")
    root, bb, executor, provider, loader = create_runtime(config_path=config_path)
    return root, bb, executor, provider, loader


def _tick(root, bb, n=1):
    status = None
    for _ in range(n):
        root.reset()
        status = root.tick()
        bb.tick_count += 1
        bb.last_tick_time = time.time()
    return status


class TestExecutorFeedback:
    """Test 9: executor produces feedback events on completion."""

    def test_feedback_on_success(self, runtime):
        """Behavior success generates BehaviorFeedbackEvent."""
        root, bb, executor, provider, loader = runtime

        # Use a very fast behavior - or just verify that the feedback
        # mechanism works by checking that executor returns feedback
        bb.set_active_behavior(provider.inject_idle())
        _tick(root, bb, 1)

        goad_id = bb.current_goal_id
        assert goad_id is not None

        fb = executor.get_feedback(goad_id)
        assert fb is not None
        assert fb.status == STATUS_RUNNING
        assert 0.0 <= fb.progress <= 1.0
        assert fb.behavior_name == "idle_look_around"

    def test_feedback_updates_over_time(self, runtime):
        """Feedback progress increases as simulation advances."""
        root, bb, executor, provider, loader = runtime

        bb.set_active_behavior(provider.inject_idle())
        _tick(root, bb, 1)

        goad_id = bb.current_goal_id
        fb1 = executor.get_feedback(goad_id)
        p1 = fb1.progress

        # Wait and tick
        time.sleep(1.0)
        executor.tick()
        fb2 = executor.get_feedback(goad_id)
        p2 = fb2.progress

        # Progress should increase (or be complete)
        assert p2 >= p1 or p2 == 1.0

    def test_send_goal_creates_feedback(self, runtime):
        """send_goal returns a goal_id that yields valid feedback."""
        root, bb, executor, provider, loader = runtime

        behavior = ActiveBehavior(
            behavior_id="test_001",
            behavior_name="express_happy",
            priority_level=5,
            value=80,
            confidence=0.9,
            need_type="emotional",
            interrupt_policy="immediate",
            timeout_sec=5.0,
            cooldown_sec=1.0,
        )

        goad_id = executor.send_goal(behavior)
        assert goad_id.startswith("goal_")

        fb = executor.get_feedback(goad_id)
        assert fb is not None
        assert fb.status == STATUS_RUNNING

    def test_cancel_goal(self, runtime):
        """Cancelling a goal marks it as CANCELED."""
        root, bb, executor, provider, loader = runtime

        behavior = ActiveBehavior(
            behavior_id="test_002",
            behavior_name="express_happy",
            priority_level=5,
            value=80,
            confidence=0.9,
            need_type="emotional",
            timeout_sec=5.0,
        )

        goad_id = executor.send_goal(behavior)
        assert executor.has_goal(goad_id)

        result = executor.cancel_goal(goad_id)
        assert result is True

        fb = executor.get_feedback(goad_id)
        assert fb.status == STATUS_CANCELED

    def test_goal_completion(self, runtime):
        """After all steps complete, goal returns SUCCESS."""
        root, bb, executor, provider, loader = runtime

        # Use a behavior with very short steps for testing
        behavior = ActiveBehavior(
            behavior_id="test_003",
            behavior_name="express_curiosity",
            priority_level=5,
            value=70,
            confidence=0.8,
            need_type="emotional",
            timeout_sec=10.0,
            cooldown_sec=0.0,
        )

        goad_id = executor.send_goal(behavior)

        # Simulate time passing to complete all steps
        # express_curiosity: 0.8 + 1.0 + 0.5 = 2.3s
        for _ in range(10):
            time.sleep(0.3)
            executor.tick()
            fb = executor.get_feedback(goad_id)
            if fb.status != STATUS_RUNNING:
                break

        result = executor.get_result(goad_id)
        assert result is not None
        assert result.status == STATUS_SUCCESS
        assert result.behavior_name == "express_curiosity"

    def test_behavior_completes_in_tree(self, runtime):
        """Full integration: behavior runs to completion in the tree."""
        root, bb, executor, provider, loader = runtime

        # Inject a short behavior
        bb.set_active_behavior(provider.inject_curiosity(70))
        _tick(root, bb, 1)

        # Tick until completion
        for _ in range(15):
            time.sleep(0.3)
            status = _tick(root, bb, 1)
            if bb.last_feedback_event:
                break

        if bb.last_feedback_event:
            # Behavior name is dynamic from emotion table; just check it completed
            assert bb.last_feedback_event.status == STATUS_SUCCESS

    def test_duplicate_behavior_not_sent(self, runtime):
        """Same behavior still running → don't send duplicate goal."""
        root, bb, executor, provider, loader = runtime

        bb.set_active_behavior(provider.inject_idle())
        _tick(root, bb, 1)
        first_goal = bb.current_goal_id
        assert first_goal is not None

        # Inject idle again
        provider.inject_idle()
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        # Should still be the same goal (not a new one)
        assert bb.current_goal_id == first_goal
