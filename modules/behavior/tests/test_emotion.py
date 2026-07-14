"""Tests: emotion module, decay, overflow, and BehaviorRelevanceCondition."""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.emotion_module import EmotionModule
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.conditions import BehaviorRelevanceCondition
from bionic_dog_bt.constants import (
    STATUS_RUNNING,
    STATUS_SUCCESS,
    STATUS_FAILURE,
    EMOTION_BEHAVIOR_MAP,
)


@pytest.fixture
def emotion_module():
    """Create a fresh emotion module."""
    return EmotionModule()


@pytest.fixture
def runtime():
    """Full runtime with emotion support."""
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


# ── Emotion Module Unit Tests ────────────────────────────────────────────────

class TestEmotionModule:
    """Unit tests for EmotionModule."""

    def test_set_and_get_emotion(self, emotion_module):
        em = emotion_module
        em.set_emotion("happy", 85.0)
        assert em.get_value("happy") == 85.0
        assert em.is_overflowing("happy")  # threshold=70

    def test_emotion_decay(self, emotion_module):
        em = emotion_module
        em.set_emotion("happy", 85.0)
        # Override decay rate for fast testing
        state = em.get_emotion("happy")
        state.decay_rate = 100.0  # very fast decay

        time.sleep(0.1)  # 100 * 0.1 = 10 units decay
        em.tick()

        val = em.get_value("happy")
        assert val < 85.0, f"Expected decay, got {val}"

    def test_emotion_below_threshold_not_overflowing(self, emotion_module):
        em = emotion_module
        em.set_emotion("happy", 50.0)  # below 70 threshold
        assert not em.is_overflowing("happy")

    def test_emotion_at_threshold_is_overflowing(self, emotion_module):
        em = emotion_module
        em.set_emotion("happy", 70.0)  # exactly at threshold
        assert em.is_overflowing("happy")

    def test_set_emotion_always_updates(self, emotion_module):
        """Emotion engine is the single source of truth — always accept its value."""
        em = emotion_module
        em.set_emotion("happy", 80.0)
        assert em.get_value("happy") == 80.0
        # Engine publishes a lower value (decayed from HIGH to MID)
        em.set_emotion("happy", 60.0)
        assert em.get_value("happy") == 60.0
        # Clamped to 0..100
        em.set_emotion("happy", -10.0)
        assert em.get_value("happy") == 0.0
        em.set_emotion("happy", 150.0)
        assert em.get_value("happy") == 100.0

    def test_unknown_emotion_returns_zero(self, emotion_module):
        assert emotion_module.get_value("nonexistent") == 0.0
        assert not emotion_module.is_overflowing("nonexistent")

    def test_multiple_emotions(self, emotion_module):
        em = emotion_module
        em.set_emotion("Joy", 85.0)
        em.set_emotion("Fear", 75.0)
        em.set_emotion("Curious", 65.0)

        assert em.is_overflowing("Joy")  # 85 >= 70
        assert em.is_overflowing("Fear")  # 75 >= 60 (Fear threshold=60)
        assert em.is_overflowing("Curious")  # 65 >= 50 (Curious threshold=50)

        all_em = em.get_all_emotions()
        assert len(all_em) == 3

    def test_decay_stops_at_zero(self, emotion_module):
        em = emotion_module
        em.set_emotion("happy", 5.0)
        state = em.get_emotion("happy")
        state.decay_rate = 1000.0

        time.sleep(0.05)
        em.tick()

        assert em.get_value("happy") == 0.0  # clamped at 0

    def test_reset_clears_all(self, emotion_module):
        em = emotion_module
        em.set_emotion("happy", 80.0)
        em.set_emotion("fear", 80.0)
        em.reset()
        assert len(em.get_all_emotions()) == 0


# ── BehaviorRelevanceCondition Tests ─────────────────────────────────────────

