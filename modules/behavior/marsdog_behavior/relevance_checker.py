"""Relevance Checker — validates that a behavior candidate is still relevant.

For emotion/need-triggered behaviors, compares the stored trigger_event
(from /emotion/signal_event or /internal_need/signal_event) against the
current levelEvents from the periodic state topic.

This implements string-comparison-based relevance checking:
- The behavior tree does NOT do value-based threshold checks.
- It only compares event strings published by upstream nodes.

Voice command candidates (event_once) only use TTL, not levelEvents.
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
    trigger_event = params.get("trigger_event", "")

    # ── Emotion-triggered behaviors ───────────────────────────────────
    if need_type == "emotional":
        emotion_name = params.get("source_emotion") or EMOTION_BEHAVIOR_MAP.get(behavior_name)
        if emotion_name is None:
            return True  # Can't determine emotion → allow

        if trigger_event:
            # Primary path: string comparison of level events (ROS2 mode)
            current_event = blackboard.emotion_module.level_events.get(emotion_name)
            if current_event and current_event == trigger_event:
                _log.event(LogEvent.RELEVANCE_PASS,
                           behavior_name=behavior_name,
                           emotion=emotion_name,
                           current_event=current_event,
                           trigger_event=trigger_event)
                return True
            else:
                _log.event(LogEvent.RELEVANCE_FAIL,
                           behavior_name=behavior_name,
                           emotion=emotion_name,
                           current_event=str(current_event),
                           trigger_event=trigger_event)
                return False

        # Fallback: value-based overflow check (mock/test mode)
        if not blackboard.emotion_module.is_overflowing(emotion_name):
            em_state = blackboard.emotion_module.get_emotion(emotion_name)
            current_val = em_state.current_value if em_state else 0.0
            _log.event(LogEvent.RELEVANCE_FAIL,
                       behavior_name=behavior_name,
                       emotion=emotion_name,
                       current=round(current_val, 1))
            return False
        return True

    # ── Need-triggered behaviors ──────────────────────────────────────
    if need_type in ("physiological", "physiological_urgent", "psychological"):
        need_name = params.get("source_need") or NEED_BEHAVIOR_MAP.get(behavior_name)
        if need_name is None:
            return True  # Can't determine need → allow

        if trigger_event:
            # Primary path: string comparison of level events (ROS2 mode)
            current_event = blackboard.need_module.level_events.get(need_name)
            if current_event and current_event == trigger_event:
                _log.event(LogEvent.RELEVANCE_PASS,
                           behavior_name=behavior_name,
                           need=need_name,
                           current_event=current_event,
                           trigger_event=trigger_event)
                return True
            else:
                _log.event(LogEvent.RELEVANCE_FAIL,
                           behavior_name=behavior_name,
                           need=need_name,
                           current_event=str(current_event),
                           trigger_event=trigger_event)
                return False

        # Fallback: value-based trigger check (mock/test mode)
        if not blackboard.need_module.is_triggered(need_name):
            _log.event(LogEvent.RELEVANCE_FAIL,
                       behavior_name=behavior_name,
                       need=need_name,
                       level=blackboard.need_module.get_level(need_name))
            return False
        return True

    # ── Voice command, external, system, idle → always relevant ───────
    return True
