from collections import deque
import json
import time
from types import SimpleNamespace

from marsdog_behavior.perception_client_adapter import PerceptionClientAdapter
from marsdog_behavior.ros_node import BehaviorTreeRosNode


class _VoiceClient:
    def __init__(self):
        self.holds = []
        self.releases = []

    def hold(self, interaction_id, hold_token, *, lease_sec, callback=None):
        self.holds.append((interaction_id, hold_token, lease_sec))
        if callback:
            callback({"ok": True})
        return True

    def release(
        self,
        interaction_id,
        hold_token,
        *,
        reset_idle_timer,
        callback=None,
    ):
        self.releases.append(
            (interaction_id, hold_token, reset_idle_timer)
        )
        if callback:
            callback({"ok": True})
        return True


class _RejectingVoiceClient(_VoiceClient):
    def hold(self, interaction_id, hold_token, *, lease_sec, callback=None):
        self.holds.append((interaction_id, hold_token, lease_sec))
        if callback:
            callback({"ok": False, "error": "temporary failure"})
        return True


class _DeferredVoiceClient(_VoiceClient):
    def __init__(self):
        super().__init__()
        self.hold_callbacks = []

    def hold(self, interaction_id, hold_token, *, lease_sec, callback=None):
        self.holds.append((interaction_id, hold_token, lease_sec))
        self.hold_callbacks.append(callback)
        return True

    def complete_hold(self, index=0, result=None):
        callback = self.hold_callbacks[index]
        if callback:
            callback({"ok": True} if result is None else result)


class _Pool:
    def __init__(self):
        self.discarded = []

    def discard_session(self, interaction_id):
        self.discarded.append(interaction_id)
        return 0

    def discard_where(self, predicate):
        return 0


class _Runtime:
    def __init__(self):
        self.canceled = []
        self.pending_discarded = []

    def cancel_current_for_shutdown(self):
        return False

    def discard_pending_interaction(self, interaction_id):
        self.pending_discarded.append(interaction_id)
        return False

    def cancel_current_interaction(self, interaction_id, *, reason):
        self.canceled.append((interaction_id, reason))
        return None


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass

    def warn(self, *_args, **_kwargs):
        pass


class _Perception:
    def __init__(self):
        self.wake_queries = []

    def request_wake_speaker(self, callback, **kwargs):
        self.wake_queries.append((callback, kwargs))


class _Harness:
    _on_audio_direct = BehaviorTreeRosNode._on_audio_direct
    _audio_need_gate_allows = BehaviorTreeRosNode._audio_need_gate_allows
    _publish_attention_control = BehaviorTreeRosNode._publish_attention_control
    _candidate_allowed_during_interaction = (
        BehaviorTreeRosNode._candidate_allowed_during_interaction
    )
    _validate_wake_event = BehaviorTreeRosNode._validate_wake_event
    _audio_event_seen = BehaviorTreeRosNode._audio_event_seen
    _remember_audio_event = BehaviorTreeRosNode._remember_audio_event
    _request_voice_hold = BehaviorTreeRosNode._request_voice_hold
    _renew_voice_hold_if_due = BehaviorTreeRosNode._renew_voice_hold_if_due
    _expire_wake_target_query_if_due = (
        BehaviorTreeRosNode._expire_wake_target_query_if_due
    )
    _expire_wake_identity_if_due = BehaviorTreeRosNode._expire_wake_identity_if_due
    _continue_wake_after_identity = BehaviorTreeRosNode._continue_wake_after_identity
    _request_wake_speaker = BehaviorTreeRosNode._request_wake_speaker
    _on_wake_speaker_resolved = BehaviorTreeRosNode._on_wake_speaker_resolved
    _handle_voice_behavior_terminal = BehaviorTreeRosNode._handle_voice_behavior_terminal
    _release_voice_hold = BehaviorTreeRosNode._release_voice_hold
    _consume_voice_session_turn = (
        BehaviorTreeRosNode._consume_voice_session_turn
    )
    _close_voice_session = BehaviorTreeRosNode._close_voice_session
    _enter_voice_waiting = BehaviorTreeRosNode._enter_voice_waiting
    _defer_queued_voice_emotions = (
        BehaviorTreeRosNode._defer_queued_voice_emotions
    )
    _flush_pending_emotions = BehaviorTreeRosNode._flush_pending_emotions

    def __init__(self):
        self._voice_session = None
        self._voice_session_generation = 0
        self._seen_audio_event_keys = set()
        self._seen_audio_event_order = deque()
        self._voice_engagement = {
            "hold_lease_sec": 6.0,
            "hold_renew_interval_sec": 2.0,
        }
        self._voice_session_client = _VoiceClient()
        self._candidate_pool = _Pool()
        self._runtime = _Runtime()
        self._perception = _Perception()
        self._pending_emotion_edges = {}
        self._pending_emotion_retry_at = {}
        self._attention_interaction_id = ""
        self._attention_mode = "face_body_centering"
        self._ros2_ready = False
        self.published = []
        self.candidates = []
        self._logger = _Logger()

    def _publish_attention_control(self, enabled, data):
        self.published.append((enabled, self._attention_mode, dict(data)))

    def _add_candidate(self, candidate):
        self.candidates.append(candidate)
        return True

    _intent_mapper = type("Mapper", (), {
        "map_audio_event": staticmethod(
            lambda event_type, data: {"behavior_name": (
                "respond_owner_call"
                if event_type == "EVT_VOICE_WAKEUP"
                else "follow_owner"
            )}
        ),
        "build_voice_approach_candidate": staticmethod(
            lambda **kwargs: {"behavior_name": "approach_voice_caller", "params": kwargs}
        ),
    })()


