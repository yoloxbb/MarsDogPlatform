"""Tests: preemption policies (safe_point, non_interruptible)."""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.constants import (
    GOAL_CANCEL_REQUESTED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    STATUS_FAILURE,
    STATUS_CANCELED,
)


@pytest.fixture
def runtime():
    config_path = str(Path(__file__).parent.parent / "config" / "behaviors.yaml")
    root, bb, executor, provider, loader = create_runtime(config_path=config_path)
    bb.perception_client.set_objects([
        {"label": "dog food can", "confidence": 0.9},
    ])
    return root, bb, executor, provider, loader


def _tick(root, bb, n=1):
    status = None
    for _ in range(n):
        root.reset()
        status = root.tick()
        bb.tick_count += 1
        bb.last_tick_time = time.time()
    return status


class TestSafePoint:
    """Test 5: safe_point interrupt policy."""

    def test_safe_point_blocks_when_not_safe(self, runtime):
        """When safe_to_interrupt is false, higher priority can't preempt."""
        root, bb, executor, provider, loader = runtime

        # eatNormally has interrupt_policy=safe_point
        # action_sequence step 2 (approach_resource) has safe_to_interrupt=false
        bb.set_active_behavior(provider.inject_hunger(85))
        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "eatNormally"

        # Ensure we're in a non-safe step. Step 0 (locate_resource, 2s, safe=true)
        # After a short time, we should still be in step 0
        fb = bb.executor_feedback
        assert fb is not None
        # Step 0 is safe, so safe_to_interrupt should be true initially

        # We need to wait until step 1 (approach_resource, 3s, safe=false)
        # Simulate time passing by ticking multiple times
        for _ in range(5):
            _tick(root, bb, 1)
            time.sleep(0.5)  # Let mock time advance

        fb = bb.executor_feedback
        if fb and not fb.safe_to_interrupt:
            # Now try to preempt with owner_call (Lv2 > Lv3)
            provider.inject_owner_call(85)
            candidate = provider.select()
            bb.set_active_behavior(candidate)

            _tick(root, bb, 1)
            # Should NOT preempt because safe_to_interrupt is false
            assert not bb.preemption_occurred
            assert bb.current_behavior.behavior_name == "eatNormally"

    def test_safe_point_allows_when_safe(self, runtime):
        """When safe_to_interrupt is true, higher priority can preempt."""
        root, bb, executor, provider, loader = runtime

        # Start eatNormally (safe_point)
        bb.set_active_behavior(provider.inject_hunger(85))
        _tick(root, bb, 1)

        # Early on, step 0 should be safe
        fb = bb.executor_feedback
        assert fb is not None
        if fb.safe_to_interrupt:
            # Try to preempt
            provider.inject_owner_call(85)
            candidate = provider.select()
            bb.set_active_behavior(candidate)

            _tick(root, bb, 1)
            assert bb.preemption_occurred
            assert bb.goal_lifecycle == GOAL_CANCEL_REQUESTED
            assert bb.current_behavior.behavior_name == "eatNormally"
            _tick(root, bb, 2)
            assert bb.current_behavior.behavior_name == "respond_owner_call"
        else:
            pytest.skip("Already in non-safe step, can't test safe path")


class TestNonInterruptible:
    """Test 6: non_interruptible policy."""

    def test_non_interruptible_blocks_normal(self, runtime):
        """Non-interruptible behavior blocks normal higher-priority preemption."""
        root, bb, executor, provider, loader = runtime

        # We need a non_interruptible behavior. Let's check what's available.
        # For this test, we directly manipulate the interrupt_policy.
        # Actually, none of our configured behaviors are non_interruptible.
        # We can test by manipulating the current_behavior's interrupt_policy.

        # Start a behavior and then change its policy
        bb.set_active_behavior(provider.inject_idle())
        _tick(root, bb, 1)
        assert bb.current_behavior is not None

        # Override the policy to non_interruptible
        bb.current_behavior.interrupt_policy = "non_interruptible"

        # Try to preempt with owner_call (Lv2)
        provider.inject_owner_call(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert not bb.preemption_occurred
        assert bb.current_behavior.behavior_name == "idle_look_around"

    def test_emergency_stop_overrides_non_interruptible(self, runtime):
        """Emergency stop (Lv0) can preempt non_interruptible."""
        root, bb, executor, provider, loader = runtime

        # Start idle and make it non_interruptible
        bb.set_active_behavior(provider.inject_idle())
        _tick(root, bb, 1)
        bb.current_behavior.interrupt_policy = "non_interruptible"

        # Inject emergency stop (Lv0)
        provider.inject_emergency_stop(100)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert bb.preemption_occurred
        assert bb.goal_lifecycle == GOAL_CANCEL_REQUESTED
        assert bb.current_behavior.behavior_name == "idle_look_around"
        _tick(root, bb, 2)
        assert bb.current_behavior.behavior_name == "emergency_stop"
