from marsdog_behavior.ros_node import BehaviorTreeRosNode


class _Harness:
    _on_audio_direct = BehaviorTreeRosNode._on_audio_direct
    _publish_attention_control = BehaviorTreeRosNode._publish_attention_control

    def __init__(self):
        self._attention_interaction_id = ""
        self._attention_mode = "face_body_centering"
        self._ros2_ready = False
        self.published = []
        self._logger = type("Logger", (), {
            "info": lambda *_args, **_kwargs: None,
            "debug": lambda *_args, **_kwargs: None,
        })()

    def _publish_attention_control(self, enabled, data):
        self.published.append((enabled, self._attention_mode, dict(data)))

    def _add_candidate(self, candidate):
        self.candidate = candidate

    _intent_mapper = type("Mapper", (), {
        "map_audio_event": staticmethod(lambda event_type, data: (
            {"behavior_name": "follow_owner"}
            if event_type == "EVT_VOICE_COMMAND_FOLLOW" else None
        )),
    })()


def test_wakeup_starts_and_matching_idle_event_stops_attention():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_CALL_NAME", {
        "interaction_id": "session-1",
        "wake_angle": 20.0,
    })
    assert node._attention_interaction_id == "session-1"
    assert node.published[-1][0] is True

    node._on_audio_direct("EVT_STATE_CHANGED", {
        "interaction_id": "session-1",
        "state": "idle",
        "state_reason": "interaction_timeout",
    })
    assert node._attention_interaction_id == ""
    assert node.published[-1][0] is False


def test_follow_command_switches_session_to_closed_loop_follow_mode():
    node = _Harness()
    node._attention_interaction_id = "session-1"
    node._on_audio_direct("EVT_VOICE_COMMAND_FOLLOW", {
        "interaction_id": "session-1",
    })
    assert node._attention_mode == "follow_owner"
    assert node.published[-1][:2] == (True, "follow_owner")
    assert node.candidate["behavior_name"] == "follow_owner"


def test_stale_session_end_does_not_stop_current_attention():
    node = _Harness()
    node._attention_interaction_id = "session-2"
    node._on_audio_direct("EVT_STATE_CHANGED", {
        "interaction_id": "session-1",
        "state": "idle",
    })
    assert node._attention_interaction_id == "session-2"
    assert not node.published