def _wake(interaction_id="session-1"):
    return {
        "schema_version": 2,
        "header": {"stamp": 100.0, "frame_id": "microphone_array"},
        "event_type": "EVT_VOICE_WAKEUP",
        "interaction_id": interaction_id,
        "wake_angle": 20.0,
        "wake_confidence": 0.9,
    }


def _speaker_result(role, status, speaker_id, wake_id="wake-1"):
    return {
        "schema_version": 2,
        "event_type": "EVT_VOICE_WAKE_SPEAKER_RESULT",
        "interaction_id": "session-1",
        "wake_id": wake_id,
        "speaker_role": role,
        "speaker_status": status,
        "speaker_id": speaker_id,
    }


def _finish_wake_orientation(node, wake_id="wake-1"):
    node._handle_voice_behavior_terminal(
        SimpleNamespace(
            behavior_name="respond_owner_call",
            params={"interaction_id": "session-1", "wake_id": wake_id},
        ),
        SimpleNamespace(status="SUCCESS"),
    )


def test_owner_result_after_orientation_starts_one_locked_approach():
    node = _Harness()
    wake = _wake()
    wake["wake_id"] = "wake-1"
    node._on_audio_direct("EVT_VOICE_WAKEUP", wake)
    _finish_wake_orientation(node)
    assert node._voice_session.phase == "AWAITING_IDENTITY"
    assert not node._perception.wake_queries

    result = _speaker_result("owner", "matched", "owner")
    node._on_audio_direct(result["event_type"], result)
    assert node._voice_session.phase == "ACQUIRING_TARGET"
    callback, _ = node._perception.wake_queries[0]
    callback({
        "target_type": "human", "vision_epoch": "epoch-1",
        "target_id": "epoch-1:human:7", "identity": "unknown",
    })
    assert node._voice_session.phase == "APPROACHING"
    assert len(node.candidates) == 2
    assert node.candidates[-1]["params"]["speaker_id"] == "owner"
    assert node.candidates[-1]["params"]["target"]["target_id"] == "epoch-1:human:7"
    node._on_audio_direct(result["event_type"], result)
    assert len(node.candidates) == 2


def test_family_result_before_orientation_starts_query_after_turn():
    node = _Harness()
    wake = _wake()
    wake["wake_id"] = "wake-1"
    node._on_audio_direct("EVT_VOICE_WAKEUP", wake)
    result = _speaker_result("family", "matched", "family_member_2")
    node._on_audio_direct(result["event_type"], result)
    assert not node._perception.wake_queries
    _finish_wake_orientation(node)
    assert node._voice_session.phase == "ACQUIRING_TARGET"
    assert len(node._perception.wake_queries) == 1


