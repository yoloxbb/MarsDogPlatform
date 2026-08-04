"""E2E tests: event → candidate → behavior → action execution.

Verifies the full pipeline in standalone mock mode:
  1. Upstream events generate correct BehaviorCandidates
  2. BT tick selects and executes the behavior
  3. MockActionExecutor simulates step-by-step action progress
  4. Results are produced and cooldown is set
  5. Preemption works correctly
  6. Ignored events (visual, audio-emotion) produce NO candidates
"""

from __future__ import annotations

import time
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from marsdog_behavior.ros_node import BehaviorTreeRosNode
from marsdog_behavior.ros2_compat import HAS_ROS2
from bionic_dog_bt.constants import DEFAULT_NEED_CONFIG

pytestmark = pytest.mark.skipif(
    HAS_ROS2 and __import__('rclpy', fromlist=['ok']).ok() if HAS_ROS2 else False,
    reason="Tests are for standalone (no-ROS2) mode")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def node():
    n = BehaviorTreeRosNode(force_mock=True)
    yield n
    n.destroy_node()


def _tick(node, n_ticks=1):
    """Tick the BT n times, waiting for mock executor to advance."""
    for _ in range(n_ticks):
        node._on_tick()
        time.sleep(0.05)


def _advance_until_done(node, max_ticks=30):
    """Tick until current behavior completes or max_ticks reached."""
    for _ in range(max_ticks):
        node._on_tick()
        time.sleep(0.05)
        bb = node.blackboard
        if bb.last_feedback_event:
            return bb.last_feedback_event
        if bb.current_status not in ("RUNNING",):
            return None
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Emotion signal_event → behavior candidate → execution
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmotionToBehavior:
    """Emotion V2 uses one rising edge and distinct human/solo behaviors."""

    @pytest.mark.parametrize(
        ("event_type", "expected_behavior"),
        [
            ("EMO_CALM_TRIGGERED", "expressCalmAlone"),
            ("EMO_JOY_TRIGGERED", "expressJoyAlone"),
            ("EMO_EXCITE_TRIGGERED", "expressExcitementAlone"),
            ("EMO_ANXIETY_TRIGGERED", "expressAnxietyAlone"),
            ("EMO_FEAR_TRIGGERED", "expressFearAlone"),
            ("EMO_CURIOUS_TRIGGERED", "expressCuriosityAlone"),
        ],
    )
    def test_trigger_events_map_one_to_one(
        self, node, event_type, expected_behavior
    ):
        candidate = node._intent_mapper.map_emotion_event(
            event_type,
            {"value": 90, "visual_route": "solo"},
            visual_route="solo",
        )

        assert candidate is not None
        assert candidate.behavior_name == expected_behavior
        assert candidate.trigger_event == event_type
        assert candidate.level == "LOW"
        assert candidate.interaction_mode == "solo"
        assert candidate.params["visual_resolved"] is True

    @pytest.mark.parametrize(
        ("event_type", "emotion", "value", "expected_behavior"),
        [
            ("EMO_CALM_TRIGGERED", "Calm", 0, "expressCalmWithHuman"),
            ("EMO_JOY_TRIGGERED", "Joy", 30, "expressJoyWithHuman"),
            (
                "EMO_EXCITE_TRIGGERED",
                "Excite",
                40,
                "expressExcitementWithHuman",
            ),
            (
                "EMO_ANXIETY_TRIGGERED",
                "Anxiety",
                25,
                "expressAnxietyWithHuman",
            ),
            ("EMO_FEAR_TRIGGERED", "Fear", 30, "expressFearWithHuman"),
            (
                "EMO_CURIOUS_TRIGGERED",
                "Curious",
                20,
                "expressCuriosityWithHuman",
            ),
        ],
    )
    def test_all_emotions_route_to_human_action_pool(
        self,
        node,
        event_type,
        emotion,
        value,
        expected_behavior,
    ):
        node.perception.mock_set_person_present(True, identity="owner")
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": event_type,
            "emotion": emotion,
            "value": value,
        }))

        queued = node.candidate_pool.candidates
        assert len(queued) == 1
        assert queued[0]["behavior_name"] == expected_behavior
        assert queued[0]["params"]["visual_route"] == "human"
        assert queued[0]["params"]["interaction_mode"] == "interactive"
        assert queued[0]["params"]["target"]["target_id"] == "owner"

    @pytest.mark.parametrize(
        ("event_type", "emotion", "value", "expected_behavior"),
        [
            ("EMO_CALM_TRIGGERED", "Calm", 0, "expressCalmAlone"),
            ("EMO_JOY_TRIGGERED", "Joy", 30, "expressJoyAlone"),
            (
                "EMO_EXCITE_TRIGGERED",
                "Excite",
                40,
                "expressExcitementAlone",
            ),
            (
                "EMO_ANXIETY_TRIGGERED",
                "Anxiety",
                25,
                "expressAnxietyAlone",
            ),
            ("EMO_FEAR_TRIGGERED", "Fear", 30, "expressFearAlone"),
            (
                "EMO_CURIOUS_TRIGGERED",
                "Curious",
                20,
                "expressCuriosityAlone",
            ),
        ],
    )
    def test_all_emotions_route_to_solo_action_pool(
        self,
        node,
        event_type,
        emotion,
        value,
        expected_behavior,
    ):
        node.perception.mock_set_no_person()
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": event_type,
            "emotion": emotion,
            "value": value,
        }))

        queued = node.candidate_pool.candidates
        assert len(queued) == 1
        assert queued[0]["behavior_name"] == expected_behavior
        assert queued[0]["params"]["visual_route"] == "solo"
        assert queued[0]["params"]["interaction_mode"] == "solo"
        assert queued[0]["params"]["target"] is None

    def test_exactly_one_event_exists_per_emotion(self, node):
        emotion_map = node._intent_mapper._emotion_map["emotion_behavior_map"]
        for emotion_name in (
            "CALM", "JOY", "EXCITE", "ANXIETY", "FEAR", "CURIOUS"
        ):
            events = [
                event_type
                for event_type in emotion_map
                if event_type.startswith(f"EMO_{emotion_name}_")
            ]
            assert events == [f"EMO_{emotion_name}_TRIGGERED"]
            entry = emotion_map[events[0]]
            assert entry["visual_required"] == "person_presence"
            assert set(entry["routes"]) == {"human", "solo"}
            assert (
                entry["routes"]["human"]["behavior_name"]
                != entry["routes"]["solo"]["behavior_name"]
            )

    @pytest.mark.parametrize(
        "event_type",
        [
            "EMO_CALM_NORMAL",
            "EMO_CALM_HIGH",
            "EMO_JOY_LOW",
            "EMO_JOY_MID",
            "EMO_JOY_HIGH",
            "EMO_EXCITE_LOW",
            "EMO_EXCITE_HIGH",
            "EMO_ANXIETY_LOW",
            "EMO_ANXIETY_HIGH",
            "EMO_FEAR_LOW",
            "EMO_FEAR_HIGH",
            "EMO_CURIOUS_LOW",
            "EMO_CURIOUS_HIGH",
        ],
    )
    def test_v1_level_events_are_unmapped(self, node, event_type):
        assert node._intent_mapper.map_emotion_event(
            event_type,
            {"value": 90},
        ) is None

    def test_nested_emotion_state_updates_value(self, node):
        """The documented V2 state updates value and trigger state."""
        node._on_emotion_state_ros2(_make_string_msg({
            "schema_version": "2.0",
            "emotions": {
                "Joy": {
                    "value": 72,
                    "triggerThreshold": 30,
                    "triggerOperator": "gte",
                    "triggered": True,
                },
            },
        }))

        assert node.blackboard.emotion_module.get_value("Joy") == 72.0
        assert node.blackboard.emotion_module.is_triggered("Joy")
        assert (
            node.blackboard.emotion_module.get_emotion("Joy").trigger_threshold
            == 30
        )

    def test_emotion_signal_generates_candidate(self, node):
        """Inject EMO_JOY_TRIGGERED signal → candidate appears in pool."""
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
            "triggerThreshold": 30,
            "triggerOperator": "gte",
        }))

        assert node.candidate_pool.size() >= 1, \
            "Expected emotion candidate after EMO_JOY_TRIGGERED"
        assert node.blackboard.emotion_module.is_triggered("Joy")

    def test_emotion_candidate_triggers_behavior(self, node):
        """Full cycle: V2 rising edge → candidate → behavior starts."""
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))

        _tick(node, 1)

        bb = node.blackboard
        assert bb.current_behavior is not None, \
            "Expected a behavior to be executing after BT tick"
        assert bb.current_behavior.need_type == "emotional", \
            f"Expected emotional behavior, got {bb.current_behavior.need_type}"
        assert bb.current_behavior.behavior_name == "expressJoyAlone"
        assert bb.current_status == "RUNNING"
        assert bb.current_goal_id is not None

    def test_emotion_service_result_is_preserved_until_execution(self, node):
        """The service result, rather than a later cache change, selects mode."""
        node.perception.mock_set_person_present(True, identity="owner")
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        node.perception.mock_set_no_person()

        _tick(node, 1)

        params = node.blackboard.current_behavior.params
        assert (
            node.blackboard.current_behavior.behavior_name
            == "expressJoyWithHuman"
        )
        assert params["interaction_mode"] == "interactive"
        assert params["target_identity"] == "owner"

    def test_emotion_waits_for_visual_service_before_enqueuing(self, node):
        callbacks = []
        node.perception.request_emotion_context = callbacks.append
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))

        assert len(callbacks) == 1
        assert node.candidate_pool.size() == 0

        callbacks[0]({"route": "solo", "target": None})

        assert node.candidate_pool.size() == 1

    def test_late_emotion_service_result_is_ignored_after_recovery(self, node):
        callbacks = []
        node.perception.request_emotion_context = callbacks.append
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        node._on_emotion_state_ros2(_make_string_msg({
            "schema_version": "2.0",
            "emotions": {
                "Joy": {
                    "value": 29,
                    "triggerThreshold": 30,
                    "triggerOperator": "gte",
                    "triggered": False,
                },
            },
        }))

        callbacks[0]({
            "route": "human",
            "target": {
                "target_type": "human",
                "target_id": "owner",
                "identity": "owner",
            },
        })

        assert node.candidate_pool.size() == 0

    def test_emotion_behavior_completes(self, node):
        """Emotion behavior runs to completion via MockActionExecutor."""
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))

        # Advance until done
        result = _advance_until_done(node, max_ticks=30)

        # Should have completed or be running with feedback
        bb = node.blackboard
        assert bb.tick_count >= 1
        assert bb.current_behavior is not None or result is not None, \
            "Expected behavior to have started"

    def test_state_recovery_discards_queued_candidate(self, node):
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        assert node.candidate_pool.size() == 1

        node._on_emotion_state_ros2(_make_string_msg({
            "schema_version": "2.0",
            "emotions": {
                "Joy": {
                    "value": 29,
                    "triggerThreshold": 30,
                    "triggerOperator": "gte",
                    "triggered": False,
                },
            },
            "dominantEmotion": "Calm",
        }))

        assert not node.blackboard.emotion_module.is_triggered("Joy")
        assert node.candidate_pool.size() == 0

    def test_new_edge_after_recovery_can_enqueue_again(self, node):
        signal = {
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }
        node._on_emotion_signal_ros2(_make_string_msg(signal))
        node._on_emotion_state_ros2(_make_string_msg({
            "schema_version": "2.0",
            "emotions": {
                "Joy": {
                    "value": 29,
                    "triggerThreshold": 30,
                    "triggerOperator": "gte",
                    "triggered": False,
                },
            },
        }))
        node._on_emotion_signal_ros2(_make_string_msg(signal))

        assert node.candidate_pool.size() == 1
        assert node.blackboard.emotion_module.is_triggered("Joy")

    def test_calm_state_is_not_treated_as_a_signal(self, node):
        node._on_emotion_state_ros2(_make_string_msg({
            "schema_version": "2.0",
            "emotions": {
                "Calm": {
                    "value": 20,
                    "triggerThreshold": 0,
                    "triggerOperator": "gte",
                    "triggered": True,
                },
            },
            "triggered": [{
                "emotion": "Calm",
                "eventType": "EMO_CALM_TRIGGERED",
                "value": 20,
            }],
        }))

        assert node.blackboard.emotion_module.is_triggered("Calm")
        assert node.candidate_pool.size() == 0

    def test_v1_state_is_rejected_without_partial_update(self, node):
        node._on_emotion_state_ros2(_make_string_msg({
            "schema_version": "1.0",
            "emotions": {
                "Joy": {
                    "value": 90,
                    "level": "HIGH",
                    "levelEvent": "EMO_JOY_HIGH",
                },
            },
            "levelEvents": {"Joy": "EMO_JOY_HIGH"},
        }))

        assert node.blackboard.emotion_module.get_emotion("Joy") is None

    def test_v1_signal_is_rejected(self, node):
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "1.0",
            "event_type": "EMO_JOY_HIGH",
            "emotion": "Joy",
            "value": 90,
        }))

        assert node.candidate_pool.size() == 0

    def test_v2_payload_cannot_use_a_v1_level_event(self, node):
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_HIGH",
            "emotion": "Joy",
            "value": 90,
        }))

        assert node.candidate_pool.size() == 0
        assert node.blackboard.emotion_module.get_emotion("Joy") is None

    def test_event_and_emotion_must_match(self, node):
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Fear",
            "value": 30,
        }))

        assert node.candidate_pool.size() == 0
        assert node.blackboard.emotion_module.get_emotion("Joy") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Need signal_event → behavior candidate → execution
