"""Every advertised mock event must survive a real provider poll."""
import pytest
from marsdog_voice_interaction.providers.mock_event import MockEventProvider, MOCK_AUDIO_EVENT_TYPES
from marsdog_voice_interaction.messages.voice_event_types import ACTION_TO_VOICE_EVENT

@pytest.mark.parametrize("event_type", MOCK_AUDIO_EVENT_TYPES)
def test_advertised_mock_event_builds(event_type):
    event = MockEventProvider({"seed": 46}).build_event(event_type)
    assert event["event_type"] == event_type
    if event_type in ACTION_TO_VOICE_EVENT.values():
        assert event["should_trigger_behavior_tree"] is True
        assert ACTION_TO_VOICE_EVENT[event["action"]] == event_type

def test_seeded_local_session_reaches_go_home(monkeypatch):
    monkeypatch.setattr("marsdog_voice_interaction.providers.mock_event.time.monotonic", lambda: 10.0)
    provider = MockEventProvider({"seed": 46, "event_interval_sec": 0.0})
    provider.start()
    assert provider.poll_event()["event_type"] == "EVT_VOICE_WAKEUP"
    event = provider.poll_event()
    assert event["event_type"] == "EVT_VOICE_COMMAND_GO_HOME"
    assert event["intent"] == "GO_HOME" and event["control"] == "DO"
    assert provider.poll_event() is None


def test_integration_mock_uses_public_catalog_identifiers():
    from pathlib import Path
    from marsdog_voice_interaction.core.command_lexicon import CommandLexicon
    path = Path(__file__).parents[1] / "config/command_catalog.yaml"
    catalog = CommandLexicon(path)
    provider = MockEventProvider({"command_catalog": str(path)})
    for key, kind in ACTION_TO_VOICE_EVENT.items():
        match = catalog.get_command(key)
        if match is not None:
            event = provider.build_event(kind)
            assert event["command_id"] == match.command_id
            assert event["specific_event_type"] == match.event_type
