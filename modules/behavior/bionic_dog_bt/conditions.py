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
    """Condition: is the active_behavior's triggering condition still valid?

    Checks whether the source signal (emotion overflow, need threshold, etc.)
    is still above its threshold before allowing the behavior to execute.

    Rules by need_type:
    - "emotional": look up the source emotion via EMOTION_BEHAVIOR_MAP,
      check if that emotion is still overflowing (current >= threshold).
      If the emotion has decayed below threshold, return FAILURE.
    - All other types ("system", "survival", "external", "physiological",
      "physiological_urgent", "psychological", "idle"): always SUCCESS.

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

        # ── Emotion-triggered behaviors: check overflow ──────────────────────
        if active.need_type == "emotional":
            emotion_name = EMOTION_BEHAVIOR_MAP.get(active.behavior_name)
            if emotion_name is None:
                return Status.SUCCESS

            if not bb.emotion_module.is_overflowing(emotion_name):
                em_state = bb.emotion_module.get_emotion(emotion_name)
                current_val = em_state.current_value if em_state else 0.0
                threshold = em_state.overflow_threshold if em_state else 0.0
                self.log(
                    f"SKIP {active.behavior_name}: emotion '{emotion_name}' "
                    f"no longer overflowing ({current_val:.0f} < {threshold:.0f})"
                )
                return Status.FAILURE

            em_state = bb.emotion_module.get_emotion(emotion_name)
            current_val = em_state.current_value if em_state else 0.0
            threshold = em_state.overflow_threshold if em_state else 0.0
            self.log(
                f"RELEVANT {active.behavior_name}: emotion '{emotion_name}' "
                f"still overflowing ({current_val:.0f} >= {threshold:.0f})"
            )

        # ── Need-triggered behaviors: check trigger level ────────────────────
        elif active.need_type in ("physiological", "physiological_urgent", "psychological"):
            need_name = NEED_BEHAVIOR_MAP.get(active.behavior_name)
            if need_name is not None:
                if not bb.need_module.is_triggered(need_name):
                    need_state = bb.need_module.get_need(need_name)
                    current_val = need_state.current_value if need_state else 0.0
                    self.log(
                        f"SKIP {active.behavior_name}: need '{need_name}' "
                        f"no longer triggered (value={current_val:.0f}, level={bb.need_module.get_level(need_name)})"
                    )
                    return Status.FAILURE

                need_state = bb.need_module.get_need(need_name)
                current_val = need_state.current_value if need_state else 0.0
                self.log(
                    f"RELEVANT {active.behavior_name}: need '{need_name}' "
                    f"still triggered (value={current_val:.0f}, level={bb.need_module.get_level(need_name)})"
                )

        # ── All other trigger types pass through ─────────────────────────────
        return Status.SUCCESS