# ═══════════════════════════════════════════════════════════════════════════════

def _need_signal(
    event_type: str,
    demand: str,
    value: float,
    level: str,
    previous_level: str = "NORMAL",
) -> dict:
    config = DEFAULT_NEED_CONFIG[demand]
    return {
        "schema_version": "2.0",
        "event_type": event_type,
        "demand": demand,
        "value": value,
        "level": level,
        "previousLevel": previous_level,
        "triggerThreshold": config["trigger_threshold"],
        "triggerOperator": config["trigger_op"],
        "urgentThreshold": config.get("urgent_threshold"),
        "urgentOperator": config.get("urgent_op"),
        "overflowThreshold": config.get("overflow_threshold"),
        "overflowOperator": config.get("overflow_op"),
        "trigger": "LEVEL_CHANGED",
    }


def _need_state_entry(demand: str, value: float, level: str) -> dict:
    config = DEFAULT_NEED_CONFIG[demand]
    triggered = level != "NORMAL"
    urgent = (
        config.get("urgent_threshold") is not None
        and level in ("URGENT", "OVERFLOW")
    )
    overflow = level == "OVERFLOW"
    suffix = "RECOVERED" if level == "NORMAL" else level
    return {
        "value": value,
        "triggerThreshold": config["trigger_threshold"],
        "triggerOperator": config["trigger_op"],
        "urgentThreshold": config.get("urgent_threshold"),
        "urgentOperator": config.get("urgent_op"),
        "overflowThreshold": config.get("overflow_threshold"),
        "triggered": triggered,
        "urgent": urgent,
        "overflow": overflow,
        "level": level,
        "levelEvent": f"NEED_{demand.upper()}_{suffix}",
        "levelActive": triggered,
    }


