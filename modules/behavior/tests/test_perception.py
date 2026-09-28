"""Tests: audio event injection, check_person, and perception integration."""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.mock_perception_client import MockPerceptionClient
from bionic_dog_bt.constants import VOICE_EVENT_BEHAVIOR_MAP
from bionic_dog_bt.visual_context import (
    select_exploration_context,
    select_hunger_context,
    select_social_animal,
)
from marsdog_behavior.perception_client_adapter import PerceptionClientAdapter


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


# ── MockPerceptionClient Unit Tests ──────────────────────────────────────────

class TestPerceptionClient:
    """Unit tests for MockPerceptionClient."""

    def test_default_no_person(self):
        client = MockPerceptionClient()
        assert not client.is_person_present()
        result = client.check_person()
        assert result["present"] is False
        assert result["count"] == 0

    def test_set_person_present(self):
        client = MockPerceptionClient()
        client.set_person_present(True, identity="alice", count=2)
        assert client.is_person_present()
        result = client.check_person()
        assert result["present"] is True
        assert result["identity"] == "alice"
        assert result["count"] == 2

    def test_set_no_person(self):
        client = MockPerceptionClient()
        client.set_person_present(True)
        client.set_no_person()
        assert not client.is_person_present()

    def test_set_person_false_clears_stale_target(self):
        client = MockPerceptionClient()
        client.set_person_present(True, identity="owner")
        client.set_person_present(False)

        result = client.check_person()
        assert result["present"] is False
        assert result["count"] == 0
        assert result["identity"] == "unknown"
        assert result["active_target"] == {}

    def test_virtual_animals_and_objects(self):
        client = MockPerceptionClient()
        client.set_animals(["cat", "dog"])
        client.set_objects([
            *client.detect_objects(),
            {"label": "dog bowl", "confidence": 0.95},
        ])

        objects = client.detect_objects()
        assert {item["label"] for item in objects} == {
            "cat",
            "dog",
            "dog bowl",
        }


class TestVisualContext:
    def test_social_selects_highest_confidence_cat_or_dog(self):
        target = select_social_animal([
            {"label": "cat", "confidence": 0.7},
            {"label": "dog", "confidence": 0.9, "track_id": 7},
            {"label": "dog bowl", "confidence": 0.99},
        ])

        assert target["target_type"] == "animal"
        assert target["species"] == "dog"
        assert target["track_id"] == 7

    def test_visual_target_preserves_producer_stable_id_and_epoch(self):
        target = select_social_animal([{
            "label": "cat",
            "confidence": 0.91,
            "vision_epoch": "vision-1",
            "target_id": "vision-1:object:11",
            "track_id": 11,
        }])

        assert target["target_id"] == "vision-1:object:11"
        assert target["vision_epoch"] == "vision-1"
        assert target["track_id"] == 11

    @pytest.mark.parametrize(
        ("objects", "route"),
        [
            ([{"label": "slipper", "confidence": 0.8}], "play_item"),
            ([{"label": "sock", "confidence": 0.8}], "play_item"),
            ([{"label": "dog toy ball", "confidence": 0.8}], "play_item"),
            ([{"label": "trash can", "confidence": 0.8}], "trash_can"),
            (
                [{"label": "cardboard shipping box", "confidence": 0.8}],
                "delivery_box",
            ),
            ([{"label": "tissue paper", "confidence": 0.8}], "tissue"),
            ([{"label": "door", "confidence": 0.8}], "door"),
            ([{"label": "dog food can", "confidence": 0.8}], "dog_food"),
            ([{"label": "stairs", "confidence": 0.8}], "unfamiliar_object"),
            ([], "empty"),
        ],
    )
    def test_exploration_classification(self, objects, route):
        assert select_exploration_context(objects)["route"] == route

    @pytest.mark.parametrize(
        ("objects", "route"),
        [
            ([{"label": "dog food can", "confidence": 0.9}], "dog_food"),
            ([{"label": "dog treat bag", "confidence": 0.9}], "dog_food"),
            ([{"label": "dog bowl", "confidence": 0.9}], "no_dog_food"),
            ([], "no_dog_food"),
        ],
    )
    def test_hunger_classification(self, objects, route):
        assert select_hunger_context(objects)["route"] == route

    def test_legacy_service_object_json_is_normalized(self):
        result = {"objects": '[{"label":"cat","confidence":0.91}]'}

        assert PerceptionClientAdapter._objects_from_result(result) == [
            {"label": "cat", "confidence": 0.91}
        ]

    def test_failed_person_check_uses_scene_cache_before_animal_route(self):
        adapter = object.__new__(PerceptionClientAdapter)
        cached = {
            "route": "human",
            "target": {"target_type": "human", "target_id": "owner"},
        }
        adapter._social_context_from_cache = lambda: cached
        resolved = []

        adapter._on_social_person_result(None, resolved.append)

        assert resolved == [cached]

    def test_emotion_context_normalizes_legacy_string_boolean(self):
        adapter = object.__new__(PerceptionClientAdapter)
        adapter.get_active_identity = lambda: "owner"

        assert adapter._emotion_context_from_person({
            "present": "false",
            "count": "0",
        }) == {"route": "solo", "target": None}

        human = adapter._emotion_context_from_person({
            "present": "true",
            "count": "1",
        })
        assert human["route"] == "human"
        assert human["target"]["target_id"] == "owner"


