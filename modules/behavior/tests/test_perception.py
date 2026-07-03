"""Tests: audio command injection, check_person, and perception integration."""

from __future__ import annotations

import time
import pytest
from pathlib import Path

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.mock_perception_client import MockPerceptionClient
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.constants import (
    STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILURE,
    COMMAND_BEHAVIOR_MAP,
)


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


# ── Voice Command Tests ──────────────────────────────────────────────────────

class TestVoiceCommands:
    """Tests for inject_audio_command mapping."""

    def test_known_command_generates_behavior(self, runtime):
        root, bb, executor, provider, loader = runtime
        behavior = provider.inject_audio_command("CMD_SIT")
        assert behavior is not None
        assert behavior.behavior_name == "respond_owner_call"
        assert behavior.params.get("command_id") == "CMD_SIT"
        assert behavior.params.get("source") == "audio_command"

    def test_unknown_command_returns_none(self, runtime):
        root, bb, executor, provider, loader = runtime
        behavior = provider.inject_audio_command("CMD_UNKNOWN")
        assert behavior is None

    def test_cmd_praise_generates_express_happy(self, runtime):
        root, bb, executor, provider, loader = runtime
        behavior = provider.inject_audio_command("CMD_PRAISE")
        assert behavior is not None
        assert behavior.behavior_name == "express_happy"

    def test_cmd_stop_generates_emergency_stop(self, runtime):
        root, bb, executor, provider, loader = runtime
        behavior = provider.inject_audio_command("CMD_STOP")
        assert behavior is not None
        assert behavior.behavior_name == "emergency_stop"

    def test_voice_command_sets_person_present(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Voice command implies a person is speaking
        provider.inject_audio_command("CMD_PRAISE")
        assert bb.perception_client.is_person_present()

    def test_voice_command_in_tree(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Inject voice command and run through tree
        provider.inject_audio_command("CMD_COME_HERE")
        candidate = provider.select()
        bb.set_active_behavior(candidate)
        _tick(root, bb, 1)
        assert bb.current_behavior is not None
        assert bb.current_behavior.behavior_name == "respond_owner_call"
        assert bb.current_behavior.params.get("command_id") == "CMD_COME_HERE"


# ── check_person Integration Tests ───────────────────────────────────────────

class TestCheckPersonIntegration:
    """Tests for check_person at behavior execution time."""

    def test_emotional_behavior_sets_interactive_when_person_present(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Set person present
        bb.perception_client.set_person_present(True, identity="owner")

        # Inject express_happy (no voice command, so check_person runs at exec)
        provider.inject_happy_overflow(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert bb.current_behavior is not None
        assert bb.current_behavior.behavior_name == "express_happy"
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
        assert bb.current_behavior.behavior_name == "express_happy"
        assert bb.current_behavior.params.get("interactive") is False

    def test_voice_command_emotional_preserves_source(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Voice command already sets source="audio_command",
        # so check_person should NOT override interactive mode
        bb.perception_client.set_no_person()  # no person, but...

        provider.inject_audio_command("CMD_PRAISE")
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert bb.current_behavior is not None
        # Voice command implies person, so even though check_person says no,
        # the source="audio_command" flag prevents override
        assert bb.current_behavior.params.get("source") == "audio_command"

    def test_need_behavior_does_not_check_person(self, runtime):
        root, bb, executor, provider, loader = runtime
        # Need behaviors should NOT call check_person
        bb.perception_client.set_person_present(True)

        provider.inject_hunger(85)
        candidate = provider.select()
        bb.set_active_behavior(candidate)

        _tick(root, bb, 1)
        assert bb.current_behavior.behavior_name == "seek_food_or_water"
        # Need behavior should not have interactive param
        assert "interactive" not in bb.current_behavior.params


# ── COMMAND_BEHAVIOR_MAP Validation ──────────────────────────────────────────

class TestCommandMap:
    """Verify command mapping coverage."""

    def test_expected_commands_mapped(self):
        expected = {
            "CMD_SIT", "CMD_COME_HERE", "CMD_HAND", "CMD_FIVE",
            "CMD_FOLLOW", "CMD_STOP", "CMD_PRAISE", "CMD_COMFORT", "CMD_ENCOUR",
        }
        mapped = set(COMMAND_BEHAVIOR_MAP.keys())
        assert expected == mapped, f"Missing: {expected - mapped}, Extra: {mapped - expected}"