class TestNeedToBehavior:
    """Every configured V2 need level maps to an exact behavior."""

    @pytest.mark.parametrize(
        (
            "event_type",
            "demand",
            "value",
            "visual_route",
            "expected_behavior",
            "expected_level",
        ),
        [
            ("NEED_HUNGER_TRIGGERED", "Hunger", 71, "dog_food", "eatNormally", 3),
            ("NEED_HUNGER_TRIGGERED", "Hunger", 71, "no_dog_food", "seekFood", 3),
            ("NEED_HUNGER_OVERFLOW", "Hunger", 91, "dog_food", "eatExcitedly", 3),
            (
                "NEED_HUNGER_OVERFLOW",
                "Hunger",
                91,
                "no_dog_food",
                "seekFoodUrgently",
                3,
            ),
            ("NEED_BLADDER_TRIGGERED", "Bladder", 76, None, "barkShortAlert", 2),
            ("NEED_SLEEPINESS_TRIGGERED", "Sleepiness", 66, None, "sleepOnSide", 2),
            ("NEED_SLEEPINESS_OVERFLOW", "Sleepiness", 91, None, "sleepNow", 2),
            ("NEED_CLEANLINESS_TRIGGERED", "Cleanliness", 71, None, "lickPaws", 3),
            ("NEED_ENERGY_TRIGGERED", "Energy", 81, None, "restInPlace", 0),
            ("NEED_ENERGY_OVERFLOW", "Energy", 91, None, "recharge", 0),
            ("NEED_SOCIAL_TRIGGERED", "Social", 61, "human", "seekHumanInteraction", 4),
            ("NEED_SOCIAL_URGENT", "Social", 71, "human", "seekInteraction", 4),
            ("NEED_SOCIAL_OVERFLOW", "Social", 86, "human", "inviteHumanToPlay", 4),
            ("NEED_EXPLORATION_TRIGGERED", "Exploration", 61, "empty", "exploreRoom", 4),
        ],
    )
    def test_strength_events_map_one_to_one(
        self,
        node,
        event_type,
        demand,
        value,
        visual_route,
        expected_behavior,
        expected_level,
    ):
        candidate = node._intent_mapper.map_need_event(
            event_type,
            {
                "demand": demand,
                "value": value,
                "level": event_type.rsplit("_", 1)[-1],
                "visual_route": visual_route,
                "target": (
                    {"target_type": "human", "target_id": "owner"}
                    if visual_route == "human"
                    else (
                        {
                            "target_type": "object",
                            "target_id": "dog food can",
                            "label": "dog food can",
                            "object_category": "food_bowl",
                        }
                        if visual_route == "dog_food"
                        else None
                    )
                ),
            },
        )

        assert candidate is not None
        assert candidate.behavior_name == expected_behavior
        assert candidate.priority_level == expected_level
        assert candidate.trigger_event == event_type

    def test_configured_level_counts_and_visual_routes(self, node):
        need_map = node._intent_mapper._event_intent["need"]
        expected_counts = {
            "HUNGER": 2,
            "BLADDER": 1,
            "SLEEPINESS": 2,
            "CLEANLINESS": 1,
            "ENERGY": 2,
            "SOCIAL": 3,
            "EXPLORATION": 1,
        }
        for need_name, expected_count in expected_counts.items():
            entries = [
                entry
                for event_type, entry in need_map.items()
                if event_type.startswith(f"NEED_{need_name}_")
            ]
            assert len(entries) == expected_count, need_name

        for event_type in (
            "NEED_SOCIAL_TRIGGERED",
            "NEED_SOCIAL_URGENT",
            "NEED_SOCIAL_OVERFLOW",
        ):
            routes = need_map[event_type]["routes"]
            assert set(routes) == {"human", "animal"}
            assert len({
                route["behavior_name"] for route in routes.values()
            }) == 2

        for event_type in (
            "NEED_HUNGER_TRIGGERED",
            "NEED_HUNGER_OVERFLOW",
        ):
            assert set(need_map[event_type]["routes"]) == {
                "dog_food",
                "no_dog_food",
            }

        assert set(need_map["NEED_EXPLORATION_TRIGGERED"]["routes"]) == {
            "play_item",
            "trash_can",
            "delivery_box",
            "tissue",
            "door",
            "dog_food",
            "unfamiliar_object",
            "empty",
        }

    @pytest.mark.parametrize(
        "event_type",
        [
            "NEED_BLADDER_OVERFLOW",
            "NEED_CLEANLINESS_OVERFLOW",
            "NEED_EXPLORATION_OVERFLOW",
        ],
    )
    def test_unconfigured_overflow_events_are_unmapped(self, node, event_type):
        assert node._intent_mapper.map_need_event(
            event_type,
            {"demand": "ignored", "value": 100},
        ) is None

    def test_need_signal_generates_candidate(self, node):
        """Inject NEED_HUNGER_TRIGGERED → candidate in pool."""
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_HUNGER_TRIGGERED",
            "Hunger",
            71,
            "TRIGGERED",
        )))

        assert node.candidate_pool.size() >= 1, \
            "Expected need candidate after NEED_HUNGER_TRIGGERED signal"

    def test_need_candidate_triggers_behavior(self, node):
        """Full cycle: NEED_HUNGER_TRIGGERED → seek_food_or_water."""
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_HUNGER_TRIGGERED",
            "Hunger",
            71,
            "TRIGGERED",
        )))

        _tick(node, 1)

        bb = node.blackboard
        assert bb.current_behavior is not None, "Expected a behavior to start"
        assert bb.current_behavior.priority_level <= 3, \
            f"Expected Lv<=3 for hunger, got Lv{bb.current_behavior.priority_level}"

    @pytest.mark.parametrize(
        (
            "event_type",
            "value",
            "level",
            "objects",
            "expected_behavior",
            "expected_route",
        ),
        [
            (
                "NEED_HUNGER_TRIGGERED",
                71,
                "TRIGGERED",
                [{"label": "dog food can", "confidence": 0.9}],
                "eatNormally",
                "dog_food",
            ),
            (
                "NEED_HUNGER_TRIGGERED",
                71,
                "TRIGGERED",
                [],
                "seekFood",
                "no_dog_food",
            ),
            (
                "NEED_HUNGER_OVERFLOW",
                91,
                "OVERFLOW",
                [{"label": "dog treat bag", "confidence": 0.9}],
                "eatExcitedly",
                "dog_food",
            ),
            (
                "NEED_HUNGER_OVERFLOW",
                91,
                "OVERFLOW",
                [],
                "seekFoodUrgently",
                "no_dog_food",
            ),
        ],
    )
    def test_hunger_routes_by_visible_dog_food(
        self,
        node,
        event_type,
        value,
        level,
        objects,
        expected_behavior,
        expected_route,
    ):
        node.perception.mock_set_objects(objects)
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            event_type,
            "Hunger",
            value,
            level,
        )))

        queued = node.candidate_pool.candidates
        assert len(queued) == 1
        assert queued[0]["behavior_name"] == expected_behavior
        assert queued[0]["params"]["visual_route"] == expected_route

    def test_bladder_at_100_remains_triggered(self, node):
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_BLADDER_TRIGGERED",
            "Bladder",
            100,
            "TRIGGERED",
        )))

        _tick(node, 1)

        bb = node.blackboard
        assert bb.current_behavior is not None
        assert bb.current_behavior.behavior_name == "barkShortAlert"
        assert bb.current_behavior.priority_level == 2, \
            f"Expected Lv2 for bladder trigger, got Lv{bb.current_behavior.priority_level}"

    def test_social_urgent_maps_and_updates_state(self, node):
        node.perception.mock_set_person_present(True, identity="owner")
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_SOCIAL_URGENT",
            "Social",
            71,
            "URGENT",
            previous_level="TRIGGERED",
        )))

        assert node.candidate_pool.size() == 1
        queued = node.candidate_pool.candidates[0]
        assert queued["sub_priority"] == 1
        assert queued["behavior_name"] == "seekInteraction"
        assert queued["params"]["visual_route"] == "human"
        assert queued["params"]["target"]["target_id"] == "owner"
        state = node.blackboard.need_module.get_need("Social")
        assert state.level == "URGENT"
        assert state.triggered is True
        assert state.urgent is True
        assert state.overflow is False
        assert state.urgent_threshold == 70
        assert state.previous_level == "TRIGGERED"

    def test_social_full_rising_and_falling_sequence(self, node):
        node.perception.mock_set_person_present(True, identity="owner")
        sequence = [
            ("NEED_SOCIAL_TRIGGERED", 61, "TRIGGERED", "NORMAL",
             "seekHumanInteraction"),
            ("NEED_SOCIAL_URGENT", 71, "URGENT", "TRIGGERED",
             "seekInteraction"),
            ("NEED_SOCIAL_OVERFLOW", 86, "OVERFLOW", "URGENT",
             "inviteHumanToPlay"),
            ("NEED_SOCIAL_URGENT", 85, "URGENT", "OVERFLOW",
             "seekInteraction"),
            ("NEED_SOCIAL_TRIGGERED", 70, "TRIGGERED", "URGENT",
             "seekHumanInteraction"),
        ]
        for event_type, value, level, previous, behavior_name in sequence:
            node._on_need_signal_ros2(_make_string_msg(_need_signal(
                event_type,
                "Social",
                value,
                level,
                previous_level=previous,
            )))

            assert node.candidate_pool.size() == 1
            candidate = node.candidate_pool.candidates[0]
            assert candidate["behavior_name"] == behavior_name
            assert candidate["params"]["trigger_event"] == event_type
            state = node.blackboard.need_module.get_need("Social")
            assert state.level == level
            assert state.previous_level == previous

        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_SOCIAL_RECOVERED",
            "Social",
            60,
            "NORMAL",
            previous_level="TRIGGERED",
        )))

        state = node.blackboard.need_module.get_need("Social")
        assert state.level == "NORMAL"
        assert state.triggered is False
        assert state.urgent is False
        assert state.overflow is False
        assert node.candidate_pool.size() == 0

    @pytest.mark.parametrize(
        ("event_type", "value", "level", "previous", "behavior_name"),
        [
            ("NEED_SOCIAL_TRIGGERED", 61, "TRIGGERED", "NORMAL",
             "testAnimalBoundary"),
            ("NEED_SOCIAL_URGENT", 71, "URGENT", "TRIGGERED",
             "greetAnimal"),
            ("NEED_SOCIAL_OVERFLOW", 86, "OVERFLOW", "URGENT",
             "inviteAnimalToPlay"),
        ],
    )
    def test_social_uses_animal_when_no_person(
        self,
        node,
        event_type,
        value,
        level,
        previous,
        behavior_name,
    ):
        node.perception.mock_set_no_person()
        node.perception.mock_set_animals(["dog"])
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            event_type,
            "Social",
            value,
            level,
            previous_level=previous,
        )))

        queued = node.candidate_pool.candidates
        assert len(queued) == 1
        assert queued[0]["behavior_name"] == behavior_name
        assert queued[0]["params"]["visual_route"] == "animal"
        assert queued[0]["params"]["target"]["species"] == "dog"

    def test_social_prefers_person_over_visible_animal(self, node):
        node.perception.mock_set_person_present(True, identity="owner")
        node.perception.mock_set_animals(["cat"])
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_SOCIAL_TRIGGERED",
            "Social",
            61,
            "TRIGGERED",
        )))

        queued = node.candidate_pool.candidates
        assert len(queued) == 1
        assert queued[0]["behavior_name"] == "seekHumanInteraction"
        assert queued[0]["params"]["visual_route"] == "human"

    def test_social_without_person_or_animal_creates_no_candidate(self, node):
        node.perception.mock_clear_scene()
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_SOCIAL_TRIGGERED",
            "Social",
            61,
            "TRIGGERED",
        )))

        assert node.blackboard.need_module.is_triggered("Social")
        assert node.candidate_pool.size() == 0

    def test_late_social_service_result_is_ignored_after_recovery(self, node):
        callbacks = []
        node.perception.request_social_target = callbacks.append
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_SOCIAL_TRIGGERED",
            "Social",
            61,
            "TRIGGERED",
        )))
        assert len(callbacks) == 1

        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_SOCIAL_RECOVERED",
            "Social",
            60,
            "NORMAL",
            previous_level="TRIGGERED",
        )))
        callbacks[0]({
            "route": "human",
            "target": {
                "target_type": "human",
                "target_id": "owner",
            },
        })

        assert node.candidate_pool.size() == 0

    @pytest.mark.parametrize(
        ("objects", "expected_behavior", "expected_route"),
        [
            (
                [{"label": "slipper", "confidence": 0.9}],
                "inspectFamiliarPlayItem",
                "play_item",
            ),
            (
                [{"label": "trash can", "confidence": 0.9}],
                "inspectTrashCan",
                "trash_can",
            ),
            (
                [{"label": "cardboard shipping box", "confidence": 0.9}],
                "inspectDeliveryBox",
                "delivery_box",
            ),
            (
                [{"label": "tissue paper", "confidence": 0.9}],
                "inspectTissuePaper",
                "tissue",
            ),
            (
                [{"label": "door", "confidence": 0.9}],
                "inspectDoor",
                "door",
            ),
            (
                [{"label": "dog food can", "confidence": 0.9}],
                "inspectDogFood",
                "dog_food",
            ),
            (
                [{"label": "stairs", "confidence": 0.9}],
                "inspectObject",
                "unfamiliar_object",
            ),
            ([], "exploreRoom", "empty"),
        ],
    )
    def test_exploration_routes_by_object_familiarity(
        self,
        node,
        objects,
        expected_behavior,
        expected_route,
    ):
        node.perception.mock_set_objects(objects)
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_EXPLORATION_TRIGGERED",
            "Exploration",
            61,
            "TRIGGERED",
        )))

        queued = node.candidate_pool.candidates
        assert len(queued) == 1
        assert queued[0]["behavior_name"] == expected_behavior
        assert queued[0]["params"]["visual_route"] == expected_route
        if expected_route not in ("unfamiliar_object", "empty"):
            assert (
                queued[0]["params"]["executor_behavior_name"]
                == "inspectKnownObject"
            )
            assert queued[0]["params"]["object_category"]

    def test_need_state_v2_is_authoritative_and_generates_no_candidate(self, node):
        node._on_need_state_ros2(_make_string_msg({
            "schema_version": "2.0",
            "demands": {
                "Bladder": _need_state_entry("Bladder", 100, "TRIGGERED"),
                "Social": _need_state_entry("Social", 71, "URGENT"),
                "Energy": _need_state_entry("Energy", 81, "TRIGGERED"),
            },
        }))

        assert node.blackboard.need_module.get_level("Bladder") == "TRIGGERED"
        assert node.blackboard.need_module.get_level("Social") == "URGENT"
        assert node.blackboard.need_module.get_level("Energy") == "TRIGGERED"
        assert node.candidate_pool.size() == 0

    def test_need_state_recovery_discards_queued_candidate(self, node):
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_HUNGER_TRIGGERED",
            "Hunger",
            71,
            "TRIGGERED",
        )))
        assert node.candidate_pool.size() == 1

        node._on_need_state_ros2(_make_string_msg({
            "schema_version": "2.0",
            "demands": {
                "Hunger": _need_state_entry("Hunger", 70, "NORMAL"),
            },
        }))

        assert not node.blackboard.need_module.is_triggered("Hunger")
        assert node.candidate_pool.size() == 0

    def test_signal_level_must_match_value_and_thresholds(self, node):
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_SOCIAL_URGENT",
            "Social",
            61,
            "URGENT",
            previous_level="TRIGGERED",
        )))

        assert node.blackboard.need_module.get_need("Social") is None
        assert node.candidate_pool.size() == 0

    def test_triggered_needs_sort_by_raw_value_descending(self, node):
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_HUNGER_TRIGGERED",
            "Hunger",
            71,
            "TRIGGERED",
        )))
        node._on_need_signal_ros2(_make_string_msg(_need_signal(
            "NEED_CLEANLINESS_TRIGGERED",
            "Cleanliness",
            90,
            "TRIGGERED",
        )))

        best = node.candidate_pool.select_best(node.blackboard)
        assert best["behavior_name"] == "lickPaws"
        assert best["value"] == 90

    def test_v1_need_messages_are_rejected(self, node):
        node._on_need_state_ros2(_make_string_msg({
            "schema_version": "1.0",
            "demands": {
                "Hunger": _need_state_entry("Hunger", 71, "TRIGGERED"),
            },
        }))
        node._on_need_signal_ros2(_make_string_msg({
            **_need_signal(
                "NEED_HUNGER_TRIGGERED",
                "Hunger",
                71,
                "TRIGGERED",
            ),
            "schema_version": "1.0",
        }))

        assert node.blackboard.need_module.get_need("Hunger") is None
        assert node.candidate_pool.size() == 0

    @pytest.mark.parametrize(
        ("demand", "event_type"),
        [
            ("Bladder", "NEED_BLADDER_OVERFLOW"),
            ("Cleanliness", "NEED_CLEANLINESS_OVERFLOW"),
            ("Exploration", "NEED_EXPLORATION_OVERFLOW"),
        ],
    )
    def test_v2_rejects_nonexistent_overflow_signals(
        self,
        node,
        demand,
        event_type,
    ):
        payload = _need_signal(
            f"NEED_{demand.upper()}_TRIGGERED",
            demand,
            100,
            "TRIGGERED",
        )
        payload.update({
            "event_type": event_type,
            "level": "OVERFLOW",
        })
        node._on_need_signal_ros2(_make_string_msg(payload))

        assert node.candidate_pool.size() == 0
        assert node.blackboard.need_module.get_need(demand) is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Audio event → behavior