# ── Voice Event Tests ────────────────────────────────────────────────────────

class TestVoiceEvents:
    """Tests for strict event_type mapping."""

    def test_known_event_generates_behavior(self, runtime):
        root, bb, executor, provider, loader = runtime
        behavior = provider.inject_audio_event("EVT_VOICE_COMMAND_SIT")
        assert behavior is not None
        assert behavior.behavior_name == "sit_down"
        assert behavior.params.get("trigger_event") == "EVT_VOICE_COMMAND_SIT"
        assert behavior.params.get("source") == "audio_direct"

    @pytest.mark.parametrize(
        ("event_type", "expected_behavior"),
        [
            ("EVT_VOICE_COMMAND_WALK", "walk_to_random_point"),
            ("EVT_VOICE_COMMAND_PLAY_ALONE", "play_alone"),
            ("EVT_VOICE_COMMAND_GO_OUT", "go_out_to_play"),
            ("EVT_VOICE_COMMAND_GO_HOME", "go_home"),
            ("EVT_VOICE_COMMAND_APPROACH", "approach_owner"),
            ("EVT_VOICE_COMMAND_BACK_UP", "back_up"),
            ("EVT_VOICE_COMMAND_SIT", "sit_down"),
            ("EVT_VOICE_COMMAND_LIE_DOWN", "lie_down"),
            ("EVT_VOICE_COMMAND_STAND_UP", "stand_up"),
            ("EVT_VOICE_COMMAND_STAND_STILL", "stand_still"),
            ("EVT_VOICE_COMMAND_HOLD_POSITION", "hold_position"),
            ("EVT_VOICE_COMMAND_WAIT", "wait_in_place"),
            ("EVT_VOICE_COMMAND_COME", "come_to_owner"),
            ("EVT_VOICE_COMMAND_FOLLOW", "follow_owner"),
            ("EVT_VOICE_COMMAND_SHAKE_HAND", "give_paw"),
            ("EVT_VOICE_COMMAND_HIGH_FIVE", "high_five"),
            ("EVT_VOICE_COMMAND_ROLL_OVER", "roll_over"),
            ("EVT_VOICE_COMMAND_SPIN", "spin_around"),
            ("EVT_VOICE_COMMAND_RETURN", "return_to_owner"),
            ("EVT_VOICE_COMMAND_DROP", "drop_object"),
            ("EVT_VOICE_COMMAND_QUIET", "quiet"),
            ("EVT_VOICE_COMMAND_PLAY_DEAD", "play_dead"),
            ("EVT_VOICE_COMMAND_BRING", "bring_object"),
            ("EVT_VOICE_COMMAND_FETCH", "fetch_object"),
        ],
    )
    def test_strong_events_have_dedicated_behaviors(
        self, runtime, event_type, expected_behavior
    ):
        root, bb, executor, provider, loader = runtime
        behavior = provider.inject_audio_event(event_type)

        assert behavior is not None
        assert behavior.behavior_name == expected_behavior
        assert behavior.priority_level == 1
        assert behavior.params["trigger_event"] == event_type

    def test_unknown_event_returns_none(self, runtime):
        root, bb, executor, provider, loader = runtime
        behavior = provider.inject_audio_event("EVT_VOICE_COMMAND_DOES_NOT_EXIST")
        assert behavior is None

    @pytest.mark.parametrize(
        ("event_type", "demand", "threshold", "expected_behavior"),
        [
            (
                "EVT_VOICE_COMMAND_TOILET",
                "Bladder",
                50.0,
                "barkShortAlert",
            ),
            (
                "EVT_VOICE_COMMAND_CLEAN",
                "Cleanliness",
                40.0,
                "lickPaws",
            ),
            (
                "EVT_VOICE_COMMAND_SLEEP",
                "Sleepiness",
                50.0,
                "sleepOnSide",
            ),
        ],
    )
    def test_standalone_need_gated_voice_commands(
        self,
        runtime,
        event_type,
        demand,
        threshold,
        expected_behavior,
    ):
        root, bb, executor, provider, loader = runtime

        assert provider.inject_audio_event(event_type) is None
        bb.need_module.set_need(demand, threshold)
        assert provider.inject_audio_event(event_type) is None

        bb.need_module.set_need(demand, threshold + 0.1)
        behavior = provider.inject_audio_event(event_type)
        assert behavior is not None
        assert behavior.behavior_name == expected_behavior

    @pytest.mark.parametrize(
        "event_type",
        ["EVT_VOICE_CALL_NAME", "EVT_VOICE_COMMAND_CALL_NAME"],
    )
    def test_standalone_nickname_social_events_are_not_actions(
        self,
        runtime,
        event_type,
    ):
        root, bb, executor, provider, loader = runtime

        assert provider.inject_audio_event(event_type) is None

    def test_stop_event_generates_emergency_stop(self, runtime):
        root, bb, executor, provider, loader = runtime
        behavior = provider.inject_audio_event("EVT_VOICE_COMMAND_STOP")
        assert behavior is not None
        assert behavior.behavior_name == "emergency_stop"

    def test_voice_event_sets_person_present(self, runtime):
        root, bb, executor, provider, loader = runtime
        provider.inject_audio_event("EVT_VOICE_COMMAND_SIT")
        assert bb.perception_client.is_person_present()

    def test_voice_event_in_tree(self, runtime):
        root, bb, executor, provider, loader = runtime
        provider.inject_audio_event("EVT_VOICE_COMMAND_COME")
        candidate = provider.select()
        bb.set_active_behavior(candidate)
        _tick(root, bb, 1)
        assert bb.current_behavior is not None
        assert bb.current_behavior.behavior_name == "come_to_owner"
        assert (
            bb.current_behavior.params.get("trigger_event")
            == "EVT_VOICE_COMMAND_COME"
        )