def test_stranger_and_identity_timeout_wait_without_tracking_or_approach():
    for result in (_speaker_result("stranger", "no_match", "unknown"), None):
        node = _Harness()
        wake = _wake()
        wake["wake_id"] = "wake-1"
        node._on_audio_direct("EVT_VOICE_WAKEUP", wake)
        _finish_wake_orientation(node)
        if result is None:
            node._voice_session.metadata["identity_wait_started_at"] = time.monotonic() - 4
            node._expire_wake_identity_if_due()
            late = _speaker_result("owner", "matched", "owner")
            node._on_audio_direct(late["event_type"], late)
        else:
            node._on_audio_direct(result["event_type"], result)
        assert node._voice_session.phase == "WAITING"
        assert not node._perception.wake_queries
        assert len(node.candidates) == 1
        assert node.published[-1][0] is False


def test_known_visual_identity_conflict_vetoes_approach():
    node = _Harness()
    wake = _wake()
    wake["wake_id"] = "wake-1"
    node._on_audio_direct("EVT_VOICE_WAKEUP", wake)
    _finish_wake_orientation(node)
    result = _speaker_result("owner", "matched", "owner")
    node._on_audio_direct(result["event_type"], result)
    callback, _ = node._perception.wake_queries[0]
    callback({
        "target_type": "human", "vision_epoch": "epoch-1",
        "target_id": "epoch-1:human:7", "identity": "family_member_2",
        "identity_state": "confirmed_known",
    })
    assert node._voice_session.phase == "WAITING"
    assert len(node.candidates) == 1


def test_wakeup_creates_orientation_candidate_and_matching_idle_closes_session():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())

    assert node._voice_session.interaction_id == "session-1"
    assert node._voice_session.phase == "ORIENTING"
    assert node.candidates[-1]["behavior_name"] == "respond_owner_call"
    assert node._voice_session_client.holds
    # Background attention must not race the formal orientation Action.
    assert not node.published

    node._on_audio_direct("EVT_STATE_CHANGED", {
        "schema_version": 2,
        "event_type": "EVT_STATE_CHANGED",
        "interaction_id": "session-1",
        "state": "idle",
        "state_reason": "interaction_timeout",
    })
    assert node._voice_session.phase == "CLOSED"
    assert node.published[-1][0] is False
    assert node._voice_session_client.releases[-1][2] is False


def test_duplicate_wake_is_idempotent():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    assert len(node.candidates) == 1
    assert len(node._voice_session_client.holds) == 1


def test_new_wake_id_in_same_session_replaces_old_orientation():
    node = _Harness()
    first = _wake()
    first["wake_id"] = "wake-1"
    node._on_audio_direct("EVT_VOICE_WAKEUP", first)
    session = node._voice_session
    assert session.metadata["wake_id"] == "wake-1"

    result = {
        "schema_version": 2,
        "event_type": "EVT_VOICE_WAKE_SPEAKER_RESULT",
        "interaction_id": "session-1",
        "wake_id": "wake-1",
        "speaker_id": "owner",
        "speaker_role": "owner",
        "speaker_status": "matched",
    }
    node._on_audio_direct(result["event_type"], result)
    assert session.metadata["wake_speaker_role"] == "owner"

    second = _wake()
    second["wake_id"] = "wake-2"
    second["wake_angle"] = 40.0
    node._on_audio_direct("EVT_VOICE_WAKEUP", second)
    new_session = node._voice_session
    assert new_session is not session
    assert session.phase == "CLOSED"
    assert len(node.candidates) == 2
    assert new_session.wake_angle_deg == 40.0
    assert new_session.metadata["wake_speaker_status"] == "pending"
    node._on_audio_direct(result["event_type"], result)
    assert new_session.metadata["wake_speaker_status"] == "pending"

    result.update({"wake_id": "wake-2", "speaker_id": "unknown",
                   "speaker_role": "stranger", "speaker_status": "no_match"})
    node._on_audio_direct(result["event_type"], result)
    assert new_session.metadata["wake_speaker_role"] == "stranger"


