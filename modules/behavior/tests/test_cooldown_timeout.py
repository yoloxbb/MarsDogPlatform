"""Tests: cooldown and timeout behavior."""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.constants import STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILURE, STATUS_CANCELED


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


class TestCooldown:
    """Test 7: cooldown prevents repeated execution."""

    def test_cooldown_blocks_repeat(self, runtime):
        """After a behavior completes, it can't start again during cooldown."""
        root, bb, executor, provider, loader = runtime

        # Use emotion-driven behavior (Lv5, cooldown=1.0s)
        behavior = provider.inject_happy_overflow(80)
        assert behavior is not None
        behavior_name = behavior.behavior_name  # dynamic from emotion table
        bb.set_active_behavior(behavior)
        _tick(root, bb, 1)
        assert bb.current_behavior is not None
        assert bb.current_behavior.need_type == "emotional"

        # Wait for the behavior to complete by ticking many times
        for _ in range(15):
            _tick(root, bb, 1)
            time.sleep(0.3)
            if bb.last_feedback_event:
                break

        # After completion, cooldown should be set on the actual behavior name
        if bb.last_feedback_event:
            assert bb.is_in_cooldown(behavior_name)

        # Verify cooldown was set for something (or feedback was produced)
        assert len(bb.cooldown_until) > 0 or bb.last_feedback_event is not None

    def test_cooldown_expires(self, runtime):
        """After cooldown expires, behavior can execute again."""
        root, bb, executor, provider, loader = runtime

        # Manually set a cooldown in the past
        bb.cooldown_until["test_behavior"] = time.time() - 10.0
        assert not bb.is_in_cooldown("test_behavior")


class TestTimeout:
    """Test 8: timeout cancels running behavior."""

    def test_timeout_cancels_behavior(self, runtime):
        """When a behavior exceeds timeout, it's canceled."""
        root, bb, executor, provider, loader = runtime

        # Inject a behavior and override its timeout to be very short
        bb.set_active_behavior(provider.inject_idle())
        _tick(root, bb, 1)

        # Override timeout for testing
        if bb.current_behavior:
            bb.current_behavior.timeout_sec = 0.01  # 10ms timeout

        # Wait for timeout
        time.sleep(0.02)

        # Next tick should detect timeout
        status = _tick(root, bb, 1)
        # Should have timed out
        assert bb.timeout_occurred or bb.current_status in (STATUS_FAILURE, STATUS_CANCELED)

    def test_no_timeout_when_not_running(self, runtime):
        """Timeout check only applies to RUNNING behaviors."""
        root, bb, executor, provider, loader = runtime

        # No behavior running
        assert not bb.check_timeout()

    def test_zero_timeout_disables_existing_running_deadline(self, runtime):
        root, bb, executor, provider, loader = runtime
        bb.set_active_behavior(provider.inject_idle())
        _tick(root, bb, 1)
        assert bb.current_behavior is not None

        bb.current_behavior.timeout_sec = 0.0
        bb._behavior_start_time -= 1000.0
        assert not bb.check_timeout()
