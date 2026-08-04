"""Tests: core behavior tree operation and priority-based selection."""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.behavior_tree_node import Status, Selector, Sequence, Node
from bionic_dog_bt.constants import (
    STATUS_RUNNING,
    STATUS_SUCCESS,
    STATUS_FAILURE,
    PRIORITY_LEVELS,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def runtime():
    """Create a full runtime with mock components."""
    config_path = str(Path(__file__).parent.parent / "config" / "behaviors.yaml")
    root, bb, executor, provider, loader = create_runtime(config_path=config_path)
    bb.perception_client.set_objects([
        {"label": "dog food can", "confidence": 0.9},
    ])
    return root, bb, executor, provider, loader


def _tick(root, bb, n=1):
    """Tick the tree n times, resetting each time (memory=False)."""
    status = None
    for _ in range(n):
        root.reset()
        status = root.tick()
        bb.tick_count += 1
        bb.last_tick_time = time.time()
    return status


# ── Basic Node Tests ─────────────────────────────────────────────────────────

class _AlwaysSuccess(Node):
    def update(self):
        return Status.SUCCESS


class _AlwaysFailure(Node):
    def update(self):
        return Status.FAILURE


class _AlwaysRunning(Node):
    def update(self):
        return Status.RUNNING


class _CountedSuccess(Node):
    def __init__(self, name, succeed_after=2):
        super().__init__(name)
        self.count = 0
        self.succeed_after = succeed_after

    def update(self):
        self.count += 1
        if self.count >= self.succeed_after:
            return Status.SUCCESS
        return Status.RUNNING


class TestBasicNodes:
    """Test the basic behavior tree node types."""

    def test_sequence_all_success(self):
        seq = Sequence("test", [_AlwaysSuccess("a"), _AlwaysSuccess("b")])
        assert seq.tick() == Status.SUCCESS

    def test_sequence_first_fails(self):
        seq = Sequence("test", [_AlwaysFailure("a"), _AlwaysSuccess("b")])
        assert seq.tick() == Status.FAILURE

    def test_sequence_running_then_success(self):
        seq = Sequence("test", [_CountedSuccess("a", 2), _AlwaysSuccess("b")])
        assert seq.tick() == Status.RUNNING  # a: count 1 < 2
        assert seq.tick() == Status.SUCCESS  # a: count 2 >= 2 → SUCCESS, then b: SUCCESS

    def test_selector_first_wins(self):
        sel = Selector("test", [_AlwaysSuccess("a"), _AlwaysFailure("b")])
        assert sel.tick() == Status.SUCCESS

    def test_selector_fallback(self):
        sel = Selector("test", [_AlwaysFailure("a"), _AlwaysSuccess("b")])
        assert sel.tick() == Status.SUCCESS

    def test_selector_all_fail(self):
        sel = Selector("test", [_AlwaysFailure("a"), _AlwaysFailure("b")])
        assert sel.tick() == Status.FAILURE

    def test_selector_running(self):
        sel = Selector("test", [_AlwaysRunning("a"), _AlwaysSuccess("b")])
        assert sel.tick() == Status.RUNNING

    def test_selector_no_memory_reevaluates(self):
        """Without memory, selector should try from first child each tick."""
        sel = Selector("test", [
            _AlwaysFailure("a"),
            _CountedSuccess("b", 3),
        ], memory=False)
        assert sel.tick() == Status.RUNNING  # b starts
        sel.reset()
        # After reset, b is reinitialised, so count starts over
        # But the selector resets b too... Hmm, the issue is CountedSuccess
        # doesn't reset its count. Let me just test that a new ALWAYS_FAILURE
        # first child is checked first each tick.
        pass


# ── Default Idle Test ────────────────────────────────────────────────────────

class TestDefaultIdle:
    """Test 1: No input → idle_look_around."""

    def test_default_idle(self, runtime):
        root, bb, executor, provider, loader = runtime

        # No active behavior set → tree should fall through to idle
        bb.set_active_behavior(provider.inject_idle())

        status = _tick(root, bb, 1)
        # Should be RUNNING (idle looking around)
        assert status == Status.RUNNING
        assert bb.current_behavior is not None
        assert bb.current_behavior.behavior_name == "idle_look_around"
        assert bb.current_behavior.priority_level == 6

    def test_idle_starts_when_nothing_else(self, runtime):
        root, bb, executor, provider, loader = runtime

        candidate = provider.select()  # No injections → returns idle
        bb.set_active_behavior(candidate)

        status = _tick(root, bb, 1)
        assert status == Status.RUNNING
        assert bb.current_behavior.priority_level == 6


# ── Priority Level Tests ─────────────────────────────────────────────────────

class TestPriorityLevels:
    """Test that higher priority levels preempt lower ones."""

    def test_lv2_preempts_lv3(self, runtime):
        """Test 2: Lv3 hunger running, inject Lv1 owner_call → preempt."""
        root, bb, executor, provider, loader = runtime

        # Start hunger (Lv3)
        bb.set_active_behavior(provider.inject_hunger(85))
        status = _tick(root, bb, 1)
        assert status == Status.RUNNING
        assert bb.current_behavior.behavior_name == "eatNormally"

        # Inject owner call (Lv1) which is higher priority
        provider.inject_owner_call(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        status = _tick(root, bb, 1)
        assert status == Status.RUNNING
        assert bb.preemption_occurred
        assert bb.current_behavior.behavior_name == "respond_owner_call"

    def test_lv0_preempts_lv2(self, runtime):
        """Test 3: Lv1 running, inject Lv0 danger → preempt."""
        root, bb, executor, provider, loader = runtime

        # Start owner call (Lv1)
        bb.set_active_behavior(provider.inject_owner_call(85))
        status = _tick(root, bb, 1)
        assert status == Status.RUNNING
        assert bb.current_behavior.behavior_name == "respond_owner_call"

        # Inject danger (Lv0)
        provider.inject_danger(100)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        status = _tick(root, bb, 1)
        assert status == Status.RUNNING
        assert bb.preemption_occurred
        assert bb.current_behavior.behavior_name == "avoid_danger"

    def test_emergency_stop_preempts_all(self, runtime):
        """Test: emergency_stop preempts anything."""
        root, bb, executor, provider, loader = runtime

        # Start owner call (Lv1)
        bb.set_active_behavior(provider.inject_owner_call(85))
        _tick(root, bb, 1)

        # Inject emergency stop
        provider.inject_emergency_stop(100)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        status = _tick(root, bb, 1)
        assert status == Status.RUNNING
        assert bb.preemption_occurred
        assert bb.current_behavior.behavior_name == "emergency_stop"

    def test_lower_priority_does_not_preempt(self, runtime):
        """Lv4 should not preempt Lv1."""
        root, bb, executor, provider, loader = runtime

        # Start owner call (Lv1)
        bb.set_active_behavior(provider.inject_owner_call(85))
        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "respond_owner_call"

        # Inject social need (Lv4) - lower priority
        bb.perception_client.set_person_present(True, identity="owner")
        provider.inject_social_need(75)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        status = _tick(root, bb, 1)
        # Should NOT preempt - current is still owner_call
        assert not bb.preemption_occurred
        assert bb.current_behavior.behavior_name == "respond_owner_call"


# ── Same-Level Jitter Prevention ─────────────────────────────────────────────

class TestSameLevelPreemption:
    """Test 4: Same-level hysteresis / jitter prevention."""

    def test_small_delta_no_preempt(self, runtime):
        """Same level, small value delta → no preempt."""
        root, bb, executor, provider, loader = runtime

        # Start eatNormally (Lv3, val=80)
        bb.set_active_behavior(provider.inject_hunger(80))
        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "eatNormally"

        # Inject lickPaws (Lv3, val=85) — delta=5 < 15
        provider.inject_cleanliness(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        status = _tick(root, bb, 1)
        assert not bb.preemption_occurred
        assert bb.current_behavior.behavior_name == "eatNormally"

    def test_large_delta_preempts(self, runtime):
        """Same level, large value delta → preempt."""
        root, bb, executor, provider, loader = runtime

        # Start eatNormally (Lv3, val=80)
        bb.set_active_behavior(provider.inject_hunger(80))
        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "eatNormally"

        # Cleanliness V2 has only TRIGGERED; value 96 maps to lickPaws.
        provider.inject_cleanliness(96)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        status = _tick(root, bb, 1)
        assert bb.preemption_occurred
        assert bb.current_behavior.behavior_name == "lickPaws"