def test_new_wake_waits_for_old_orientation_result_before_requeue():
    node = _Harness()
    first = _wake()
    first["wake_id"] = "wake-1"
    node._on_audio_direct("EVT_VOICE_WAKEUP", first)
    original_add = node._add_candidate
    busy = {"old_goal_running": True}

    def add_if_free(candidate):
        if busy["old_goal_running"] and candidate["behavior_name"] == "respond_owner_call":
            return False
        return original_add(candidate)

    node._add_candidate = add_if_free
    second = _wake()
    second["wake_id"] = "wake-2"
    node._on_audio_direct("EVT_VOICE_WAKEUP", second)
    assert len(node.candidates) == 1
    assert node._voice_session.metadata["pending_wake_candidate"] is not None
    assert node._runtime.canceled[-1][0] == "session-1"

    busy["old_goal_running"] = False
    node._handle_voice_behavior_terminal(
        SimpleNamespace(
            behavior_name="respond_owner_call",
            params={"interaction_id": "session-1", "wake_id": "wake-1"},
        ),
        SimpleNamespace(status="CANCELED"),
    )
    assert len(node.candidates) == 2
    assert "pending_wake_candidate" not in node._voice_session.metadata


def test_new_interaction_wake_also_requeues_after_old_result():
    node = _Harness()
    first = _wake("session-1")
    first["wake_id"] = "wake-1"
    node._on_audio_direct("EVT_VOICE_WAKEUP", first)
    original_add = node._add_candidate
    busy = {"old_goal_running": True}

    def add_if_free(candidate):
        if busy["old_goal_running"]:
            return False
        return original_add(candidate)

    node._add_candidate = add_if_free
    second = _wake("session-2")
    second["wake_id"] = "wake-2"
    node._on_audio_direct("EVT_VOICE_WAKEUP", second)
    assert node._voice_session.interaction_id == "session-2"
    assert len(node.candidates) == 1
    busy["old_goal_running"] = False
    node._handle_voice_behavior_terminal(
        SimpleNamespace(
            behavior_name="respond_owner_call",
            params={"interaction_id": "session-1", "wake_id": "wake-1"},
        ),
        SimpleNamespace(status="CANCELED"),
    )
    assert len(node.candidates) == 2


def test_wake_identity_result_reaches_tree_through_audio_adapter():
    node = _Harness()
    adapter = object.__new__(PerceptionClientAdapter)
    adapter._on_audio_direct = node._on_audio_direct
    wake = _wake()
    wake["wake_id"] = "wake-1"
    adapter._on_audio_ros2(SimpleNamespace(data=json.dumps(wake)))
    result = {
        "schema_version": 2,
        "event_type": "EVT_VOICE_WAKE_SPEAKER_RESULT",
        "interaction_id": "session-1",
        "wake_id": "wake-1",
        "speaker_id": "family_member_2",
        "speaker_role": "family",
        "speaker_status": "matched",
    }
    adapter._on_audio_ros2(SimpleNamespace(data=json.dumps(result)))
    assert node._voice_session.metadata["wake_speaker_role"] == "family"
    assert node._voice_session.metadata["wake_speaker_id"] == "family_member_2"


def test_wakeup_rejects_non_microphone_array_frame_before_session_creation():
    node = _Harness()
    event = _wake()
    event["header"]["frame_id"] = "base_link"

    node._on_audio_direct("EVT_VOICE_WAKEUP", event)

    assert node._voice_session is None
    assert not node.candidates
    assert not node._voice_session_client.holds


def test_follow_command_dispatches_goal_without_starting_session_follow():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    node._on_audio_direct("EVT_VOICE_COMMAND_FOLLOW", {
        "interaction_id": "session-1",
        "utterance_id": "utterance-1",
    })
    assert node._attention_mode == "face_body_centering"
    assert node.published[-1][:2] == (False, "face_body_centering")
    assert node.candidates[-1]["behavior_name"] == "follow_owner"
    assert node._voice_session.command_received is True
    assert len(node._voice_session_client.releases) == 1


def test_voice_command_release_never_reacquires_an_empty_hold_token():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    original_hold = node._voice_session_client.holds[0]

    node._on_audio_direct("EVT_VOICE_COMMAND_RETURN", {
        "interaction_id": "session-1",
        "utterance_id": "utterance-return-1",
    })
    session = node._voice_session
    assert session.command_received is True
    assert session.hold_token == ""
    assert node._voice_session_client.releases == [
        ("session-1", original_hold[1], False)
    ]

    # Reproduce many 10 Hz BT ticks after the lease is released.  None may
    # send hold_interaction again, especially not with an empty token.
    session.last_hold_attempted_at = 0.0
    session.last_hold_renewed_at = 0.0
    for _ in range(20):
        node._renew_voice_hold_if_due()

    assert node._voice_session_client.holds == [original_hold]
    assert all(hold_token for _, hold_token, _ in node._voice_session_client.holds)


