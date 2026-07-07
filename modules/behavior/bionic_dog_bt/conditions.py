"""Behavior tree condition nodes.

ActiveLevelCondition checks the blackboard for behaviors at a specific
priority level, enabling the priority-based selector to route correctly.

BehaviorRelevanceCondition validates that an emotion-triggered (or need-triggered)
behavior candidate is still relevant before execution. For example, if a
"happy overflow" triggers express_happy at Lv5 but higher-priority behaviors
run first, the happy emotion may decay below threshold — the behavior
should be skipped.
"""

from __future__ import annotations

from .behavior_tree_node import Node, Status
from .blackboard import Blackboard
from .constants import STATUS_RUNNING, EMOTION_BEHAVIOR_MAP, NEED_BEHAVIOR_MAP
from .logger import get_logger, LogEvent

_log = get_logger("conditions")


class ActiveLevelCondition(Node):
    """Condition: is there an active or running behavior at the given priority level?

    This condition returns SUCCESS when:
    1. Blackboard.active_behavior is set AND its priority_level == level
    2. OR Blackboard.current_behavior is RUNNING AND its priority_level == level

    This ensures the selector keeps ticking the currently running behavior
    even after active_behavior has been consumed by ExecuteActiveBehavior.
    """

    def __init__(self, name: str, blackboard: Blackboard, level: int):
        super().__init__(name)
        self.blackboard = blackboard
        self.level = level

    def update(self) -> Status:
        bb = self.blackboard

        # Case 1: New active behavior at this level
        if bb.active_behavior is not None:
            if bb.active_behavior.priority_level == self.level:
                return Status.SUCCESS

        # Case 2: Currently running behavior at this level
        if bb.current_behavior is not None and bb.current_status == STATUS_RUNNING:
            if bb.current_behavior.priority_level == self.level:
                return Status.SUCCESS

        return Status.FAILURE


class BehaviorRelevanceCondition(Node):
    """Condition: is the active_behavior's triggering signal still valid?

    Uses STRING COMPARISON of level events (not value-based overflow checks):

    - For emotion-triggered behaviors:
      Compare current /emotion/state.levelEvents[emotion] with the
      trigger_event stored at injection time (from /emotion/signal_event).
      If they match → emotion is still in the same zone → SUCCESS.
      If they differ → emotion has changed zone → FAILURE.

    - For need-triggered behaviors:
      Same pattern: compare /internal_need/state.levelEvents[need]
      with trigger_event from /internal_need/signal_event.

    - For all other types (system, external, idle): always SUCCESS.

    When there is no active_behavior (current behavior is still running),
    always return SUCCESS — relevance only gates new candidates.
    """

    def __init__(self, name: str, blackboard: Blackboard):
        super().__init__(name)
        self.blackboard = blackboard

    def update(self) -> Status:
        bb = self.blackboard
        active = bb.active_behavior

        # No new candidate — current behavior is still running, let it continue
        if active is None:
            return Status.SUCCESS

        # ── Emotion-triggered: compare levelEvents[emotion] vs trigger_event ─
        if active.need_type == "emotional":
            emotion_name = active.params.get("source_emotion")
            trigger_event = active.params.get("trigger_event", "")

            if emotion_name is None:
                emotion_name = EMOTION_BEHAVIOR_MAP.get(active.behavior_name)
            if emotion_name is None:
                return Status.SUCCESS

            # Primary path: string comparison of level events (ROS2 mode)
            if trigger_event:
                current_event = bb.emotion_module.level_events.get(emotion_name)
                if current_event and current_event == trigger_event:
                    _log.event(LogEvent.RELEVANCE_PASS,
                               behavior_name=active.behavior_name,
                               emotion=emotion_name,
                               current_event=current_event,
                               trigger_event=trigger_event)
                    return Status.SUCCESS
                else:
                    _log.event(LogEvent.RELEVANCE_FAIL,
                               behavior_name=active.behavior_name,
                               emotion=emotion_name,
                               current_event=str(current_event),
                               trigger_event=trigger_event)
                    return Status.FAILURE

            # Fallback: value-based overflow check (mock/test mode)
            if not bb.emotion_module.is_overflowing(emotion_name):
                em_state = bb.emotion_module.get_emotion(emotion_name)
                current_val = em_state.current_value if em_state else 0.0
                threshold = em_state.overflow_threshold if em_state else 0.0
                _log.event(LogEvent.RELEVANCE_FAIL,
                           behavior_name=active.behavior_name,
                           emotion=emotion_name,
                           current=round(current_val, 1),
                           threshold=round(threshold, 1))
                return Status.FAILURE

        # ── Need-triggered: compare levelEvents[need] vs trigger_event ───────
        if active.need_type in ("physiological", "physiological_urgent", "psychological"):
            need_name = active.params.get("source_need")
            trigger_event = active.params.get("trigger_event", "")

            if need_name is None:
                need_name = NEED_BEHAVIOR_MAP.get(active.behavior_name)

            if need_name is not None:
                # Primary path: string comparison of level events (ROS2 mode)
                if trigger_event:
                    current_event = bb.need_module.level_events.get(need_name)
                    if current_event and current_event == trigger_event:
                        _log.event(LogEvent.RELEVANCE_PASS,
                                   behavior_name=active.behavior_name,
                                   need=need_name,
                                   current_event=current_event,
                                   trigger_event=trigger_event)
                        return Status.SUCCESS
                    else:
                        _log.event(LogEvent.RELEVANCE_FAIL,
                                   behavior_name=active.behavior_name,
                                   need=need_name,
                                   current_event=str(current_event),
                                   trigger_event=trigger_event)
                        return Status.FAILURE

                # Fallback: value-based trigger check (mock/test mode)
                if not bb.need_module.is_triggered(need_name):
                    _log.event(LogEvent.RELEVANCE_FAIL,
                               behavior_name=active.behavior_name,
                               need=need_name,
                               level=bb.need_module.get_level(need_name))
                    return Status.FAILURE

        # ── All other trigger types pass through ─────────────────────────────
        return Status.SUCCESS
