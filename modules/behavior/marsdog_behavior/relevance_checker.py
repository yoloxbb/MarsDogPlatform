"""Relevance Checker — validates that a behavior candidate is still relevant.

Emotion V2 and internal need V2 relevance both read the authoritative
``triggered`` boolean from their periodic state topics.

Voice command candidates (event_once) only use TTL.
"""

from __future__ import annotations

from typing import Optional

from bionic_dog_bt.constants import EMOTION_BEHAVIOR_MAP, NEED_BEHAVIOR_MAP
from bionic_dog_bt.logger import get_logger, LogEvent

_log = get_logger("relevance")


def is_behavior_relevant(candidate: dict, blackboard) -> bool:
    """Check if a behavior candidate is still relevant.

    Args:
        candidate: dict with keys:
            behavior_name, need_type, params{trigger_event, source_emotion, source_need, ...}
        blackboard: Blackboard instance with emotion_module and need_module

    Returns:
        True if behavior should proceed, False if it should be skipped.
    """
    behavior_name = candidate.get("behavior_name", "")
    need_type = candidate.get("need_type", "")
    params = candidate.get("params", {})
    # ── Emotion-triggered behaviors ───────────────────────────────────
    if need_type == "emotional":
        emotion_name = params.get("source_emotion") or EMOTION_BEHAVIOR_MAP.get(behavior_name)
        if emotion_name is None:
            _log.event(LogEvent.RELEVANCE_FAIL,
                       behavior_name=behavior_name,
                       reason="missing_source_emotion")
            return False

        if not blackboard.emotion_module.is_triggered(emotion_name):
            em_state = blackboard.emotion_module.get_emotion(emotion_name)
            current_val = em_state.current_value if em_state else 0.0
            _log.event(LogEvent.RELEVANCE_FAIL,
                       behavior_name=behavior_name,
                       emotion=emotion_name,
                       current=round(current_val, 1),
                       triggered=False)
            return False
        _log.event(LogEvent.RELEVANCE_PASS,
                   behavior_name=behavior_name,
                   emotion=emotion_name,
                   triggered=True)
        return True

    # ── Need-triggered behaviors ──────────────────────────────────────
    if (
        params.get("source") == "need"
        or need_type in (
            "physiological",
            "physiological_urgent",
            "psychological",
        )
    ):
        need_name = params.get("source_need") or NEED_BEHAVIOR_MAP.get(behavior_name)
        if need_name is None:
            return True  # Can't determine need → allow

        if not blackboard.need_module.is_triggered(need_name):
            _log.event(LogEvent.RELEVANCE_FAIL,
                       behavior_name=behavior_name,
                       need=need_name,
                       level=blackboard.need_module.get_level(need_name))
            return False
        _log.event(LogEvent.RELEVANCE_PASS,
                   behavior_name=behavior_name,
                   need=need_name,
                   triggered=True)
        return True

    # ── Voice command, external, system, idle → always relevant ───────
    return True
