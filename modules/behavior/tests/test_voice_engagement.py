from bionic_dog_bt.arbitration import evaluate_preemption
from bionic_dog_bt.datatypes import ExecutorFeedback
from bionic_dog_bt.visual_context import select_wake_speaker
from marsdog_behavior.candidate_pool import CandidatePool
from marsdog_behavior.intent_mapper import IntentMapper


def _person(
    target_id,
    *,
    bearing,
    confidence,
    identity="unknown",
    identity_confidence=0.0,
):
    return {
        "vision_epoch": "epoch-1",
        "target_id": target_id,
        "track_id": int(target_id.rsplit(":", 1)[-1]),
        "target_type": "human",
        "identity": identity,
        "identity_state": (
            "confirmed_known" if identity != "unknown" else "unknown"
        ),
        "identity_confidence": identity_confidence,
        "detection_confidence": confidence,
        "tracking_state": "tracking",
        "last_seen_age_ms": 20.0,
        "bearing_deg": bearing,
        "range_valid": True,
        "distance_m": 2.0,
    }


def test_wake_speaker_uses_bearing_before_familiar_identity():
    familiar_elsewhere = _person(
        "epoch-1:human:1",
        bearing=28.0,
        confidence=0.99,
        identity="owner",
        identity_confidence=0.99,
    )
    unknown_caller = _person(
        "epoch-1:human:2",
        bearing=1.0,
        confidence=0.70,
    )

    selected = select_wake_speaker(
        [familiar_elsewhere, unknown_caller],
        reference_bearing_deg=0.0,
    )
    assert selected["target_id"] == "epoch-1:human:2"
    assert selected["selection_reason"] == "wake_bearing_first"


def test_wake_speaker_rejects_stale_or_unstable_targets():
    stale = _person("epoch-1:human:1", bearing=0.0, confidence=0.9)
    stale["last_seen_age_ms"] = 500.0
    no_epoch = _person("epoch-1:human:2", bearing=0.0, confidence=0.9)
    no_epoch["vision_epoch"] = ""
    assert select_wake_speaker([stale, no_epoch], max_age_ms=300.0) is None


def test_wake_speaker_rejects_person_outside_sound_matching_sector():
    elsewhere = _person(
        "epoch-1:human:3", bearing=40.0, confidence=0.99
    )
    assert select_wake_speaker(
        [elsewhere], max_bearing_error_deg=25.0
    ) is None


def test_wake_speaker_bearing_error_wraps_at_180_degrees():
    candidate = _person(
        "epoch-1:human:4", bearing=-179.0, confidence=0.9
    )
    selected = select_wake_speaker(
        [candidate],
        reference_bearing_deg=179.0,
        max_bearing_error_deg=5.0,
    )
    assert selected["wake_bearing_error_deg"] == 2.0


def test_voice_approach_candidate_has_strict_target_lock():
    target = _person("epoch-1:human:7", bearing=0.0, confidence=0.9)
    candidate = IntentMapper().build_voice_approach_candidate(
        interaction_id="voice-1",
        target=target,
        wake_id="wake-1",
        speaker_id="owner",
        speaker_role="owner",
        speaker_status="matched",
        stand_off_distance_m=1.5,
        timeout_sec=160.0,
        ttl_sec=3.0,
    )
    assert candidate.behavior_name == "approach_voice_caller"
    assert candidate.priority_level == 1
    assert candidate.target["target_id"] == "epoch-1:human:7"
    assert candidate.params["strict_target_lock"] is True
    assert candidate.params["allow_target_switch"] is False
    assert candidate.params["session_preempt_rank"] == 20
    assert candidate.params["approach_timeout_sec"] == 160.0
    assert candidate.params["stand_off_distance_m"] == 1.5
    assert candidate.params["wake_id"] == "wake-1"
    assert candidate.to_pool_dict()["cooldown_sec"] == 0.0


def test_voice_command_preempts_same_session_approach_at_safe_feedback():
    allowed, reason = evaluate_preemption(
        1,
        50.0,
        "sit_down",
        1,
        100.0,
        "immediate",
        ExecutorFeedback(
            behavior_id="approach-1",
            behavior_name="approach_voice_caller",
            status="RUNNING",
            safe_to_interrupt=True,
        ),
        {
            "interaction_id": "voice-1",
            "session_preempt_rank": 0,
        },
        {
            "interaction_id": "voice-1",
            "session_preempt_rank": 20,
        },
    )
    assert allowed is True
    assert "same-session rank" in reason


def test_discard_session_does_not_clear_unrelated_candidates():
    pool = CandidatePool()
    for interaction_id, behavior_name in (
        ("voice-1", "approach_voice_caller"),
        ("voice-2", "sit_down"),
    ):
        assert pool.add(
            behavior_name,
            1,
            params={"interaction_id": interaction_id},
            dedup_key=(interaction_id, behavior_name),
        )
    assert pool.discard_session("voice-1") == 1
    assert pool.size() == 1
    assert pool.is_duplicate("sit_down") is True


def test_voice_idle_keeps_queued_long_behaviors_but_rechecks_waiting_emotion():
    pool = CandidatePool()
    for name, params in (
        ("follow_owner", {
            "lifecycle_scope": "behavior",
            "completion_policy": "until_preempted",
            "cancel_on_voice_idle": False,
        }),
        ("play_alone", {
            "lifecycle_scope": "behavior",
            "completion_policy": "until_preempted",
            "cancel_on_voice_idle": False,
        }),
        ("expressJoyInPlaceWithHuman", {
            "lifecycle_scope": "behavior",
            "session_role": "voice_waiting_emotion",
        }),
        ("respond_owner_call", {}),
    ):
        assert pool.add(
            name, 1,
            params={"interaction_id": "voice-1", **params},
            dedup_key=("voice-1", name),
        )

    assert pool.discard_session("voice-1") == 2
    assert {item["behavior_name"] for item in pool.candidates} == {
        "follow_owner", "play_alone",
    }
