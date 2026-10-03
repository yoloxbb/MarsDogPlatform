"""Behavior tree condition nodes.

ActiveLevelCondition checks the blackboard for behaviors at a specific
priority level, enabling the priority-based selector to route correctly.

BehaviorRelevanceCondition validates that an emotion-triggered (or need-triggered)
behavior candidate is still relevant before execution.
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

    - For emotion-triggered behaviors:
      Read current /emotion/state.emotions[emotion].triggered. A false value
      means the V2 single-threshold signal has recovered, so the queued
      behavior is discarded.

    - For need-triggered behaviors:
      Read /internal_need/state.demands[need].triggered. URGENT and OVERFLOW
      remain relevant because they have also crossed the first trigger line.

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

        # ── Emotion-triggered: V2 authoritative triggered boolean ───────────
        if active.need_type == "emotional":
            emotion_name = active.params.get("source_emotion")

            if emotion_name is None:
                emotion_name = EMOTION_BEHAVIOR_MAP.get(active.behavior_name)
            if emotion_name is None:
                _log.event(LogEvent.RELEVANCE_FAIL,
                           behavior_name=active.behavior_name,
                           reason="missing_source_emotion")
                bb.active_behavior = None
                return Status.FAILURE

            if not bb.emotion_module.is_triggered(emotion_name):
                em_state = bb.emotion_module.get_emotion(emotion_name)
                current_val = em_state.current_value if em_state else 0.0
                _log.event(LogEvent.RELEVANCE_FAIL,
                           behavior_name=active.behavior_name,
                           emotion=emotion_name,
                           current=round(current_val, 1),
                           triggered=False)
                bb.active_behavior = None  # Clear stale candidate
                return Status.FAILURE
            _log.event(LogEvent.RELEVANCE_PASS,
                       behavior_name=active.behavior_name,
                       emotion=emotion_name,
                       triggered=True)
            return Status.SUCCESS

        # ── Need-triggered: V2 authoritative triggered boolean ──────────────
        if (
            active.params.get("source") == "need"
            or active.need_type in (
                "physiological",
                "physiological_urgent",
                "psychological",
            )
        ):
            need_name = active.params.get("source_need")
            if need_name is None:
                need_name = NEED_BEHAVIOR_MAP.get(active.behavior_name)

            if need_name is not None:
                if not bb.need_module.is_triggered(need_name):
                    _log.event(LogEvent.RELEVANCE_FAIL,
                               behavior_name=active.behavior_name,
                               need=need_name,
                               need_level=bb.need_module.get_level(need_name))
                    bb.active_behavior = None  # Clear stale candidate
                    return Status.FAILURE
                _log.event(LogEvent.RELEVANCE_PASS,
                           behavior_name=active.behavior_name,
                           need=need_name,
                           triggered=True)
                return Status.SUCCESS

        # ── All other trigger types pass through ─────────────────────────────
        return Status.SUCCESS