def test_rejected_hold_retry_is_throttled_to_the_configured_interval():
    node = _Harness()
    node._voice_session_client = _RejectingVoiceClient()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    session = node._voice_session
    assert len(node._voice_session_client.holds) == 1

    # A rejection must not turn the 2 s renewal policy into a 10 Hz retry.
    for _ in range(20):
        node._renew_voice_hold_if_due()
    assert len(node._voice_session_client.holds) == 1

    session.last_hold_attempted_at = time.monotonic() - 3.0
    node._renew_voice_hold_if_due()
    assert len(node._voice_session_client.holds) == 2


def test_late_successful_hold_after_command_gets_compensating_release():
    node = _Harness()
    client = _DeferredVoiceClient()
    node._voice_session_client = client
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    session = node._voice_session
    token = session.hold_token
    assert session.hold_request_pending

    node._on_audio_direct("EVT_VOICE_COMMAND_RETURN", {
        "interaction_id": "session-1",
        "utterance_id": "utterance-return-late-hold",
    })
    assert client.releases == [("session-1", token, False)]

    # Simulate Voice processing the older hold after the first release.
    client.complete_hold()

    assert client.releases == [
        ("session-1", token, False),
        ("session-1", token, False),
    ]
    assert session.command_received is True
    assert session.hold_token == ""
    assert session.hold_active is False
    assert session.hold_request_pending is False


def test_late_successful_hold_after_waiting_resets_idle_timer_on_cleanup():
    node = _Harness()
    client = _DeferredVoiceClient()
    node._voice_session_client = client
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    session = node._voice_session
    token = session.hold_token

    node._enter_voice_waiting(session, reason="already_near")
    assert client.releases == [("session-1", token, True)]

    client.complete_hold()

    assert client.releases == [
        ("session-1", token, True),
        ("session-1", token, True),
    ]
    assert session.phase == "WAITING"
    assert session.hold_token == ""


def test_late_old_hold_after_new_wake_cannot_pollute_new_session():
    node = _Harness()
    client = _DeferredVoiceClient()
    node._voice_session_client = client
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake("session-1"))
    old_session = node._voice_session
    old_token = old_session.hold_token

    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake("session-2"))
    new_session = node._voice_session
    new_token = new_session.hold_token
    assert new_session is not old_session
    assert new_session.interaction_id == "session-2"
    assert new_session.hold_request_pending is True
    assert client.releases == [("session-1", old_token, False)]

    client.complete_hold(0)

    assert client.releases == [
        ("session-1", old_token, False),
        ("session-1", old_token, False),
    ]
    assert node._voice_session is new_session
    assert new_session.hold_token == new_token
    assert new_session.hold_request_pending is True
    assert new_session.hold_active is False


def test_late_hold_after_matching_idle_stays_closed_and_never_renews():
    node = _Harness()
    client = _DeferredVoiceClient()
    node._voice_session_client = client
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    session = node._voice_session
    token = session.hold_token

    node._on_audio_direct("EVT_STATE_CHANGED", {
        "schema_version": 2,
        "event_type": "EVT_STATE_CHANGED",
        "interaction_id": "session-1",
        "state": "idle",
        "state_reason": "interaction_timeout",
    })
    assert session.phase == "CLOSED"
    assert client.releases == [("session-1", token, False)]

    client.complete_hold()
    holds_before = list(client.holds)
    for _ in range(20):
        node._renew_voice_hold_if_due()

    assert client.releases == [
        ("session-1", token, False),
        ("session-1", token, False),
    ]
    assert client.holds == holds_before
    assert session.phase == "CLOSED"
    assert session.hold_token == ""


def test_request_hold_rejects_blank_token_without_calling_voice():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    session = node._voice_session
    holds_before = list(node._voice_session_client.holds)
    session.hold_token = "   "
    session.hold_request_pending = False
    session.command_received = False

    node._request_voice_hold(session)

    assert node._voice_session_client.holds == holds_before
    node._renew_voice_hold_if_due()
    assert node._voice_session_client.holds == holds_before


def test_stale_session_end_does_not_stop_current_session():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake("session-2"))
    node._on_audio_direct("EVT_STATE_CHANGED", {
        "schema_version": 2,
        "event_type": "EVT_STATE_CHANGED",
        "interaction_id": "session-1",
        "state": "idle",
    })
    assert node._voice_session.phase == "ORIENTING"
    assert not node.published