# ── check_person Integration Tests ───────────────────────────────────────────

class TestCheckPersonIntegration:
    """Tests for check_person at behavior execution time."""

    def test_emotional_behavior_sets_interactive_when_person_present(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Set person present
        bb.perception_client.set_person_present(True, identity="owner")

        # Inject express_happy, so check_person runs at execution time.
        provider.inject_happy_overflow(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert bb.current_behavior is not None
        assert bb.current_behavior.need_type == "emotional"
        # Interactive mode should be set (person present → interactive=True)
        assert bb.current_behavior.params.get("interactive") is True
        assert bb.current_behavior.params.get("target_identity") == "owner"

    def test_emotional_behavior_sets_solo_when_no_person(self, runtime):
        root, bb, executor, provider, loader = runtime
        # No person present
        bb.perception_client.set_no_person()

        provider.inject_happy_overflow(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert bb.current_behavior is not None
        assert bb.current_behavior.need_type == "emotional"
        # Solo mode (no person)
        assert bb.current_behavior.params.get("interactive") is False

    def test_need_behavior_does_not_check_person(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Need behaviors should NOT call check_person
        bb.perception_client.set_person_present(True)
        bb.perception_client.set_objects([
            {"label": "dog food can", "confidence": 0.9},
        ])

        provider.inject_hunger(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "eatNormally"
        # Hunger visual routing is object-based, not person-based.
        assert bb.current_behavior.params.get("interactive") is False
        assert bb.current_behavior.params["visual_route"] == "dog_food"


# ── VOICE_EVENT_BEHAVIOR_MAP Validation ──────────────────────────────────────

class TestVoiceEventMap:
    """Verify voice event mapping coverage."""

    def test_expected_events_mapped(self):
        expected = {
            "EVT_VOICE_WAKEUP",
            "EVT_VOICE_COMMAND_WALK",
            "EVT_VOICE_COMMAND_PLAY_ALONE",
            "EVT_VOICE_COMMAND_GO_OUT",
            "EVT_VOICE_COMMAND_GO_HOME",
            "EVT_VOICE_COMMAND_APPROACH",
            "EVT_VOICE_COMMAND_BACK_UP",
            "EVT_VOICE_COMMAND_SIT",
            "EVT_VOICE_COMMAND_LIE_DOWN",
            "EVT_VOICE_COMMAND_STAND_UP",
            "EVT_VOICE_COMMAND_STAND_STILL",
            "EVT_VOICE_COMMAND_HOLD_POSITION",
            "EVT_VOICE_COMMAND_WAIT",
            "EVT_VOICE_COMMAND_COME",
            "EVT_VOICE_COMMAND_FOLLOW",
            "EVT_VOICE_COMMAND_SHAKE_HAND",
            "EVT_VOICE_COMMAND_HIGH_FIVE",
            "EVT_VOICE_COMMAND_ROLL_OVER",
            "EVT_VOICE_COMMAND_SPIN",
            "EVT_VOICE_COMMAND_RETURN",
            "EVT_VOICE_COMMAND_DROP",
            "EVT_VOICE_COMMAND_QUIET",
            "EVT_VOICE_COMMAND_PLAY_DEAD",
            "EVT_VOICE_COMMAND_BRING",
            "EVT_VOICE_COMMAND_FETCH",
            "EVT_VOICE_COMMAND_TOILET",
            "EVT_VOICE_COMMAND_CLEAN",
            "EVT_VOICE_COMMAND_SLEEP",
            "EVT_VOICE_COMMAND_STOP",
        }
        mapped = set(VOICE_EVENT_BEHAVIOR_MAP)
        assert expected == mapped, f"Missing: {expected - mapped}, Extra: {mapped - expected}"