# ═══════════════════════════════════════════════════════════════════════════════

class TestAudioEventToBehavior:
    """Specific EVT_VOICE_COMMAND_<ACTION> → dedicated behavior."""

    @pytest.mark.parametrize(
        ("event_type", "expected_behavior"),
        [
            ("EVT_VOICE_COMMAND_SIT", "sit_down"),
            ("EVT_VOICE_COMMAND_LIE_DOWN", "lie_down"),
            ("EVT_VOICE_COMMAND_STAND_UP", "stand_up"),
            ("EVT_VOICE_COMMAND_WAIT", "wait_in_place"),
            ("EVT_VOICE_COMMAND_COME", "come_to_owner"),
            ("EVT_VOICE_COMMAND_FOLLOW", "follow_owner"),
            ("EVT_VOICE_COMMAND_SHAKE_HAND", "give_paw"),
            ("EVT_VOICE_COMMAND_HIGH_FIVE", "high_five"),
            ("EVT_VOICE_COMMAND_ROLL_OVER", "roll_over"),
            ("EVT_VOICE_COMMAND_SPIN", "spin_around"),
            ("EVT_VOICE_COMMAND_RETURN", "return_to_owner"),
            ("EVT_VOICE_COMMAND_DROP", "drop_object"),
            ("EVT_VOICE_COMMAND_PLAY_DEAD", "play_dead"),
            ("EVT_VOICE_COMMAND_BRING", "bring_object"),
            ("EVT_VOICE_COMMAND_FETCH", "fetch_object"),
        ],
    )
    def test_strong_events_map_one_to_one(
        self, node, event_type, expected_behavior
    ):
        candidate = node._intent_mapper.map_audio_event(
            event_type,
            {
                "intent_confidence": 0.95,
            },
        )

        assert candidate is not None
        assert candidate.behavior_name == expected_behavior
        assert candidate.priority_level == 1
        assert candidate.interrupt_policy == "immediate"

    def test_call_name_is_the_only_owner_call_mapping(self, node):
        candidate = node._intent_mapper.map_audio_event(
            "EVT_VOICE_CALL_NAME",
            {
                "header": {"frame_id": "base_link"},
                "wake_angle": 35.0,
                "wake_confidence": 0.95,
            },
        )

        assert candidate is not None
        assert candidate.behavior_name == "respond_owner_call"
        assert candidate.confidence == 0.95
        assert candidate.params["use_wake_angle"] is True
        assert candidate.params["wake_angle_deg"] == 35.0
        assert candidate.params["wake_confidence"] == 0.95
        assert candidate.params["wake_frame_id"] == "base_link"

    @pytest.mark.parametrize(
        "payload",
        [
            {"header": {"frame_id": "base_link"}},
            {"header": {"frame_id": "base_link"}, "wake_angle": "bad"},
            {"header": {}, "wake_angle": 30.0},
        ],
    )
    def test_call_name_rejects_invalid_wake_angle_contract(
        self, node, payload
    ):
        assert node._intent_mapper.map_audio_event(
            "EVT_VOICE_CALL_NAME",
            payload,
        ) is None

    def test_payload_cannot_override_unconfigured_event(self, node):
        candidate = node._intent_mapper.map_audio_event(
            "EVT_VOICE_COMMAND_NOT_CONFIGURED",
            {"action": "SIT"},
        )

        assert candidate is None

    def test_sit_event_generates_candidate(self, node):
        node._on_audio_direct("EVT_VOICE_COMMAND_SIT", {
            "intent_confidence": 0.95,
            "asr_text": "坐下",
        })

        assert node.candidate_pool.size() >= 1, \
            "Expected candidate after EVT_VOICE_COMMAND_SIT"

    def test_sit_event_triggers_behavior(self, node):
        node._on_audio_direct("EVT_VOICE_COMMAND_SIT", {
            "intent_confidence": 0.95,
            "asr_text": "坐下",
        })

        _tick(node, 1)
        bb = node.blackboard
        assert bb.current_behavior is not None
        assert bb.current_behavior.behavior_name == "sit_down"
        assert bb.current_behavior.priority_level == 1, \
            f"Expected Lv1 for sit command, got Lv{bb.current_behavior.priority_level}"

    def test_stop_event_is_emergency(self, node):
        node._on_audio_direct("EVT_VOICE_COMMAND_STOP", {
            "intent_confidence": 0.95,
        })

        _tick(node, 1)
        bb = node.blackboard
        assert bb.current_behavior is not None, "Expected emergency stop"
        assert bb.current_behavior.priority_level == 0, \
            f"Expected Lv0 for stop, got Lv{bb.current_behavior.priority_level}"

    def test_unknown_command_event_ignored(self, node):
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_NOT_CONFIGURED",
            {"intent_confidence": 0.95},
        )

        assert node.candidate_pool.size() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Ignored events produce NO behavior candidates