def test_stale_session_command_cannot_drive_current_session():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake("session-2"))
    node._on_audio_direct("EVT_VOICE_COMMAND_FOLLOW", {
        "interaction_id": "session-1",
        "utterance_id": "old-utterance",
    })
    assert len(node.candidates) == 1
    assert node.candidates[0]["behavior_name"] == "respond_owner_call"
    assert node._attention_mode == "face_body_centering"
    assert node._voice_session.command_received is False


def _interactive_emotion_candidate():
    return {
        "behavior_name": "expressJoyInPlaceWithHuman",
        "priority_level": 5,
        "params": {
            "source": "emotion",
            "interaction_mode": "interactive",
            "interaction_variant": "voice_waiting",
            "interaction_id": "session-1",
            "session_role": "voice_waiting_emotion",
            "mobility_policy": "in_place",
            "visual_route": "human",
            "target": {"target_id": "person-1"},
        },
    }


def test_active_voice_session_blocks_lower_priority_candidates_while_orienting():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    assert node._candidate_allowed_during_interaction({"priority_level": 0})
    assert node._candidate_allowed_during_interaction({"priority_level": 1})
    assert not node._candidate_allowed_during_interaction({"priority_level": 2})
    assert not node._candidate_allowed_during_interaction({"priority_level": 5})
    assert not node._candidate_allowed_during_interaction(
        _interactive_emotion_candidate()
    )


def test_waiting_voice_session_allows_only_visual_with_human_emotion():
    node = _Harness()
    node._voice_engagement["waiting_emotion_enabled"] = True
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    node._voice_session.phase = "WAITING"
    node._attention_interaction_id = "session-1"

    assert node._candidate_allowed_during_interaction(
        _interactive_emotion_candidate()
    )
    assert not node._candidate_allowed_during_interaction({
        "priority_level": 5,
        "params": {
            "source": "emotion",
            "interaction_mode": "solo",
            "visual_route": "solo",
            "target": None,
        },
    })
    assert not node._candidate_allowed_during_interaction({
        "priority_level": 5,
        "params": {
            "source": "need",
            "interaction_mode": "interactive",
            "visual_route": "human",
            "target": {"target_id": "person-1"},
        },
    })


def test_voice_command_closes_waiting_emotion_exception():
    node = _Harness()
    node._voice_engagement["waiting_emotion_enabled"] = True
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    node._voice_session.phase = "WAITING"
    node._attention_interaction_id = "session-1"
    node._voice_session.command_received = True

    assert not node._candidate_allowed_during_interaction(
        _interactive_emotion_candidate()
    )


def test_waiting_emotion_feature_is_disabled_until_action_is_ready():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    node._voice_session.phase = "WAITING"
    node._attention_interaction_id = "session-1"

    assert not node._candidate_allowed_during_interaction(
        _interactive_emotion_candidate()
    )


def test_voice_idle_releases_lower_priority_gate():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())

    node._on_audio_direct("EVT_STATE_CHANGED", {
        "schema_version": 2,
        "event_type": "EVT_STATE_CHANGED",
        "interaction_id": "session-1",
        "state": "idle",
        "state_reason": "interaction_timeout",
    })
    assert node._candidate_allowed_during_interaction({"priority_level": 5})


def test_invalid_wake_contract_has_no_side_effect():
    node = _Harness()
    invalid = _wake()
    invalid["header"] = {}
    node._on_audio_direct("EVT_VOICE_WAKEUP", invalid)
    assert node._voice_session is None
    assert not node.candidates


def test_visual_query_timeout_invalidates_late_result_and_starts_waiting():
    node = _Harness()
    node._on_audio_direct("EVT_VOICE_WAKEUP", _wake())
    session = node._voice_session
    previous_generation = session.generation
    session.phase = "ACQUIRING_TARGET"
    session.metadata["target_query_started_at"] = time.monotonic() - 3.0
    node._voice_engagement["acquire_timeout_sec"] = 2.0

    node._expire_wake_target_query_if_due()

    assert session.phase == "WAITING"
    assert session.generation == previous_generation + 1
    assert "target_query_started_at" not in session.metadata
    assert node._voice_session_client.releases[-1][2] is True
    assert node.published[-1][0] is False
    assert node.published[-1][2]["wake_angle"] == 0.0
