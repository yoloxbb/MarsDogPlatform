"""Tests: internal need V2 levels and relevance."""

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
    NEED_LEVEL_URGENT,
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

    def test_energy_is_battery_deficit(self, need_module):
        """Energy V2 is demand intensity, not remaining battery."""
        need_module.set_need("Energy", 80)
        assert need_module.get_level("Energy") == NEED_LEVEL_NORMAL

        need_module.set_need("Energy", 81)
        assert need_module.get_level("Energy") == NEED_LEVEL_TRIGGERED
        assert need_module.is_triggered("Energy")

        need_module.set_need("Energy", 91)
        assert need_module.get_level("Energy") == NEED_LEVEL_OVERFLOW
        assert need_module.is_overflowing("Energy")

    @pytest.mark.parametrize(
        ("demand", "normal_value", "triggered_value"),
        [
            ("Bladder", 75, 100),
            ("Cleanliness", 70, 100),
            ("Exploration", 60, 100),
        ],
    )
    def test_demands_without_overflow_stay_triggered_at_100(
        self,
        need_module,
        demand,
        normal_value,
        triggered_value,
    ):
        need_module.set_need(demand, normal_value)
        assert need_module.get_level(demand) == NEED_LEVEL_NORMAL
        need_module.set_need(demand, triggered_value)
        assert need_module.get_level(demand) == NEED_LEVEL_TRIGGERED
        assert not need_module.is_overflowing(demand)

    def test_social_has_urgent_level(self, need_module):
        expected = [
            (60, NEED_LEVEL_NORMAL),
            (61, NEED_LEVEL_TRIGGERED),
            (70, NEED_LEVEL_TRIGGERED),
            (71, NEED_LEVEL_URGENT),
            (85, NEED_LEVEL_URGENT),
            (86, NEED_LEVEL_OVERFLOW),
        ]
        for value, level in expected:
            need_module.set_need("Social", value)
            assert need_module.get_level("Social") == level

        state = need_module.get_need("Social")
        assert state.triggered is True
        assert state.urgent is True
        assert state.overflow is True

    def test_set_need_returns_new_level(self, need_module):
        result = need_module.set_need("Hunger", 75)  # NORMAL → TRIGGERED
        assert result == NEED_LEVEL_TRIGGERED

        result = need_module.set_need("Hunger", 80)  # TRIGGERED → TRIGGERED (no change)
        assert result is None

    def test_multiple_needs(self, need_module):
        need_module.set_need("Hunger", 80)
        need_module.set_need("Bladder", 95)
        need_module.set_need("Social", 70)
        need_module.set_need("Energy", 81)

        assert need_module.get_level("Hunger") == NEED_LEVEL_TRIGGERED
        assert need_module.get_level("Bladder") == NEED_LEVEL_TRIGGERED
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
        provider.inject_hunger(71)
        candidate = provider.select()
        bb.need_module.set_need("Hunger", 50)
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.FAILURE

    def test_need_candidate_stays_relevant_across_active_levels(self, runtime):
        root, bb, executor, provider, loader = runtime
        bb.perception_client.set_person_present(True, identity="owner")
        provider.inject_social_need(61)
        candidate = provider.select()
        assert candidate.behavior_name == "seekHumanInteraction"

        # V2 relevance only checks the first trigger line. Moving to URGENT
        # selects a different edge behavior but does not mean the need recovered.
        bb.need_module.set_need("Social", 71)
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS

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

    def test_bladder_then_joy_recovery(self, runtime):
        """Core scenario: Bladder trigger + Joy trigger simultaneously.
        Bladder response (Lv2) runs first. If Bladder is satisfied during it,
        BehaviorRelevanceCondition should still allow it (it already started).
        A Joy recovery state invalidates the pending Lv5 behavior.
        """
        root, bb, executor, provider, loader = runtime

        # Simulate receiving both states
        provider.inject_excretion(100)
        provider.inject_joy_trigger(30)

        candidate = provider.select()
        assert candidate.behavior_name == "barkShortAlert"
        bb.set_active_behavior(candidate)
        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "barkShortAlert"

        # /emotion/state reports recovery while the need behavior is running.
        bb.emotion_module.update_state("Joy", 29.0, False)
        _tick(root, bb, 1)

        from bionic_dog_bt.datatypes import ActiveBehavior
        happy_candidate = ActiveBehavior(
            behavior_id="test_joy",
            behavior_name="expressJoy",
            priority_level=5,
            value=29.0,
            confidence=0.8,
            need_type="emotional",
            timeout_sec=5.0,
            params={"source_emotion": "Joy"},
        )
        bb.set_active_behavior(happy_candidate)
        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.FAILURE


# ── NEED_BEHAVIOR_MAP Validation ─────────────────────────────────────────────

class TestNeedBehaviorMap:
    """Verify all need-triggered behaviors have mappings."""

    def test_all_need_behaviors_mapped(self):
        expected = {
            "eatNormally", "eatExcitedly", "seekFood", "seekFoodUrgently",
            "barkShortAlert",
            "sleepOnSide", "sleepNow",
            "lickPaws",
            "restInPlace", "recharge",
            "seekHumanInteraction", "seekInteraction", "inviteHumanToPlay",
            "testAnimalBoundary", "greetAnimal", "inviteAnimalToPlay",
            "exploreRoom", "inspectObject",
            "inspectFamiliarPlayItem", "inspectTrashCan",
            "inspectDeliveryBox", "inspectTissuePaper",
            "inspectDoor", "inspectDogFood",
        }
        mapped = set(NEED_BEHAVIOR_MAP.keys())
        missing = expected - mapped
        assert not missing, f"Missing need mappings: {missing}"