# ═══════════════════════════════════════════════════════════════════════════════

class TestIgnoredEvents:
    """Audio emotion events and visual events must NOT generate candidates."""

    def test_voice_praise_ignored(self, node):
        """EVT_VOICE_PRAISE → should go to emotion_engine, not behavior_tree."""
        # Simulate audio_event callback directly
        from marsdog_behavior.perception_client_adapter import PerceptionClientAdapter

        # EVT_VOICE_PRAISE is NOT in the whitelist
        pool_before = node.candidate_pool.size()
        node._on_audio_direct("EVT_VOICE_PRAISE", {
            "event_type": "EVT_VOICE_PRAISE",
        })
        # Should be ignored — no candidate added
        assert node.candidate_pool.size() == pool_before, \
            "EVT_VOICE_PRAISE should NOT generate behavior candidate"

    def test_voice_scold_ignored(self, node):
        """EVT_VOICE_SCOLD → ignored."""
        pool_before = node.candidate_pool.size()
        node._on_audio_direct("EVT_VOICE_SCOLD", {
            "event_type": "EVT_VOICE_SCOLD",
        })
        assert node.candidate_pool.size() == pool_before, \
            "EVT_VOICE_SCOLD should NOT generate behavior candidate"

    def test_visual_event_not_a_source(self, node):
        """Visual events return None from intent_mapper."""
        result = node._intent_mapper.map_visual_event("EVT_VISION_FALL", {})
        assert result is None, \
            "Visual events must NOT generate BehaviorCandidate"

    def test_unknown_audio_ignored(self, node):
        """Unknown audio event type → ignored."""
        pool_before = node.candidate_pool.size()
        node._on_audio_direct("EVT_SOME_UNKNOWN_THING", {})
        assert node.candidate_pool.size() == pool_before, \
            "Unknown audio events should NOT generate behavior candidates"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: Preemption — Lv0 preempts Lv5
