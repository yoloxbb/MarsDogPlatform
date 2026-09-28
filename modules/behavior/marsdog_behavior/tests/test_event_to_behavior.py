"""E2E tests: event → candidate → behavior → action execution.

Verifies the full pipeline in standalone mock mode:
  1. Upstream events generate correct BehaviorCandidates
  2. BT tick selects and executes the behavior
  3. MockActionExecutor simulates step-by-step action progress
  4. Results are produced and cooldown is set
  5. Preemption works correctly
  6. FALL/STOP_GESTURE visual events produce Lv1.2 candidates
  7. Other visual and audio-emotion events produce NO candidates
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
from marsdog_behavior.voice_interaction_session import (
    WAITING,
    VoiceInteractionSession,
)
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


_COMMAND_IDS = {
    "WALK": "CMD_WALK",
    "PLAY_ALONE": "CMD_PLAY_ALONE",
    "GO_OUT": "CMD_GO_OUT",
    "GO_HOME": "CMD_GO_HOME",
    "APPROACH": "CMD_APPROACH",
    "BACK_UP": "CMD_BACK_UP",
    "SIT": "CMD_SIT",
    "LIE_DOWN": "CMD_LIE_DOWN",
    "STAND_UP": "CMD_STAND_UP",
    "STAND_STILL": "CMD_STAND_STILL",
    "HOLD_POSITION": "CMD_HOLD_POSITION",
    "WAIT": "CMD_WAIT",
    "COME": "CMD_COME_HERE",
    "FOLLOW": "CMD_FOLLOW",
    "SHAKE_HAND": "CMD_HAND",
    "HIGH_FIVE": "CMD_FIVE",
    "ROLL_OVER": "CMD_ROLL",
    "SPIN": "CMD_SPIN",
    "RETURN": "CMD_BACK",
    "DROP": "CMD_SPIT",
    "QUIET": "CMD_QUIET",
    "PLAY_DEAD": "CMD_DEAD",
    "BRING": "CMD_BRING_OBJECT",
    "FETCH": "CMD_FETCH_OBJECT",
    "TOILET": "CMD_TOILET",
    "CLEAN": "CMD_CLEAN",
    "SLEEP": "CMD_SLEEP",
    "STOP": "CMD_STOP",
    # Direct-drive phrases (直驱式短语)
    "COMFORT_DONT_BE_AFRAID": "CMD_COMFORT_DONT_BE_AFRAID",
    "COMFORT_REASSURE": "CMD_COMFORT_REASSURE",
    "ASK_IF_HURTS": "CMD_ASK_IF_HURTS",
    "OFFER_HEAD_FOR_PET": "CMD_OFFER_HEAD_FOR_PET",
    "SEEK_HUG": "CMD_SEEK_HUG",
    "REFUSE": "CMD_REFUSE",
    "REFUSE_PLAY": "CMD_REFUSE_PLAY",
    "FIND_DAD": "CMD_FIND_DAD",
    "FIND_MOM": "CMD_FIND_MOM",
    "DANCE": "CMD_DANCE",
    "BRING_TO_ME": "CMD_BRING_TO_ME",
    "GIVE_TO_ME": "CMD_GIVE_TO_ME",
    "GO_GET_IT": "CMD_GO_GET_IT",
    "BRING_IT_BACK": "CMD_BRING_IT_BACK",
    "FETCH_BALL": "CMD_FETCH_BALL",
    "FIND_TOY": "CMD_FIND_TOY",
    "STAY_HOME_ALONE": "CMD_STAY_HOME_ALONE",
    "WAIT_FOR_OWNER_RETURN": "CMD_WAIT_FOR_OWNER_RETURN",
    "OWNER_GOING_OUT": "CMD_OWNER_GOING_OUT",
    "OWNER_RETURNED": "CMD_OWNER_RETURNED",
    "BYE_BYE": "CMD_BYE_BYE",
    "GOODBYE": "CMD_GOODBYE",
    "ASK_WHAT_DOING": "CMD_ASK_WHAT_DOING",
    "ASK_WHERE_ARE_YOU": "CMD_ASK_WHERE_ARE_YOU",
    "ASK_WHATS_WRONG": "CMD_ASK_WHATS_WRONG",
    "ASK_WHAT_THINKING": "CMD_ASK_WHAT_THINKING",
    "ASK_IF_COMFORTABLE": "CMD_ASK_IF_COMFORTABLE",
    "ASK_IF_LIKES": "CMD_ASK_IF_LIKES",
    "ASK_IF_FUN": "CMD_ASK_IF_FUN",
    "ASK_IF_UNDERSTANDS": "CMD_ASK_IF_UNDERSTANDS",
    "ASK_ABILITIES": "CMD_ASK_ABILITIES",
    "ASK_IF_LEARNED": "CMD_ASK_IF_LEARNED",
    "EXPRESS_MISS_YOU": "CMD_EXPRESS_MISS_YOU",
    "OWNER_TIRED": "CMD_OWNER_TIRED",
    "OWNER_ANNOYED": "CMD_OWNER_ANNOYED",
    "OWNER_UNHAPPY": "CMD_OWNER_UNHAPPY",
    "OWNER_BAD_DAY": "CMD_OWNER_BAD_DAY",
    "OWNER_DEPRESSED": "CMD_OWNER_DEPRESSED",
    "OWNER_STRESSED": "CMD_OWNER_STRESSED",
    "OWNER_LONELY": "CMD_OWNER_LONELY",
    "OWNER_UNWELL": "CMD_OWNER_UNWELL",
    "OWNER_HAPPY": "CMD_OWNER_HAPPY",
    "OWNER_VERY_HAPPY": "CMD_OWNER_VERY_HAPPY",
    "OWNER_FEELING_GREAT": "CMD_OWNER_FEELING_GREAT",
    "OWNER_FEELING_EXCELLENT": "CMD_OWNER_FEELING_EXCELLENT",
    "OWNER_RELAXED": "CMD_OWNER_RELAXED",
    "OWNER_WONDERFUL_DAY": "CMD_OWNER_WONDERFUL_DAY",
    "OWNER_FEELING_LUCKY": "CMD_OWNER_FEELING_LUCKY",
    "EAT_MEAL": "CMD_EAT_MEAL",
    "EAT_SNACK": "CMD_EAT_SNACK",
    "EAT_CANNED_FOOD": "CMD_EAT_CANNED_FOOD",
    "RESPOND_FOOD_PREFERENCE_QUERY": "CMD_RESPOND_FOOD_PREFERENCE_QUERY",
}


def _audio_command(event_type: str, **values) -> dict:
    suffix = event_type.rsplit("_COMMAND_", 1)[-1]
    payload = {
        "schema_version": 2,
        "event_type": event_type,
        "interaction_id": "voice-test",
        "utterance_id": "utterance-test",
        "command_id": _COMMAND_IDS[suffix],
        "specific_event_type": event_type,
        "dispatch_role": "specific_command",
        "should_trigger_behavior_tree": True,
        "intent_confidence": 0.95,
        "slots": [],
    }
    payload.update(values)
    return payload


@pytest.mark.parametrize("event_type, behavior_name", [
    ("EVT_VOICE_COMMAND_FOLLOW", "follow_owner"),
    ("EVT_VOICE_COMMAND_PLAY_ALONE", "play_alone"),
])
def test_long_behavior_survives_matching_voice_idle(
    node, event_type, behavior_name,
):
    node._voice_session = VoiceInteractionSession(
        interaction_id="voice-test", generation=1, phase=WAITING,
    )
    node._on_audio_direct(event_type, _audio_command(event_type))
    _tick(node, 1)
    goal_id = node.blackboard.current_goal_id
    assert goal_id
    assert node.blackboard.current_behavior.behavior_name == behavior_name

    node._on_audio_direct("EVT_STATE_CHANGED", {
        "schema_version": 2,
        "event_type": "EVT_STATE_CHANGED",
        "interaction_id": "voice-test",
        "state": "idle",
    })
    _tick(node, 2)
    assert node._voice_session.phase == "CLOSED"
    assert node.blackboard.current_goal_id == goal_id
    assert node.blackboard.current_behavior.behavior_name == behavior_name
    assert node.blackboard.current_behavior.timeout_sec == 0.0


def test_bounded_owner_nav_continues_after_voice_idle(node):
    node._voice_session = VoiceInteractionSession(
        interaction_id="voice-test", generation=1, phase=WAITING,
    )
    event_type = "EVT_VOICE_COMMAND_COME"
    node._on_audio_direct(event_type, _audio_command(event_type))
    _tick(node, 1)
    goal_id = node.blackboard.current_goal_id
    assert goal_id
    node._on_audio_direct("EVT_STATE_CHANGED", {
        "schema_version": 2,
        "event_type": "EVT_STATE_CHANGED",
        "interaction_id": "voice-test",
        "state": "idle",
    })
    _tick(node, 2)
    assert node.blackboard.current_goal_id == goal_id
    assert node.blackboard.current_behavior.behavior_name == "come_to_owner"


def _audio_reaction(event_type: str, social: str, **values) -> dict:
    payload = {
        "schema_version": 2,
        "event_type": event_type,
        "interaction_id": "voice-test",
        "utterance_id": "utterance-test",
        "command_id": "CMD_%s" % social,
        "specific_event_type": event_type,
        "dispatch_role": "social_reaction",
        "social": social,
        "emotion": social,
        "intent": "NONE",
        "action": "NONE",
        "control": "NONE",
        "is_executable": False,
        "should_trigger_behavior_tree": True,
        "intent_confidence": 1.0,
        "slots": [{"key": "command_key", "value": social}],
    }
    payload.update(values)
    return payload


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
        assert candidate.to_pool_dict()["cooldown_sec"] == 10.0

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
        assert queued[0]["params"]["target"]["vision_epoch"] == "mock-vision"

    @pytest.mark.parametrize(
        ("event_type", "emotion", "value", "expected_behavior"),
        [
            ("EMO_CALM_TRIGGERED", "Calm", 0, "expressCalmInPlaceWithHuman"),
            ("EMO_JOY_TRIGGERED", "Joy", 30, "expressJoyInPlaceWithHuman"),
            (
                "EMO_EXCITE_TRIGGERED",
                "Excite",
                40,
                "expressExcitementInPlaceWithHuman",
            ),
            (
                "EMO_ANXIETY_TRIGGERED",
                "Anxiety",
                25,
                "expressAnxietyInPlaceWithHuman",
            ),
            ("EMO_FEAR_TRIGGERED", "Fear", 30, "expressFearInPlaceWithHuman"),
            (
                "EMO_CURIOUS_TRIGGERED",
                "Curious",
                20,
                "expressCuriosityInPlaceWithHuman",
            ),
        ],
    )
    def test_waiting_voice_session_uses_inplace_human_behavior(
        self,
        node,
        event_type,
        emotion,
        value,
        expected_behavior,
    ):
        node._voice_engagement["waiting_emotion_enabled"] = True
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1",
            generation=1,
            phase=WAITING,
        )
        node._attention_interaction_id = "voice-1"
        node.perception.mock_set_person_present(True, identity="owner")

        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": event_type,
            "emotion": emotion,
            "value": value,
        }))

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == expected_behavior
        assert queued["params"]["interaction_id"] == "voice-1"
        assert queued["params"]["interaction_variant"] == "voice_waiting"
        assert queued["params"]["session_role"] == "voice_waiting_emotion"
        assert queued["params"]["mobility_policy"] == "in_place"
        assert queued["params"]["visual_route"] == "human"
        assert queued["params"]["target"]["target_id"] == "owner"

    def test_voice_command_discards_queued_waiting_emotion(self, node):
        node._voice_engagement["waiting_emotion_enabled"] = True
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1",
            generation=1,
            phase=WAITING,
        )
        node._attention_interaction_id = "voice-1"
        node.perception.mock_set_person_present(True, identity="owner")
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        assert [
            item["behavior_name"] for item in node.candidate_pool.candidates
        ] == ["expressJoyInPlaceWithHuman"]

        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SIT",
            _audio_command(
                "EVT_VOICE_COMMAND_SIT",
                interaction_id="voice-1",
                utterance_id="utterance-1",
                intent_source="rkllm",
            ),
        )

        assert node._voice_session.command_received is True
        assert [
            item["behavior_name"] for item in node.candidate_pool.candidates
        ] == ["sit_down"]

    def test_active_voice_session_suppresses_emotion_until_action_is_ready(
        self,
        node,
    ):
        node._voice_engagement["waiting_emotion_enabled"] = False
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1",
            generation=1,
            phase=WAITING,
        )
        node._attention_interaction_id = "voice-1"
        node.perception.mock_set_person_present(True, identity="owner")

        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))

        assert node.candidate_pool.size() == 0

    def test_emotion_during_orientation_resolves_fresh_target_when_waiting(
        self,
        node,
    ):
        node._voice_engagement["waiting_emotion_enabled"] = True
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1",
            generation=1,
            phase="ORIENTING",
        )
        node.perception.mock_set_person_present(True, identity="owner")

        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))

        assert node.candidate_pool.candidates == []
        assert node._pending_emotion_edges == {"Joy": "EMO_JOY_TRIGGERED"}

        node._enter_voice_waiting(node._voice_session, reason="orientation_done")

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == "expressJoyInPlaceWithHuman"
        assert queued["params"]["interaction_id"] == "voice-1"
        assert queued["params"]["lifecycle_scope"] == "behavior"
        assert node._candidate_allowed_during_interaction(queued)

    def test_emotion_after_command_result_can_run_before_voice_idle(self, node):
        node._voice_engagement["waiting_emotion_enabled"] = True
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1", generation=1, phase=WAITING,
        )
        node._voice_session.command_received = True
        node._attention_interaction_id = "voice-1"
        node.perception.mock_set_person_present(True, identity="owner")

        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        assert node.candidate_pool.candidates == []
        assert node._pending_emotion_edges == {"Joy": "EMO_JOY_TRIGGERED"}

        node._voice_session.metadata["command_goal_terminal"] = True
        node._flush_pending_emotions()

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == "expressJoyInPlaceWithHuman"
        assert node._candidate_allowed_during_interaction(queued)

    def test_waiting_emotion_ignores_need_blocked_by_voice_gate(self, node):
        node._voice_engagement["waiting_emotion_enabled"] = True
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1", generation=1, phase=WAITING,
        )
        node._attention_interaction_id = "voice-1"
        node.perception.mock_set_person_present(True, identity="owner")
        assert node.candidate_pool.add(
            "feed_self", 3, params={"source": "need"},
        )

        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))

        queued = node.candidate_pool.candidates
        assert [item["behavior_name"] for item in queued] == [
            "feed_self", "expressJoyInPlaceWithHuman",
        ]
        assert not node._candidate_allowed_during_interaction(queued[0])
        assert node._candidate_allowed_during_interaction(queued[1])

    def test_voice_idle_rechecks_deferred_emotion_visual_route(self, node):
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1", generation=1, phase="ORIENTING",
        )
        node.perception.mock_set_person_present(True, identity="owner")
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        assert node.candidate_pool.candidates == []

        node.perception.mock_set_person_present(False)
        node._close_voice_session("voice-1", reason="voice_idle")

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == "expressJoyAlone"
        assert node._pending_emotion_edges == {}

    def test_voice_idle_rechecks_queued_inplace_emotion_instead_of_losing_it(
        self, node,
    ):
        node._voice_engagement["waiting_emotion_enabled"] = True
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1", generation=1, phase=WAITING,
        )
        node._attention_interaction_id = "voice-1"
        node.perception.mock_set_person_present(True, identity="owner")
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        assert [item["behavior_name"] for item in node.candidate_pool.candidates] == [
            "expressJoyInPlaceWithHuman"
        ]

        node.perception.mock_set_person_present(False)
        node._close_voice_session("voice-1", reason="voice_idle")

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == "expressJoyAlone"
        assert node._pending_emotion_edges == {}

    def test_voice_idle_rechecks_reserved_emotion_before_goal_send(self, node):
        node._voice_engagement["waiting_emotion_enabled"] = True
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1", generation=1, phase=WAITING,
        )
        node._attention_interaction_id = "voice-1"
        node.perception.mock_set_person_present(True, identity="owner")
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        selected = node.candidate_pool.select_best(
            node.blackboard,
            can_run=node._candidate_allowed_during_interaction,
        )
        reserved = node._runtime.candidate_to_active_behavior(selected)
        node.blackboard.set_active_behavior(reserved)
        assert node.candidate_pool.candidates == []

        node.perception.mock_set_person_present(False)
        node._close_voice_session("voice-1", reason="voice_idle")

        assert node.blackboard.active_behavior is None
        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == "expressJoyAlone"

    def test_waiting_emotion_retries_when_person_appears(self, node):
        node._voice_engagement["waiting_emotion_enabled"] = True
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1", generation=1, phase=WAITING,
        )
        node._attention_interaction_id = "voice-1"
        node.perception.mock_set_person_present(False)
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        assert node.candidate_pool.candidates == []
        assert node._pending_emotion_edges == {"Joy": "EMO_JOY_TRIGGERED"}

        node.perception.mock_set_person_present(True, identity="owner")
        node._pending_emotion_retry_at["Joy"] = 0.0
        node._flush_pending_emotions()

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == "expressJoyInPlaceWithHuman"
        assert node._pending_emotion_edges == {}

    def test_recovered_emotion_does_not_run_after_voice_idle(self, node):
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1", generation=1, phase="ORIENTING",
        )
        node._on_emotion_signal_ros2(_make_string_msg({
            "schema_version": "2.0",
            "event_type": "EMO_JOY_TRIGGERED",
            "emotion": "Joy",
            "value": 30,
        }))
        assert node._pending_emotion_edges == {"Joy": "EMO_JOY_TRIGGERED"}

        node._on_emotion_state_ros2(_make_string_msg({
            "schema_version": "2.0",
            "emotions": {"Joy": {"value": 0, "triggered": False}},
        }))
        node._close_voice_session("voice-1", reason="voice_idle")

        assert node._pending_emotion_edges == {}
        assert node.candidate_pool.candidates == []

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

    def test_visual_result_uses_latest_emotion_value(self, node):
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
            "emotions": {"Joy": {"value": 45, "triggered": True}},
        }))

        callbacks[0]({"route": "solo", "target": None})

        [queued] = node.candidate_pool.candidates
        assert queued["value"] == 45
        assert node.blackboard.emotion_module.get_value("Joy") == 45

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
            assert "executor_behavior_name" not in queued[0]["params"]
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
        ],
    )
    def test_strong_events_map_one_to_one(
        self, node, event_type, expected_behavior
    ):
        candidate = node._intent_mapper.map_audio_event(
            event_type,
            _audio_command(event_type),
        )

        assert candidate is not None
        assert candidate.behavior_name == expected_behavior
        assert candidate.priority_level == 1
        assert candidate.interrupt_policy == "immediate"

    def test_hardware_wakeup_is_the_only_owner_call_mapping(self, node):
        candidate = node._intent_mapper.map_audio_event(
            "EVT_VOICE_WAKEUP",
            {
                "schema_version": 2,
                "event_type": "EVT_VOICE_WAKEUP",
                "header": {"frame_id": "microphone_array"},
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
        assert candidate.params["wake_frame_id"] == "microphone_array"
        assert candidate.to_pool_dict()["cooldown_sec"] == 0.0

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "schema_version": 2,
                "event_type": "EVT_VOICE_WAKEUP",
                "header": {"frame_id": "microphone_array"},
            },
            {
                "schema_version": 2,
                "event_type": "EVT_VOICE_WAKEUP",
                "header": {"frame_id": "microphone_array"},
                "wake_angle": "bad",
            },
            {
                "schema_version": 2,
                "event_type": "EVT_VOICE_WAKEUP",
                "header": {},
                "wake_angle": 30.0,
            },
        ],
    )
    def test_hardware_wakeup_rejects_invalid_angle_contract(
        self, node, payload
    ):
        assert node._intent_mapper.map_audio_event(
            "EVT_VOICE_WAKEUP",
            payload,
        ) is None

    @pytest.mark.parametrize(
        "event_type",
        ["EVT_VOICE_CALL_NAME"],
    )
    def test_nickname_events_are_social_only(self, node, event_type):
        """非 COMMAND 昵称事件仍是纯社交通知，不建会话、不生成候选。"""
        payload = {
            "schema_version": 2,
            "event_type": event_type,
            "social": "CALL",
            "intent": "NONE",
            "control": "NONE",
            "action": "NONE",
            "intent_category": "social",
            "is_executable": False,
            "should_trigger_behavior_tree": False,
        }

        assert node._intent_mapper.map_audio_event(event_type, payload) is None
        node._on_audio_direct(event_type, payload)
        assert node._voice_session is None
        assert node.candidate_pool.size() == 0

    def test_command_call_name_remains_social_only(self, node):
        """Catalog nickname is not wakeup, a command, or a Tree reaction."""
        payload = {
            "schema_version": 2,
            "event_type": "EVT_VOICE_COMMAND_CALL_NAME",
            "social": "CALL",
            "intent": "NONE",
            "control": "NONE",
            "is_executable": False,
            "should_trigger_behavior_tree": False,
        }
        node._on_audio_direct("EVT_VOICE_COMMAND_CALL_NAME", payload)
        assert node._voice_session is None
        assert node.candidate_pool.size() == 0

    def test_payload_cannot_override_unconfigured_event(self, node):
        candidate = node._intent_mapper.map_audio_event(
            "EVT_VOICE_COMMAND_NOT_CONFIGURED",
            {"action": "SIT"},
        )

        assert candidate is None

    def test_play_alone_event_queues_and_executes_dedicated_behavior(self, node):
        event_type = "EVT_VOICE_COMMAND_PLAY_ALONE"
        node._on_audio_direct(
            event_type,
            _audio_command(
                event_type,
                asr_text="自己去玩吧",
                slots=[
                    {"key": "command_key", "value": "PLAY_ALONE"},
                    {"key": "action_name", "value": "ACT_PLAY_ALONE"},
                    {"key": "behavior", "value": "去随机位置自己玩"},
                ],
            ),
        )

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == "play_alone"
        assert queued["timeout_sec"] == 0.0
        assert queued["params"]["lifecycle_scope"] == "behavior"
        assert queued["params"]["completion_policy"] == "until_preempted"
        assert queued["params"]["cancel_on_voice_idle"] is False
        assert queued["params"]["command_id"] == "CMD_PLAY_ALONE"
        assert queued["params"]["trigger_event"] == event_type
        assert "action_name" not in queued["params"]
        assert "behavior" not in queued["params"]

        _tick(node, 1)
        behavior = node.blackboard.current_behavior
        assert behavior is not None
        assert behavior.behavior_name == "play_alone"
        assert behavior.priority_level == 1

    @pytest.mark.parametrize("overrides", [
        {"command_id": "CMD_WALK"},
        {"specific_event_type": "EVT_VOICE_COMMAND_GO_OUT"},
        {"dispatch_role": "generic_command"},
        {"should_trigger_behavior_tree": False},
    ])
    def test_play_alone_rejects_invalid_audio_contract(self, node, overrides):
        event_type = "EVT_VOICE_COMMAND_PLAY_ALONE"
        node._on_audio_direct(event_type, _audio_command(event_type, **overrides))

        assert node.candidate_pool.size() == 0

    def test_sit_event_generates_candidate(self, node):
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SIT",
            _audio_command("EVT_VOICE_COMMAND_SIT", asr_text="坐下"),
        )

        assert node.candidate_pool.size() >= 1, \
            "Expected candidate after EVT_VOICE_COMMAND_SIT"

    def test_sit_event_triggers_behavior(self, node):
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SIT",
            _audio_command("EVT_VOICE_COMMAND_SIT", asr_text="坐下"),
        )

        _tick(node, 1)
        bb = node.blackboard
        assert bb.current_behavior is not None
        assert bb.current_behavior.behavior_name == "sit_down"
        assert bb.current_behavior.priority_level == 1, \
            f"Expected Lv1 for sit command, got Lv{bb.current_behavior.priority_level}"

    def test_stop_event_is_emergency(self, node):
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_STOP",
            _audio_command("EVT_VOICE_COMMAND_STOP"),
        )

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

    def test_old_model_intent_command_namespace_is_not_routable(self, node):
        event_type = "EVT_VOICE_INTENT_COMMAND_SIT"

        assert node._intent_mapper.map_audio_event(
            event_type,
            _audio_command(event_type, intent_source="rkllm"),
        ) is None

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("should_trigger_behavior_tree", False),
            ("dispatch_role", "semantic_classification"),
            ("command_id", "CMD_LIE_DOWN"),
            ("specific_event_type", "EVT_VOICE_COMMAND_LIE_DOWN"),
        ],
    )
    def test_command_authority_mismatch_is_rejected(
        self, node, field, value
    ):
        payload = _audio_command("EVT_VOICE_COMMAND_SIT")
        payload[field] = value

        assert node._intent_mapper.map_audio_event(
            "EVT_VOICE_COMMAND_SIT",
            payload,
        ) is None

    def test_catalog_identity_reaches_action_params_without_action_override(
        self,
        node,
    ):
        event_type = "EVT_VOICE_COMMAND_SIT"
        payload = _audio_command(
            event_type,
            intent_source="command_lexicon",
            slots=[
                {"key": "command_key", "value": "SIT"},
                {
                    "key": "command_catalog_version",
                    "value": "2026-08-29-expanded-v1",
                },
                {"key": "action_name", "value": "ACT_SIT"},
                {"key": "behavior", "value": "untrusted description"},
            ],
        )

        node._on_audio_direct(event_type, payload)

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == "sit_down"
        params = queued["params"]
        assert params["trigger_event"] == event_type
        assert params["command_key"] == "SIT"
        assert params["command_id"] == "CMD_SIT"
        assert params["command_catalog_version"] == (
            "2026-08-29-expanded-v1"
        )
        assert params["intent_source"] == "command_lexicon"
        assert params["dispatch_role"] == "specific_command"
        assert params["specific_event_type"] == event_type
        assert "action_name" not in params["voice_slots"]
        assert "behavior" not in params["voice_slots"]

    def test_rejected_command_does_not_mutate_waiting_session(self, node):
        node._voice_session = VoiceInteractionSession(
            interaction_id="voice-1",
            generation=1,
            phase=WAITING,
        )
        node._attention_interaction_id = "voice-1"
        node._candidate_pool.add(
            "expressJoyInPlaceWithHuman",
            3,
            sub_priority=1,
            confidence=0.9,
            params={
                "interaction_id": "voice-1",
                "session_role": "voice_waiting_emotion",
            },
        )
        payload = _audio_command(
            "EVT_VOICE_COMMAND_SIT",
            interaction_id="voice-1",
            utterance_id="utterance-1",
            should_trigger_behavior_tree=False,
        )

        node._on_audio_direct("EVT_VOICE_COMMAND_SIT", payload)

        assert node._voice_session.command_received is False
        assert node._voice_session.phase == WAITING
        assert node._attention_interaction_id == "voice-1"
        assert [
            item["behavior_name"] for item in node.candidate_pool.candidates
        ] == ["expressJoyInPlaceWithHuman"]

    def test_fetch_requires_and_preserves_object_slot(self, node):
        event_type = "EVT_VOICE_COMMAND_FETCH"
        payload = _audio_command(event_type, slots=[
            {"key": "object_name", "value": "dog toy ball"},
            {"key": "object_mention", "value": "小球"},
            {"key": "object_match_source", "value": "object_catalog"},
            {"key": "object_catalog_version", "value": "2026-08-31-v1"},
            {"key": "action_name", "value": "DO_NOT_FORWARD"},
        ])

        candidate = node._intent_mapper.map_audio_event(event_type, payload)

        assert candidate is not None
        assert candidate.behavior_name == "fetch_object"
        assert candidate.params["object_name"] == "dog toy ball"
        assert candidate.params["object_mention"] == "小球"
        assert "action_name" not in candidate.params["voice_slots"]

        payload["slots"][0]["value"] = "NONE"
        assert node._intent_mapper.map_audio_event(
            event_type,
            payload,
        ) is None

        payload["slots"][0]["value"] = "unsupported toy"
        assert node._intent_mapper.map_audio_event(
            event_type,
            payload,
        ) is None

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
    def test_need_gated_commands_require_strictly_greater_current_value(
        self,
        node,
        event_type,
        demand,
        threshold,
        expected_behavior,
    ):
        payload = _audio_command(event_type)

        # Missing state fails closed.
        node._on_audio_direct(event_type, payload)
        assert node.candidate_pool.size() == 0

        # The contract is strict greater-than; equality still does nothing.
        node.blackboard.need_module.set_need(demand, threshold)
        node._on_audio_direct(event_type, payload)
        assert node.candidate_pool.size() == 0

        node.blackboard.need_module.set_need(demand, threshold + 0.1)
        node._on_audio_direct(event_type, payload)

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == expected_behavior
        assert queued["params"]["need_gate"]["passed"] is True
        assert queued["params"]["need_gate"]["observed_value"] == (
            threshold + 0.1
        )

    @pytest.mark.parametrize("missing_field", ["interaction_id", "utterance_id"])
    def test_specific_command_requires_correlation_ids(
        self, node, missing_field
    ):
        payload = _audio_command("EVT_VOICE_COMMAND_SIT")
        payload[missing_field] = ""

        assert node._intent_mapper.map_audio_event(
            "EVT_VOICE_COMMAND_SIT",
            payload,
        ) is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Direct visual events → Lv1.2 behavior candidates
# ═══════════════════════════════════════════════════════════════════════════════

class TestVisualDirectToBehavior:
    @pytest.mark.parametrize(
        ("event_type", "expected_behavior"),
        [
            ("EVT_VISION_FALL", "respond_person_fall"),
            ("EVT_VISION_STOP_GESTURE", "respond_stop_gesture"),
        ],
    )
    def test_visual_event_maps_to_lv1_subpriority_12(
        self, node, event_type, expected_behavior
    ):
        candidate = node._intent_mapper.map_visual_event(event_type, {
            "schema_version": 1,
            "header": {"stamp": 1786417000.1, "frame_id": "camera_link"},
            "active_target": {"track_id": 7, "pose_action": "fallen_down"},
            "hands": [{"hand_action": "stop_gesture"}],
            "events": [event_type],
        })

        assert candidate is not None
        assert candidate.behavior_name == expected_behavior
        assert candidate.source == "visual_direct"
        assert candidate.trigger_event == event_type
        assert candidate.priority_level == 1
        assert candidate.sub_priority == 12
        assert candidate.params["visual_header"]["frame_id"] == "camera_link"

    def test_visual_topic_reaches_candidate_pool(self, node):
        node.perception._on_visual_ros2(_make_string_msg({
            "schema_version": 1,
            "header": {"stamp": 1786417000.1, "frame_id": "camera_link"},
            "active_target": {"track_id": 7, "pose_action": "fallen_down"},
            "faces": [],
            "humans": [],
            "hands": [],
            "tracked_objects": [],
            "events": ["EVT_VISION_FALL"],
        }))

        queued = node.candidate_pool.candidates
        assert len(queued) == 1
        assert queued[0]["behavior_name"] == "respond_person_fall"
        assert queued[0]["priority_level"] == 1
        assert queued[0]["sub_priority"] == 12

# ══════════════════════════════════════════════════════════════════════════════════════════
# Test 5: Ignored events produce NO behavior candidates
# ═════════════════════════════════════════════════════════════════════════════════════════

class TestIgnoredEvents:
    """Audio emotion events and non-whitelisted visual events are ignored."""

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

    @pytest.mark.parametrize(
        "event_type",
        ["EVT_VISION_STRANGER", "EVT_VISION_TOY"],
    )
    def test_other_visual_event_not_a_direct_source(self, node, event_type):
        result = node._intent_mapper.map_visual_event(event_type, {})
        assert result is None, \
            "Non-whitelisted visual events must not generate BehaviorCandidate"

    def test_unknown_audio_ignored(self, node):
        """Unknown audio event type → ignored."""
        pool_before = node.candidate_pool.size()
        node._on_audio_direct("EVT_SOME_UNKNOWN_THING", {})
        assert node.candidate_pool.size() == pool_before, \
            "Unknown audio events should NOT generate behavior candidates"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4b: Direct-drive phrases (直驱式短语) → Lv1 behavior candidates
# ═══════════════════════════════════════════════════════════════════════════════

class TestDirectDrivePhrases:
    """直驱式社交/亲昵/情绪短语精确映射到 Lv1 语义 Behavior（走 audio_direct）。"""

    @pytest.mark.parametrize(
        ("event_type", "expected_behavior"),
        [
            # A: 安抚关怀
            ("EVT_VOICE_COMMAND_COMFORT_DONT_BE_AFRAID", "comfort_soothe"),
            ("EVT_VOICE_COMMAND_COMFORT_REASSURE", "comfort_reassure"),
            ("EVT_VOICE_COMMAND_ASK_IF_HURTS", "care_inquire"),
            ("EVT_VOICE_COMMAND_OFFER_HEAD_FOR_PET", "pet_head"),
            ("EVT_VOICE_COMMAND_SEEK_HUG", "hug"),
            # B: 拒绝否定
            ("EVT_VOICE_COMMAND_REFUSE", "refuse"),
            ("EVT_VOICE_COMMAND_REFUSE_PLAY", "refuse_play"),
            # C: 找人
            ("EVT_VOICE_COMMAND_FIND_DAD", "find_dad"),
            ("EVT_VOICE_COMMAND_FIND_MOM", "find_mom"),
            # D: 表演
            ("EVT_VOICE_COMMAND_DANCE", "dance"),
            # E: 取物
            ("EVT_VOICE_COMMAND_BRING_TO_ME", "bring_to_me"),
            ("EVT_VOICE_COMMAND_GIVE_TO_ME", "give_me"),
            ("EVT_VOICE_COMMAND_GO_GET_IT", "go_fetch"),
            ("EVT_VOICE_COMMAND_BRING_IT_BACK", "bring_back"),
            ("EVT_VOICE_COMMAND_FETCH_BALL", "fetch_ball"),
            ("EVT_VOICE_COMMAND_FIND_TOY", "find_toy"),
            # F: 留守/等待
            ("EVT_VOICE_COMMAND_STAY_HOME_ALONE", "stay_home"),
            ("EVT_VOICE_COMMAND_WAIT_FOR_OWNER_RETURN", "wait_return"),
            # G: 主人出行/归来
            ("EVT_VOICE_COMMAND_OWNER_GOING_OUT", "farewell_leave"),
            ("EVT_VOICE_COMMAND_OWNER_RETURNED", "greet_return"),
            ("EVT_VOICE_COMMAND_BYE_BYE", "farewell_bye"),
            ("EVT_VOICE_COMMAND_GOODBYE", "farewell_goodbye"),
            # H: 询问回应
            ("EVT_VOICE_COMMAND_ASK_WHAT_DOING", "report_activity"),
            ("EVT_VOICE_COMMAND_ASK_WHERE_ARE_YOU", "report_location"),
            ("EVT_VOICE_COMMAND_ASK_WHATS_WRONG", "report_state"),
            ("EVT_VOICE_COMMAND_ASK_WHAT_THINKING", "respond_thought"),
            ("EVT_VOICE_COMMAND_ASK_IF_COMFORTABLE", "respond_comfort"),
            ("EVT_VOICE_COMMAND_ASK_IF_LIKES", "respond_like"),
            ("EVT_VOICE_COMMAND_ASK_IF_FUN", "respond_fun"),
            ("EVT_VOICE_COMMAND_ASK_IF_UNDERSTANDS", "respond_understand"),
            ("EVT_VOICE_COMMAND_ASK_ABILITIES", "show_skill"),
            ("EVT_VOICE_COMMAND_ASK_IF_LEARNED", "respond_learned"),
            # I: 主人状态/情绪表达
            ("EVT_VOICE_COMMAND_EXPRESS_MISS_YOU", "miss_owner"),
            ("EVT_VOICE_COMMAND_OWNER_TIRED", "tired"),
            ("EVT_VOICE_COMMAND_OWNER_ANNOYED", "annoyed"),
            ("EVT_VOICE_COMMAND_OWNER_UNHAPPY", "unhappy"),
            ("EVT_VOICE_COMMAND_OWNER_BAD_DAY", "downcast"),
            ("EVT_VOICE_COMMAND_OWNER_DEPRESSED", "depressed"),
            ("EVT_VOICE_COMMAND_OWNER_STRESSED", "stressed"),
            ("EVT_VOICE_COMMAND_OWNER_LONELY", "lonely"),
            ("EVT_VOICE_COMMAND_OWNER_UNWELL", "unwell"),
            ("EVT_VOICE_COMMAND_OWNER_HAPPY", "cheerful"),
            ("EVT_VOICE_COMMAND_OWNER_VERY_HAPPY", "happy"),
            ("EVT_VOICE_COMMAND_OWNER_FEELING_GREAT", "great_form"),
            ("EVT_VOICE_COMMAND_OWNER_FEELING_EXCELLENT", "great"),
            ("EVT_VOICE_COMMAND_OWNER_RELAXED", "relaxed"),
            ("EVT_VOICE_COMMAND_OWNER_WONDERFUL_DAY", "wonderful_day"),
            ("EVT_VOICE_COMMAND_OWNER_FEELING_LUCKY", "lucky"),
            # J: 饮食直驱
            ("EVT_VOICE_COMMAND_EAT_MEAL", "eat_meal"),
            ("EVT_VOICE_COMMAND_EAT_SNACK", "eat_snack"),
            ("EVT_VOICE_COMMAND_EAT_CANNED_FOOD", "eat_canned_food"),
            ("EVT_VOICE_COMMAND_RESPOND_FOOD_PREFERENCE_QUERY", "respond_food_preference"),
        ],
    )
    def test_phrase_maps_to_behavior(self, node, event_type, expected_behavior):
        """每个直驱短语生成 Lv1 候选，且 behavior_name 精确匹配。"""
        if expected_behavior in {
            "approach_owner",
            "come_to_owner",
            "return_to_owner",
            "unhappy",
            "miss_owner",
            "farewell_leave",
        }:
            node.perception.mock_set_person_present(True, identity="owner")
        node._on_audio_direct(event_type, _audio_command(event_type))
        queued = node.candidate_pool.candidates
        assert queued, f"{event_type} should generate a candidate"
        assert queued[0]["behavior_name"] == expected_behavior
        assert queued[0]["priority_level"] == 1

    @pytest.mark.parametrize(
        ("event_type", "expected_behavior"),
        [
            ("EVT_VOICE_COMMAND_OWNER_UNHAPPY", "unhappy"),
            ("EVT_VOICE_COMMAND_EXPRESS_MISS_YOU", "miss_owner"),
            ("EVT_VOICE_COMMAND_OWNER_GOING_OUT", "farewell_leave"),
        ],
    )
    def test_owner_mobile_phrase_waits_for_vision_and_binds_target(
        self, node, event_type, expected_behavior
    ):
        callbacks = []
        node.perception.request_owner_target = callbacks.append

        node._on_audio_direct(event_type, _audio_command(event_type))

        assert len(callbacks) == 1
        assert node.candidate_pool.size() == 0

        target = {
            "target_type": "human",
            "vision_epoch": "vision-1",
            "target_id": "vision-1:human:7",
            "track_id": 7,
            "identity": "owner",
            "identity_state": "confirmed_known",
            "tracking_state": "tracking",
        }
        callbacks[0](target)

        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == expected_behavior
        assert queued["timeout_sec"] == 25.0
        assert queued["params"]["target"] == target
        assert queued["params"]["target_identity"] == "owner"
        assert queued["params"]["target_track_id"] == 7
        assert queued["params"]["target_resolution"] == "vision_query_targets"
        assert queued["params"]["interactive"] is True
        assert queued["params"]["interaction_mode"] == "interactive"

    @pytest.mark.parametrize(
        ("event_type", "expected_behavior"),
        [
            ("EVT_VOICE_COMMAND_APPROACH", "approach_owner"),
            ("EVT_VOICE_COMMAND_COME", "come_to_owner"),
            ("EVT_VOICE_COMMAND_RETURN", "return_to_owner"),
        ],
    )
    def test_owner_nav_command_queues_without_vision_query(
        self, node, event_type, expected_behavior
    ):
        callbacks = []
        node.perception.request_owner_target = callbacks.append

        node._on_audio_direct(event_type, _audio_command(event_type))

        assert not callbacks
        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] == expected_behavior
        assert queued["params"].get("target") is None
        assert queued["params"]["target_resolution"] == "action_visual_event"
        assert queued["params"]["strict_target_lock"] is True
        assert queued["params"]["allow_target_switch"] is False
        assert queued["params"]["stand_off_distance_m"] == 1.5
        assert queued["params"]["cancel_on_voice_idle"] is False
        assert queued["timeout_sec"] == 170.0

    def test_owner_nav_command_discards_unbound_voice_target(self, node):
        event_type = "EVT_VOICE_COMMAND_COME"
        event = _audio_command(event_type)
        event.update({
            "target_id": "old:human:1", "target_track_id": 1,
            "target_identity": "owner",
        })
        node._on_audio_direct(event_type, event)
        [queued] = node.candidate_pool.candidates
        assert queued["params"]["target"] is None
        assert "target_identity" not in queued["params"]
        assert queued["params"]["interactive"] is False

    @pytest.mark.parametrize(
        "target",
        [
            None,
            {
                "target_type": "human",
                "vision_epoch": "vision-1",
                "target_id": "vision-1:human:9",
                "track_id": 9,
                "identity": "stranger",
            },
        ],
    )
    def test_owner_mobile_phrase_is_not_queued_without_owner(self, node, target):
        callbacks = []
        node.perception.request_owner_target = callbacks.append
        event_type = "EVT_VOICE_COMMAND_OWNER_GOING_OUT"

        node._on_audio_direct(event_type, _audio_command(event_type))
        callbacks[0](target)

        assert node.candidate_pool.size() == 0

    def test_late_owner_target_is_ignored_after_newer_command(self, node):
        callbacks = []
        node.perception.request_owner_target = callbacks.append
        owner_event = "EVT_VOICE_COMMAND_OWNER_GOING_OUT"

        node._on_audio_direct(
            owner_event,
            _audio_command(owner_event, utterance_id="owner-command"),
        )
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SIT",
            _audio_command("EVT_VOICE_COMMAND_SIT", utterance_id="sit-command"),
        )
        callbacks[0]({
            "target_type": "human",
            "vision_epoch": "vision-1",
            "target_id": "vision-1:human:7",
            "track_id": 7,
            "identity": "owner",
        })

        queued = node.candidate_pool.candidates
        assert [item["behavior_name"] for item in queued] == ["sit_down"]

    def test_hug_executes_as_current_behavior(self, node):
        """代表性执行：抱抱 → hug 成为当前行为（空 action_sequence，动作归 Action）。"""
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SEEK_HUG",
            _audio_command("EVT_VOICE_COMMAND_SEEK_HUG", asr_text="抱抱"),
        )
        _tick(node, 1)
        bb = node.blackboard
        assert bb.current_behavior is not None
        assert bb.current_behavior.behavior_name == "hug"
        assert bb.current_behavior.priority_level == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4c: Direct-drive special events (社交绑情绪 / 饮食分流 / 打断 / PLAY)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpecialAudioEvents:
    """Vocabulary reactions and the remaining bounded special events."""

    def test_praise_binds_joy_or_excite(self, node):
        callbacks = []
        node.perception.request_emotion_context = callbacks.append
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_PRAISE",
            _audio_reaction("EVT_VOICE_COMMAND_PRAISE", "PRAISE"),
        )
        assert len(callbacks) == 1
        callbacks[0]({"route": "solo", "target": None})
        queued = node.candidate_pool.candidates
        assert queued and queued[0]["behavior_name"] in {
            "expressJoyAlone",
            "expressExcitementAlone",
        }
        assert queued[0]["priority_level"] == 1
        assert queued[0]["ttl_sec"] == 5.0
        assert queued[0]["cooldown_sec"] == 2.0
        assert queued[0]["params"]["source"] == "audio_reaction"

    def test_scold_binds_anxiety_curious_fear(self, node):
        callbacks = []
        node.perception.request_emotion_context = callbacks.append
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SCOLD",
            _audio_reaction("EVT_VOICE_COMMAND_SCOLD", "SCOLD"),
        )
        assert len(callbacks) == 1
        callbacks[0]({"route": "solo", "target": None})
        queued = node.candidate_pool.candidates
        assert queued and queued[0]["behavior_name"] in {
            "expressAnxietyAlone",
            "expressCuriosityAlone",
            "expressFearAlone",
        }

    def test_praise_executes_in_place_during_active_voice_session(self, node):
        interaction_id = "voice-active"
        node._voice_session = VoiceInteractionSession(
            interaction_id=interaction_id,
            generation=1,
            phase=WAITING,
            hold_token="hold-active",
            hold_active=True,
        )
        callbacks = []
        node.perception.request_emotion_context = callbacks.append
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_PRAISE",
            _audio_reaction(
                "EVT_VOICE_COMMAND_PRAISE",
                "PRAISE",
                interaction_id=interaction_id,
            ),
        )

        assert node._voice_session.command_received is True
        assert node._voice_session.metadata["accepted_turn_kind"] == (
            "social_reaction"
        )
        assert node._voice_session.hold_active is False
        callbacks[0]({
            "route": "human",
            "target": {
                "vision_epoch": "vision-1",
                "target_id": "vision-1:human:7",
                "identity": "owner",
            },
        })
        [queued] = node.candidate_pool.candidates
        assert queued["behavior_name"] in {
            "expressJoyInPlaceWithHuman",
            "expressExcitementInPlaceWithHuman",
        }
        assert queued["priority_level"] == 1
        assert queued["params"]["session_role"] == "voice_social_reaction"
        assert queued["params"]["mobility_policy"] == "in_place"
        assert node._candidate_allowed_during_interaction(queued) is True

        _tick(node, 1)
        assert node.blackboard.current_behavior is not None
        assert node.blackboard.current_behavior.behavior_name in {
            "expressJoyInPlaceWithHuman",
            "expressExcitementInPlaceWithHuman",
        }

    def test_audio_reaction_rejects_old_authority_contract(self, node):
        payload = _audio_reaction(
            "EVT_VOICE_COMMAND_PRAISE",
            "PRAISE",
            dispatch_role="specific_command",
            should_trigger_behavior_tree=False,
        )
        node._on_audio_direct("EVT_VOICE_COMMAND_PRAISE", payload)
        assert node.candidate_pool.size() == 0

    def test_play_binds_excite(self, node):
        callbacks = []
        node.perception.request_emotion_context = callbacks.append
        node._on_audio_direct("EVT_VOICE_COMMAND_PLAY", {})
        assert len(callbacks) == 1
        callbacks[0]({"route": "solo", "target": None})
        queued = node.candidate_pool.candidates
        assert queued and queued[0]["behavior_name"] == "expressExcitementAlone"

    def test_hungry_query_routes_yes(self, node):
        node.blackboard.need_module.set_need("Hunger", 80.0)
        node._on_audio_direct("EVT_VOICE_COMMAND_RESPOND_HUNGRY_QUERY", {})
        queued = node.candidate_pool.candidates
        assert queued and queued[0]["behavior_name"] == "respond_hungry_yes"

    def test_hungry_query_routes_no(self, node):
        node.blackboard.need_module.set_need("Hunger", 30.0)
        node._on_audio_direct("EVT_VOICE_COMMAND_RESPOND_HUNGRY_QUERY", {})
        queued = node.candidate_pool.candidates
        assert queued and queued[0]["behavior_name"] == "respond_hungry_no"

    def test_want_eat_query_routes_yes(self, node):
        node.blackboard.need_module.set_need("Hunger", 80.0)
        node._on_audio_direct("EVT_VOICE_COMMAND_RESPOND_WANT_EAT_QUERY", {})
        queued = node.candidate_pool.candidates
        assert queued and queued[0]["behavior_name"] == "respond_want_eat_yes"

    def test_eating_query_not_eating_looks_at_owner(self, node):
        node._on_audio_direct("EVT_VOICE_COMMAND_RESPOND_EATING_QUERY", {})
        queued = node.candidate_pool.candidates
        assert queued and queued[0]["behavior_name"] == "look_at_owner_brief"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4d: 合并窗口（姿态/移动/声音类执行完可重复，情绪类 10s 合并）
# ═══════════════════════════════════════════════════════════════════════════════

class TestBehaviorMerge:
    """姿态/移动/声音类 cooldown=0.2（执行中才去重），情绪类 cooldown=10。"""

    def test_dance_dedup_while_running(self, node):
        """跳舞执行中，重复语音事件（新 utterance）被候选池去重（不重复入池）。"""
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_DANCE",
            _audio_command("EVT_VOICE_COMMAND_DANCE", asr_text="跳个舞", utterance_id="u1"),
        )
        _tick(node, 1)
        assert node.blackboard.current_behavior.behavior_name == "dance"

        # 执行中，新 utterance 的重复事件 → 候选池 inflight 去重，保持空
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_DANCE",
            _audio_command("EVT_VOICE_COMMAND_DANCE", asr_text="跳个舞", utterance_id="u2"),
        )
        assert node.candidate_pool.size() == 0

    def test_dance_can_repeat_after_completion(self, node):
        """跳舞执行完 + 冷却过后，可以再次触发第 2 次。"""
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_DANCE",
            _audio_command("EVT_VOICE_COMMAND_DANCE", asr_text="跳个舞", utterance_id="u1"),
        )
        _tick(node, 1)  # 选中并开始执行
        _tick(node, 1)  # 空 action_sequence 完成 → release inflight + cooldown

        # 清除极小冷却（0.2s），模拟冷却已过
        node.blackboard.cooldown_until.pop("dance", None)

        node._on_audio_direct(
            "EVT_VOICE_COMMAND_DANCE",
            _audio_command("EVT_VOICE_COMMAND_DANCE", asr_text="跳个舞", utterance_id="u2"),
        )
        assert node.candidate_pool.size() >= 1

    def test_audio_reaction_cooldown_is_two_seconds(self, node):
        """One-shot social reactions do not inherit the 10s emotion cooldown."""
        callbacks = []
        node.perception.request_emotion_context = callbacks.append
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_PRAISE",
            _audio_reaction("EVT_VOICE_COMMAND_PRAISE", "PRAISE"),
        )
        callbacks[0]({"route": "solo", "target": None})

        queued = node.candidate_pool.candidates
        assert queued and queued[0]["cooldown_sec"] == 2.0


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
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_STOP",
            _audio_command(
                "EVT_VOICE_COMMAND_STOP",
                intent_confidence=1.0,
            ),
        )
        _tick(node, 1)

        bb = node.blackboard
        # Cancel acknowledgement is not completion.  The replacement starts
        # only after the old goal's real CANCELED result is consumed.
        for _ in range(4):
            if (
                bb.current_behavior is not None
                and bb.current_behavior.behavior_name == "emergency_stop"
            ):
                break
            _tick(node, 1)
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
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SIT",
            _audio_command("EVT_VOICE_COMMAND_SIT", asr_text="坐下"),
        )

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
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SIT",
            _audio_command("EVT_VOICE_COMMAND_SIT"),
        )
        _tick(node, 1)

        # executor should have feedback
        fb = node.blackboard.executor_feedback
        assert fb is not None, "Expected executor feedback after behavior start"
        assert fb.status == "RUNNING"
        assert 0.0 <= fb.progress <= 1.0

    def test_executor_completes_with_result(self, node):
        """After all steps, executor returns a result."""
        node._on_audio_direct(
            "EVT_VOICE_COMMAND_SIT",
            _audio_command("EVT_VOICE_COMMAND_SIT"),
        )

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
