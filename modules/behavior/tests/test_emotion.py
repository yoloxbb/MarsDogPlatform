"""Tests: emotion V2 state and behavior relevance."""

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
        em.update_state("Joy", 30.0, True, 30.0, "gte")
        assert em.get_value("Joy") == 30.0
        assert em.is_triggered("Joy")
        assert em.get_emotion("Joy").trigger_threshold == 30.0
        assert em.get_emotion("Joy").trigger_operator == "gte"

    def test_emotion_decay(self, emotion_module):
        em = emotion_module
        em.set_emotion("Joy", 85.0)
        # Override decay rate for fast testing
        state = em.get_emotion("Joy")
        state.decay_rate = 100.0  # very fast decay

        time.sleep(0.1)  # 100 * 0.1 = 10 units decay
        em.tick()

        val = em.get_value("Joy")
        assert val < 85.0, f"Expected decay, got {val}"

    def test_numeric_value_does_not_replace_triggered_flag(self, emotion_module):
        em = emotion_module
        em.update_state("Joy", 100.0, False)
        assert not em.is_triggered("Joy")
        em.update_state("Joy", 0.0, True)
        assert em.is_triggered("Joy")

    def test_set_emotion_always_updates(self, emotion_module):
        """Emotion engine is the single source of truth — always accept its value."""
        em = emotion_module
        em.set_emotion("Joy", 80.0)
        assert em.get_value("Joy") == 80.0
        em.set_emotion("Joy", 60.0)
        assert em.get_value("Joy") == 60.0
        # Clamped to 0..100
        em.set_emotion("Joy", -10.0)
        assert em.get_value("Joy") == 0.0
        em.set_emotion("Joy", 150.0)
        assert em.get_value("Joy") == 100.0

    def test_unknown_emotion_returns_zero(self, emotion_module):
        assert emotion_module.get_value("nonexistent") == 0.0
        assert not emotion_module.is_triggered("nonexistent")

    def test_multiple_emotions(self, emotion_module):
        em = emotion_module
        em.update_state("Joy", 85.0, True)
        em.update_state("Fear", 75.0, False)
        em.update_state("Curious", 65.0, True)

        assert em.is_triggered("Joy")
        assert not em.is_triggered("Fear")
        assert em.is_triggered("Curious")

        all_em = em.get_all_emotions()
        assert len(all_em) == 3

    def test_decay_stops_at_zero(self, emotion_module):
        em = emotion_module
        em.set_emotion("Joy", 5.0)
        state = em.get_emotion("Joy")
        state.decay_rate = 1000.0

        time.sleep(0.05)
        em.tick()

        assert em.get_value("Joy") == 0.0  # clamped at 0

    def test_reset_clears_all(self, emotion_module):
        em = emotion_module
        em.update_state("Joy", 80.0, True)
        em.update_state("Fear", 80.0, True)
        em.reset()
        assert len(em.get_all_emotions()) == 0


# ── BehaviorRelevanceCondition Tests ─────────────────────────────────────────

class TestBehaviorRelevanceCondition:
    """Tests for the relevance condition node."""

    def test_emotional_behavior_passes_while_triggered(self, runtime):
        root, bb, executor, provider, loader = runtime
        provider.inject_joy_trigger(30)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.SUCCESS

    def test_emotional_behavior_fails_after_state_recovery(self, runtime):
        root, bb, executor, provider, loader = runtime
        provider.inject_joy_trigger(30)
        candidate = provider.select()
        bb.emotion_module.update_state("Joy", 29.0, False)
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

    def test_unknown_emotional_behavior_fails_closed(self, runtime):
        from bionic_dog_bt.datatypes import ActiveBehavior

        root, bb, executor, provider, loader = runtime
        bb.set_active_behavior(ActiveBehavior(
            behavior_id="legacy-emotion",
            behavior_name="express_happy",
            priority_level=5,
            value=80.0,
            confidence=0.8,
            need_type="emotional",
        ))

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.FAILURE


# ── Integration: queued emotion candidate + recovery ────────────────────────

class TestQueuedEmotionRecovery:
    def test_happy_skipped_when_state_reports_recovery(self, runtime):
        root, bb, executor, provider, loader = runtime

        provider.inject_joy_trigger(30)
        candidate = provider.select()
        assert candidate.behavior_name == "expressJoyAlone"
        bb.emotion_module.update_state("Joy", 29.0, False)
        bb.set_active_behavior(candidate)

        cond = BehaviorRelevanceCondition("test", bb)
        assert cond.update() == Status.FAILURE

    def test_happy_executes_while_still_triggered(self, runtime):
        root, bb, executor, provider, loader = runtime

        provider.inject_joy_trigger(30)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert bb.current_behavior is not None
        assert bb.current_behavior.need_type == "emotional"
        assert bb.current_behavior.params.get("source_emotion") == "Joy"
        assert bb.preemption_occurred is False  # no preemption needed


# ── EMOTION_BEHAVIOR_MAP Validation ──────────────────────────────────────────

class TestEmotionBehaviorMap:
    """Verify all emotion-triggered behaviors have mappings."""

    def test_all_emotional_behaviors_mapped(self):
        expected = {
            "expressCalm",
            "expressCalmWithHuman",
            "expressCalmAlone",
            "expressJoy",
            "expressJoyWithHuman",
            "expressJoyAlone",
            "expressExcitement",
            "expressExcitementWithHuman",
            "expressExcitementAlone",
            "expressAnxiety",
            "expressAnxietyWithHuman",
            "expressAnxietyAlone",
            "expressFear",
            "expressFearWithHuman",
            "expressFearAlone",
            "expressCuriosity",
            "expressCuriosityWithHuman",
            "expressCuriosityAlone",
        }
        mapped = set(EMOTION_BEHAVIOR_MAP.keys())
        assert expected == mapped