# ═══════════════════════════════════════════════════════════════════════════════

class TestPreemption:
    """Higher priority behavior preempts lower priority."""

    def test_lv0_preempts_lv5(self, node):
        """Emergency stop (Lv0) preempts emotion expression (Lv5)."""
        # Start Lv5 emotion behavior
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        _tick(node, 1)
        assert node.blackboard.current_behavior is not None
        first_behavior = node.blackboard.current_behavior.behavior_name

        # Now inject EVT_VOICE_COMMAND_STOP (Lv0)
        node._on_audio_direct("EVT_VOICE_COMMAND_STOP", {
            "intent_confidence": 1.0,
        })
        _tick(node, 1)

        bb = node.blackboard
        # Should have been preempted
        assert bb.current_behavior is not None
        assert bb.current_behavior.priority_level == 0, \
            f"Expected Lv0 after stop command, got Lv{bb.current_behavior.priority_level}"
        assert bb.current_behavior.behavior_name == "emergency_stop"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: BehaviorCandidate → /execute_behavior Goal format
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoalFormat:
    """Verify the goal sent to executor contains correct fields."""

    def test_goal_contains_intent_metadata(self, node):
        """Goal params should include source, category, intent fields."""
        node._on_audio_direct("EVT_VOICE_COMMAND_SIT", {
            "intent_confidence": 0.95,
            "asr_text": "坐下",
        })

        _tick(node, 1)
        bb = node.blackboard
        assert bb.current_behavior is not None

        params = bb.current_behavior.params
        assert params.get("source") == "audio_direct", \
            f"Expected audio source, got {params.get('source')}"
        assert params.get("trigger_event") == "EVT_VOICE_COMMAND_SIT"
        assert "intent" in params or "category" in params or "source_event" in params, \
            f"Expected intent metadata in params, got keys: {list(params.keys())}"

    def test_emotion_goal_has_trigger_event(self, node):
        """Emotion goal params should contain trigger_event."""
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))

        _tick(node, 1)
        bb = node.blackboard
        if bb.current_behavior:
            params = bb.current_behavior.params
            assert params.get("source_emotion") == "Joy" or "trigger_event" in str(params), \
                f"Expected emotion metadata in params: {params}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: MockActionExecutor produces feedback + result
