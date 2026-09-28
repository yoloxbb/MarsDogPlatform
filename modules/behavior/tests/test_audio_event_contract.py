"""Static checks for the Voice AudioEvent v2 consumer contract."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent

FETCH_OBJECT_NAMES = {
    "dog toy ball",
    "dog frisbee toy",
    "dog tug ring toy",
    "dog collar",
    "dog bowl",
    "dog leash",
    "dog treat bag",
    "dog food can",
    "dog bed",
    "trash can",
    "cardboard shipping box",
    "sock",
    "slipper",
    "tissue paper",
    "door",
    "stairs",
    "cat",
    "dog",
}

NEED_GATED_COMMANDS = {
    "EVT_VOICE_COMMAND_TOILET": ("Bladder", 50.0, "barkShortAlert"),
    "EVT_VOICE_COMMAND_CLEAN": ("Cleanliness", 40.0, "lickPaws"),
    "EVT_VOICE_COMMAND_SLEEP": ("Sleepiness", 50.0, "sleepOnSide"),
}


def _load(name: str) -> dict:
    with (ROOT / "config" / name).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_every_audio_route_has_a_configured_behavior() -> None:
    event_map = _load("event_intent_map.yaml")["audio_direct"]
    intent_pool = _load("intent_action_pool.yaml")
    behaviors = _load("behaviors.yaml")["behaviors"]

    for event_type, route in event_map.items():
        # Hardware wake is not a voice command and has no command_id.
        if event_type != "EVT_VOICE_WAKEUP":
            assert route.get("expected_command_id"), event_type
        intent = route["intent"]
        candidates = intent_pool[intent]["candidates"]
        assert candidates, (event_type, intent)
        assert set(candidates) <= set(behaviors), (event_type, candidates)


def test_only_hardware_wakeup_owns_the_wake_route() -> None:
    event_map = _load("event_intent_map.yaml")["audio_direct"]

    assert "EVT_VOICE_WAKEUP" in event_map
    assert event_map["EVT_VOICE_WAKEUP"]["intent"] == "orient_to_sound"
    assert "EVT_VOICE_CALL_NAME" not in event_map
    assert "EVT_VOICE_COMMAND_CALL_NAME" not in event_map


def test_only_praise_and_scold_are_configured_audio_reactions() -> None:
    config = _load("event_intent_map.yaml")
    reactions = config["audio_reaction"]
    emotion_map = _load("emotion_behavior_map.yaml")["emotion_behavior_map"]

    assert set(reactions) == {
        "EVT_VOICE_COMMAND_PRAISE",
        "EVT_VOICE_COMMAND_SCOLD",
    }
    assert "EVT_VOICE_COMMAND_CALL_NAME" not in reactions
    available_emotions = {
        event_type.removeprefix("EMO_").removesuffix("_TRIGGERED")
        for event_type in emotion_map
    }
    # The configured vocabulary reactions reuse existing emotion routes while
    # retaining their own external-interaction priority and lifecycle.
    for event_type, route in reactions.items():
        assert route["category"] == "external_interaction", event_type
        assert route["expected_command_id"], event_type
        assert route["expected_social"] in {"PRAISE", "SCOLD"}
        assert route["ttl_sec"] < 30.0
        assert route["cooldown_sec"] < 20.0
        assert {
            reaction["emotion"].upper()
            for reaction in route["reactions"]
        } <= available_emotions


def test_model_intent_command_aliases_are_not_routable() -> None:
    event_map = _load("event_intent_map.yaml")["audio_direct"]

    assert not {
        event_type
        for event_type in event_map
        if event_type.startswith("EVT_VOICE_INTENT_COMMAND_")
    }


def test_need_gated_commands_reuse_existing_need_behaviors() -> None:
    event_map = _load("event_intent_map.yaml")["audio_direct"]
    intent_pool = _load("intent_action_pool.yaml")

    for event_type, (demand, threshold, behavior_name) in (
        NEED_GATED_COMMANDS.items()
    ):
        route = event_map[event_type]
        assert route["need_gate"] == {
            "demand": demand,
            "operator": "gt",
            "threshold": threshold,
        }
        assert intent_pool[route["intent"]]["candidates"] == [behavior_name]


def test_fetch_requires_a_supported_object_on_the_concrete_event() -> None:
    event_map = _load("event_intent_map.yaml")["audio_direct"]
    route = event_map["EVT_VOICE_COMMAND_FETCH"]

    assert route["required_voice_slots"] == ["object_name"]
    assert set(route["allowed_voice_slot_values"]["object_name"]) == (
        FETCH_OBJECT_NAMES
    )