class TestBehaviorRelevanceCondition:
    """Tests for the relevance condition node."""

    def test_emotional_behavior_passes_when_overflowing(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Set emotion above threshold
        bb.emotion_module.set_emotion("happy", 85.0)
        # Create active behavior for express_happy
        provider.inject_happy_overflow(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS

    def test_emotional_behavior_fails_when_decayed(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Set emotion below threshold
        bb.emotion_module.set_emotion("happy", 40.0)  # well below 70
        provider.inject_happy_overflow(40)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.FAILURE

    def test_non_emotional_always_passes(self, runtime):
        root, bb, executor, provider, loader = runtime
        # System behavior
        provider.inject_danger(100)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS

    def test_external_behavior_always_passes(self, runtime):
        root, bb, executor, provider, loader = runtime
        provider.inject_owner_call(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS

    def test_idle_behavior_always_passes(self, runtime):
        root, bb, executor, provider, loader = runtime
        provider.inject_idle()
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS

    def test_no_active_behavior_passes(self, runtime):
        root, bb, executor, provider, loader = runtime
        # No active behavior (current behavior is running)
        bb.active_behavior = None

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS


# ── Integration: Excretion + Happy Scenario ──────────────────────────────────

class TestExcretionThenHappyScenario:
    """Test the core scenario: excretion (Lv1) + happy (Lv5) trigger together.

    Excretion runs first (higher priority). While it executes, happy emotion
    decays. By the time the tree reaches Lv5, happy should be below threshold
    and the express_happy behavior should be skipped.
    """

    def test_happy_skipped_when_decayed_during_excretion(self, runtime):
        root, bb, executor, provider, loader = runtime

        # Inject both excretion and happy simultaneously
        provider.inject_excretion(95)
        provider.inject_happy_overflow(80)

        # Select best — should be excretion (Lv1 < Lv5)
        candidate = provider.select()
        assert candidate.behavior_name == "excretion_request"
        bb.set_active_behavior(candidate)

        # Tick: excretion starts
        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "excretion_request"

        # Simulate rapid emotion decay in the upstream /emotion node.
        # (Decay happens upstream, NOT inside the BT tick.)
        joy_state = bb.emotion_module.get_emotion("Joy")
        assert joy_state is not None
        joy_state.decay_rate = 200.0  # very fast decay: 200/s

        # Tick multiple times. Each tick: upstream decays, then BT processes.
        for _ in range(5):
            time.sleep(0.1)  # 200 * 0.1 = 20 units decay
            bb.tick_emotions()  # simulate upstream /emotion node processing
            _tick(root, bb, 1)

        # After several ticks, Joy should be well below threshold
        current_joy = bb.emotion_module.get_value("Joy")
        assert current_joy < 70.0, f"Expected Joy < 70 after decay, got {current_joy}"

        # Now if express_happy were still pending, it should be skipped.
        # Don't re-inject (which would re-raise emotion). Instead create
        # a candidate manually.
        from bionic_dog_bt.datatypes import ActiveBehavior
        candidate2 = ActiveBehavior(
            behavior_id="test_decayed", behavior_name="express_happy",
            priority_level=5, value=current_joy, confidence=0.8,
            need_type="emotional", timeout_sec=5.0, cooldown_sec=1.0,
        )
        bb.set_active_behavior(candidate2)

        cond = BehaviorRelevanceCondition("test", bb)
        result = cond.update()
        assert result == Status.FAILURE, (
            f"Expected FAILURE for Joy at {current_joy:.0f} below threshold 70"
        )

    def test_happy_executes_when_still_overflowing(self, runtime):
        root, bb, executor, provider, loader = runtime

        # Inject express_happy directly (no competing behavior)
        provider.inject_happy_overflow(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        # Set very slow decay so emotion stays high
        joy_state = bb.emotion_module.get_emotion("Joy")
        assert joy_state is not None
        joy_state.decay_rate = 0.1  # nearly no decay

        _tick(root, bb, 1)
        # Should start an emotion-driven behavior
        assert bb.current_behavior is not None
        assert bb.current_behavior.need_type == "emotional"
        assert bb.current_behavior.params.get("source_emotion") == "Joy"
        assert bb.preemption_occurred is False  # no preemption needed


# ── EMOTION_BEHAVIOR_MAP Validation ──────────────────────────────────────────

class TestEmotionBehaviorMap:
    """Verify all emotion-triggered behaviors have mappings."""

    def test_all_emotional_behaviors_mapped(self):
        expected = {"express_happy", "express_fear", "express_curiosity"}
        mapped = set(EMOTION_BEHAVIOR_MAP.keys())
        assert expected == mapped, f"Missing mappings: {expected - mapped}"