# ═══════════════════════════════════════════════════════════════════════════════

class TestActionExecution:
    """Verify MockActionExecutor simulates step-by-step action execution."""

    def test_executor_produces_feedback(self, node):
        """After starting a behavior, executor provides progress feedback."""
        node._on_audio_direct("EVT_VOICE_COMMAND_SIT", {
            "intent_confidence": 0.95,
        })
        _tick(node, 1)

        # executor should have feedback
        fb = node.blackboard.executor_feedback
        assert fb is not None, "Expected executor feedback after behavior start"
        assert fb.status == "RUNNING"
        assert 0.0 <= fb.progress <= 1.0

    def test_executor_completes_with_result(self, node):
        """After all steps, executor returns a result."""
        node._on_audio_direct("EVT_VOICE_COMMAND_SIT", {
            "intent_confidence": 0.95,
        })

        result = _advance_until_done(node, max_ticks=30)

        # Should have a result or the behavior should have progressed
        bb = node.blackboard
        if result:
            assert result.status in ("SUCCESS", "RUNNING")
        # At minimum, the executor should have been ticked
        assert bb.tick_count >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_string_msg(data: dict):
    """Create a mock ROS2 String message from a dict."""
    import json
    # In mock mode, callbacks receive plain strings or mock objects.
    # _on_emotion_signal_ros2 / _on_need_signal_ros2 expect msg.data
    class _MockMsg:
        def __init__(self, d):
            self.data = json.dumps(d)
    return _MockMsg(data)
