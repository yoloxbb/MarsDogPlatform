"""Tests: need module, trigger/overflow levels, and need relevance checking."""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.need_module import NeedModule
from bionic_dog_bt.conditions import BehaviorRelevanceCondition
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.constants import (
    NEED_LEVEL_NORMAL,
    NEED_LEVEL_TRIGGERED,
    NEED_LEVEL_OVERFLOW,
    NEED_BEHAVIOR_MAP,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    STATUS_FAILURE,
)


@pytest.fixture
def need_module():
    return NeedModule()


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


# ── Need Module Unit Tests ───────────────────────────────────────────────────

class TestNeedModule:
    """Unit tests for NeedModule."""

    def test_set_need_normal(self, need_module):
        need_module.set_need("Hunger", 50)
        assert need_module.get_value("Hunger") == 50
        assert need_module.get_level("Hunger") == NEED_LEVEL_NORMAL
        assert not need_module.is_triggered("Hunger")

    def test_set_need_triggered(self, need_module):
        need_module.set_need("Hunger", 75)  # > 70
        assert need_module.is_triggered("Hunger")
        assert need_module.get_level("Hunger") == NEED_LEVEL_TRIGGERED

    def test_set_need_overflow(self, need_module):
        need_module.set_need("Hunger", 95)  # > 90
        assert need_module.get_level("Hunger") == NEED_LEVEL_OVERFLOW
        assert need_module.is_overflowing("Hunger")
        assert need_module.is_triggered("Hunger")  # overflow implies triggered

    def test_energy_inverted(self, need_module):
        """Energy uses 'lt' operator: low value = triggered."""
        need_module.set_need("Energy", 50)
        assert need_module.get_level("Energy") == NEED_LEVEL_NORMAL

        need_module.set_need("Energy", 15)  # < 20 = TRIGGERED
        assert need_module.get_level("Energy") == NEED_LEVEL_TRIGGERED
        assert need_module.is_triggered("Energy")

        need_module.set_need("Energy", 5)  # < 10 = OVERFLOW
        assert need_module.get_level("Energy") == NEED_LEVEL_OVERFLOW
        assert need_module.is_overflowing("Energy")

    def test_set_need_returns_new_level(self, need_module):
        result = need_module.set_need("Hunger", 75)  # NORMAL → TRIGGERED
        assert result == NEED_LEVEL_TRIGGERED

        result = need_module.set_need("Hunger", 80)  # TRIGGERED → TRIGGERED (no change)
        assert result is None

    def test_multiple_needs(self, need_module):
        need_module.set_need("Hunger", 80)
        need_module.set_need("Bladder", 95)
        need_module.set_need("Social", 70)
        need_module.set_need("Energy", 15)

        assert need_module.get_level("Hunger") == NEED_LEVEL_TRIGGERED
        assert need_module.get_level("Bladder") == NEED_LEVEL_OVERFLOW
        assert need_module.get_level("Social") == NEED_LEVEL_TRIGGERED
        assert need_module.get_level("Energy") == NEED_LEVEL_TRIGGERED

        all_needs = need_module.get_all_needs()
        assert len(all_needs) == 4

    def test_unknown_need_returns_normal(self, need_module):
        assert need_module.get_level("nonexistent") == NEED_LEVEL_NORMAL
        assert not need_module.is_triggered("nonexistent")

    def test_reset_clears_all(self, need_module):
        need_module.set_need("Hunger", 80)
        need_module.set_need("Social", 70)
        need_module.reset()
        assert len(need_module.get_all_needs()) == 0


# ── Need Relevance Tests ─────────────────────────────────────────────────────

class TestNeedRelevance:
    """Tests for BehaviorRelevanceCondition with need-triggered behaviors."""

    def test_hunger_behavior_passes_when_triggered(self, runtime):
        root, bb, executor, provider, loader = runtime
        bb.need_module.set_need("Hunger", 80)  # TRIGGERED
        provider.inject_hunger(80)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS

    def test_hunger_behavior_fails_when_recovered(self, runtime):
        root, bb, executor, provider, loader = runtime
        bb.need_module.set_need("Hunger", 50)  # NORMAL (below trigger=70)
        provider.inject_hunger(50)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.FAILURE

    def test_bladder_behavior_checks_correctly(self, runtime):
        root, bb, executor, provider, loader = runtime
        bb.need_module.set_need("Bladder", 95)
        provider.inject_excretion(95)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS

        # Lower bladder below trigger
        bb.need_module.set_need("Bladder", 50)  # NORMAL
        # Re-inject would re-set, so manually create candidate
        from bionic_dog_bt.datatypes import ActiveBehavior
        c2 = ActiveBehavior(
            behavior_id="test_bladder", behavior_name="excretion_request",
            priority_level=1, value=50.0, confidence=0.9,
            need_type="physiological_urgent", timeout_sec=60.0,
        )
        bb.set_active_behavior(c2)
        assert cond.update() == Status.FAILURE


# ── Integration: Need + Emotion Scenario ─────────────────────────────────────

class TestNeedEmotionIntegration:
    """Scenarios with both needs and emotions."""

    def test_excretion_then_happy_with_need_decay(self, runtime):
        """Core scenario: Bladder overflow + Joy overflow simultaneously.
        Excretion (Lv1) runs first. If Bladder is satisfied during excretion,
        BehaviorRelevanceCondition should still allow it (it already started).
        Joy decays, express_happy should be skipped at Lv5.
        """
        root, bb, executor, provider, loader = runtime

        # Simulate receiving both states
        provider.inject_excretion(95)   # Bladder OVERFLOW
        provider.inject_happy_overflow(85)  # Joy OVERFLOW

        candidate = provider.select()
        assert candidate.behavior_name == "excretion_request"  # Lv1 > Lv5
        bb.set_active_behavior(candidate)
        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "excretion_request"

        # Fast Joy decay during excretion (upstream /emotion node)
        joy_state = bb.emotion_module.get_emotion("Joy")
        joy_state.decay_rate = 500.0
        time.sleep(0.05)
        bb.tick_emotions()  # simulate upstream /emotion node processing
        _tick(root, bb, 1)

        current_joy = bb.emotion_module.get_value("Joy")
        assert current_joy < 70.0, f"Joy decayed to {current_joy}"

        # After excretion completes (let it run), a new tick with Joy below
        # threshold should NOT start express_happy
        from bionic_dog_bt.datatypes import ActiveBehavior
        happy_candidate = ActiveBehavior(
            behavior_id="test_joy", behavior_name="express_happy",
            priority_level=5, value=current_joy, confidence=0.8,
            need_type="emotional", timeout_sec=5.0,
        )
        bb.set_active_behavior(happy_candidate)
        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.FAILURE


# ── NEED_BEHAVIOR_MAP Validation ─────────────────────────────────────────────

class TestNeedBehaviorMap:
    """Verify all need-triggered behaviors have mappings."""

    def test_all_need_behaviors_mapped(self):
        expected = {
            "seek_food_or_water",
            "excretion_request",
            "sleep_request",
            "clean_self",
            "seek_social_interaction",
            "explore_environment",
        }
        mapped = set(NEED_BEHAVIOR_MAP.keys())
        missing = expected - mapped
        extra = mapped - expected
        assert not missing, f"Missing need mappings: {missing}"
        assert not extra, f"Extra need mappings: {extra}"
