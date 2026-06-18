"""行为仲裁器。"""

from __future__ import annotations

from typing import Any

from .rules import GetMetadataNumber, IsConditionMatched
from .state import ActionDecision, MarsdogState
from .types import ActionType, DemandType


class BehaviorArbiter:
    """按优先级规则输出唯一行为指令。"""

    def __init__(self, state: MarsdogState, configs: dict[str, Any]) -> None:
        """初始化仲裁器。"""
        self.state = state
        self.configs = configs

    def DecideNextAction(self) -> ActionDecision:
        """从 Lv.0 到 Lv.6 逐层仲裁下一个行为。"""
        rules = self.configs.get("priorities", {}).get("rules", [])
        for level in range(0, 7):
            matches = []
            for order, rule in enumerate(rules):
                if int(rule.get("level", 6)) != level:
                    continue
                decision = self._EvaluateRule(rule)
                if decision is not None:
                    matches.append((decision, order))
            if matches:
                matches.sort(key=lambda item: (item[0].score, -item[1]), reverse=True)
                return matches[0][0]

        return ActionDecision(ActionType.ACTION_LOAF.value, 6, "Idle", 0.0)

    def _EvaluateRule(self, rule: dict[str, Any]) -> ActionDecision | None:
        """根据规则来源分发到具体判断逻辑。"""
        source = rule.get("source")
        if source == "demand":
            return self._EvaluateDemandRule(rule)
        if source == "emotion":
            return self._EvaluateEmotionRule(rule)
        if source == "event":
            return self._EvaluateEventRule(rule)
        if source == "idle":
            return self._BuildDecision(rule, 0.0)
        return None

    def _EvaluateDemandRule(self, rule: dict[str, Any]) -> ActionDecision | None:
        """判断需求类规则是否触发。"""
        demand = rule.get("demand")
        if demand not in self.state.demands:
            return None
        if demand == DemandType.SLEEPINESS.value and not self.state.sleepActionAllowed:
            return None
        value = self.state.demands[demand]
        if not IsConditionMatched(value, rule["operator"], float(rule["threshold"])):
            return None
        score = float(rule.get("score", value))
        return self._BuildDecision(rule, score)

    def _EvaluateEmotionRule(self, rule: dict[str, Any]) -> ActionDecision | None:
        """判断情绪表达规则是否触发。"""
        emotion = rule.get("emotion")
        if emotion not in self.state.emotions:
            return None
        value = self.state.emotions[emotion]
        if not IsConditionMatched(value, rule["operator"], float(rule["threshold"])):
            return None
        score = float(rule.get("score", value * self._GetPersonalityFactor(rule)))
        return self._BuildDecision(rule, score)

    def _EvaluateEventRule(self, rule: dict[str, Any]) -> ActionDecision | None:
        """判断外部事件规则是否触发。"""
        matchedEvents = [
            event for event in self.state.pendingEvents if event.eventTag in set(rule.get("eventTags", []))
        ]
        if not matchedEvents:
            return None

        if "metadataThreshold" in rule:
            matchedEvents = [
                event for event in matchedEvents if self._IsMetadataThresholdMatched(event.metadata, rule)
            ]
            if not matchedEvents:
                return None

        if "demand" in rule:
            demand = rule["demand"]
            value = self.state.demands.get(demand)
            if value is None:
                return None
            if not IsConditionMatched(value, rule["operator"], float(rule["threshold"])):
                return None
            score = float(rule.get("score", value))
        else:
            score = float(rule.get("score", self._GetEventScore(matchedEvents)))
        return self._BuildDecision(rule, score)

    def _IsMetadataThresholdMatched(self, metadata: dict[str, Any], rule: dict[str, Any]) -> bool:
        """判断事件元数据阈值是否触发。"""
        metadataRule = rule["metadataThreshold"]
        value = GetMetadataNumber(metadata, metadataRule["key"])
        return IsConditionMatched(value, metadataRule["operator"], float(metadataRule["threshold"]))

    def _GetEventScore(self, events) -> float:
        """获取事件类规则的排序分数。"""
        scores = []
        for event in events:
            # 常用传感输入字段优先作为同层事件排序依据。
            scores.append(GetMetadataNumber(event.metadata, "value", 0.0))
            scores.append(GetMetadataNumber(event.metadata, "pressure", 0.0))
            scores.append(GetMetadataNumber(event.metadata, "confidence", 0.0))
        return max(scores) if scores else 0.0

    def _GetPersonalityFactor(self, rule: dict[str, Any]) -> float:
        """根据性格参数计算情绪表达系数。"""
        paramName = rule.get("personalityParam")
        if not paramName:
            return 1.0
        paramValue = self.state.personality.get(paramName, 50)
        base = float(rule.get("factorBase", 1.0))
        scale = float(rule.get("factorScale", 0.0))
        return base + (paramValue / 100.0) * scale

    def _BuildDecision(self, rule: dict[str, Any], score: float) -> ActionDecision:
        """生成行为决策对象。"""
        return ActionDecision(
            action=rule["action"],
            level=int(rule.get("level", 6)),
            ruleName=rule.get("name", rule["action"]),
            score=score,
            source=rule.get("source", ""),
            demand=rule.get("demand"),
        )
