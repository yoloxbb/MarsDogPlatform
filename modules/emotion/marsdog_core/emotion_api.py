"""情绪接口实现。"""

from __future__ import annotations

import time
from typing import Any

from .rules import IsConditionMatched
from .types import ClampValue, EmotionType, NormalizeActionResultType, NormalizeEmotionType


class EmotionAPI:
    """情绪 API 混入类。"""

    def GetEmotionValue(self, emotionType: object) -> int:
        """获取指定情绪的当前值。"""
        emotion = NormalizeEmotionType(emotionType)
        return self.state.emotions[emotion]

    def SetEmotionValue(self, emotionType: object, value: int) -> bool:
        """设置指定情绪的当前值。"""
        try:
            emotion = NormalizeEmotionType(emotionType)
            self._SetEmotionValueInternal(emotion, value)
            return True
        except (TypeError, ValueError):
            return False

    def GetAllEmotions(self) -> dict[str, int]:
        """获取所有情绪的当前值。"""
        return dict(self.state.emotions)

    def GetDominantEmotion(self) -> str:
        """获取当前主导情绪类型。"""
        return max(self.state.emotions.items(), key=lambda item: item[1])[0]

    def ApplyEmotionDelta(self, emotionType: object, delta: int) -> bool:
        """对指定情绪施加增量变化。"""
        try:
            emotion = NormalizeEmotionType(emotionType)
            oldValue = self.state.emotions[emotion]
            self._SetEmotionValueInternal(emotion, oldValue + int(delta))
            return True
        except (TypeError, ValueError):
            return False

    def ApplyEmotionEvent(self, eventName: object, metadata: dict[str, Any] | None = None) -> bool:
        """根据外部 EVT_* 事件映射更新情绪值。"""
        event = str(eventName)
        mapping = self.GetEmotionEventMappingValue(event)
        if not mapping:
            return False

        eventMetadata = dict(metadata or {})
        multiplier = self._GetEmotionEventMultiplier(mapping, eventMetadata)
        appliedDeltas: dict[str, int] = {}
        for emotionName, baseDelta in mapping.get("deltas", {}).items():
            try:
                emotion = NormalizeEmotionType(emotionName)
            except (TypeError, ValueError):
                continue
            coefficient = self._GetEmotionPersonalityCoefficient(emotion)
            delta = int(round(float(baseDelta) * coefficient * multiplier))
            if delta == 0:
                continue
            self.ApplyEmotionDelta(emotion, delta)
            appliedDeltas[emotion] = delta

        self.state.lastEmotionEventResult = {
            "eventName": event,
            "appliedDeltas": appliedDeltas,
            "metadataMultiplier": multiplier,
            "metadata": eventMetadata,
        }
        return bool(appliedDeltas)

    def GetEmotionEventMappingValue(self, eventName: object) -> dict[str, Any]:
        """获取指定 EVT_* 事件的情绪映射配置。"""
        event = str(eventName)
        mapping = self.configs.get("emotions", {}).get("eventRules", {}).get(event, {})
        return dict(mapping) if isinstance(mapping, dict) else {}

    def GetLastEmotionEventResultValue(self) -> dict[str, Any]:
        """获取最近一次外部情绪事件的计算结果。"""
        return dict(getattr(self.state, "lastEmotionEventResult", {}))

    def ApplyEmotionDecay(self, elapsedSeconds: float = 1.0) -> dict[str, int]:
        """按自然平复公式衰减情绪值。"""
        elapsed = max(0.0, float(elapsedSeconds))
        if elapsed == 0:
            return self.GetAllEmotions()
        decayRules = self.configs.get("emotions", {}).get("decayRules", {})
        for emotionName, rate in decayRules.items():
            try:
                emotion = NormalizeEmotionType(emotionName)
            except (TypeError, ValueError):
                continue
            decayValue = float(rate) * elapsed
            if decayValue <= 0:
                continue
            oldValue = self.state.emotions[emotion]
            self._SetEmotionValueInternal(emotion, int(round(max(0.0, oldValue - decayValue))))
        return self.GetAllEmotions()

    def IsEmotionTriggered(
        self,
        emotionType: object,
        value: int | None = None,
    ) -> bool:
        """判断情绪是否触发；Calm 作为无其他触发情绪时的兜底状态。"""
        emotion = NormalizeEmotionType(emotionType)
        if emotion == EmotionType.CALM.value:
            # Calm 不依赖自身数值；任一其他情绪触发时立即退出平静状态。
            return self.IsCalmFallbackActive()
        emotionValue = ClampValue(
            self.state.emotions[emotion]
            if value is None
            else int(value)
        )
        return self._IsEmotionValueTriggered(emotion, emotionValue)

    def IsCalmFallbackActive(self) -> bool:
        """判断当前是否没有任何非 Calm 情绪越过各自阈值。"""
        for emotion, value in self.state.emotions.items():
            if emotion == EmotionType.CALM.value:
                continue
            if self._IsEmotionValueTriggered(emotion, value):
                return False
        return True

    def _IsEmotionValueTriggered(self, emotion: str, emotionValue: int) -> bool:
        """只根据指定情绪的数值和配置阈值执行基础判断。"""
        thresholdConfig = self._GetEmotionThresholdConfigValue(emotion)
        threshold = thresholdConfig.get("triggerThreshold")
        if threshold is None:
            return False
        operator = str(thresholdConfig.get("triggerOperator", "gte"))
        return IsConditionMatched(
            float(emotionValue),
            operator,
            float(threshold),
        )

    def GetEmotionSignalSnapshotValue(self) -> dict[str, bool]:
        """获取全部情绪的触发布尔快照。"""
        return {
            emotion: self.IsEmotionTriggered(emotion)
            for emotion in self.state.emotions
        }

    def GetEmotionSignalEventsValue(self, timestamp: float | None = None) -> list[dict[str, Any]]:
        """获取情绪事件；普通情绪发上升沿，平静状态每次检查都发事件。"""
        previousSnapshot = getattr(self, "_lastEmotionSignalSnapshot", None)
        currentSnapshot = self.GetEmotionSignalSnapshotValue()
        if previousSnapshot is None:
            self._lastEmotionSignalSnapshot = currentSnapshot
            previousSnapshot = {}

        events: list[dict[str, Any]] = []
        eventTimestamp = self._GetEmotionSignalTimestamp(timestamp)
        for emotion, isTriggered in currentSnapshot.items():
            if emotion == EmotionType.CALM.value:
                # Calm 每次检查都输出；ROS2 节点用真实时间 1 Hz 驱动该检查。
                if isTriggered:
                    events.append(
                        self._BuildEmotionSignalEvent(
                            emotion,
                            self.state.emotions[emotion],
                            eventTimestamp,
                        )
                    )
                continue
            # 只发布 false→true 上升沿；下降沿仅写回快照，供下次重新触发。
            if not isTriggered or bool(previousSnapshot.get(emotion, False)):
                continue
            events.append(
                self._BuildEmotionSignalEvent(
                    emotion,
                    self.state.emotions[emotion],
                    eventTimestamp,
                )
            )

        self._lastEmotionSignalSnapshot = currentSnapshot
        return events

    def GetAllEmotionSignals(self) -> list[dict[str, Any]]:
        """获取全部已经达到单一阈值的情绪信号。"""
        signals: list[dict[str, Any]] = []
        for emotion, value in self.state.emotions.items():
            if not self.IsEmotionTriggered(emotion):
                continue
            thresholdConfig = self._GetEmotionThresholdConfigValue(emotion)
            threshold = thresholdConfig.get("triggerThreshold")
            operator = thresholdConfig.get("triggerOperator", "gte")
            signals.append(
                {
                    "emotion": emotion,
                    "value": value,
                    "eventType": self._GetEmotionTriggerEventTypeValue(emotion),
                    "triggerThreshold": threshold,
                    "triggerOperator": operator,
                }
            )
        return signals

    def OnEmotionChanged(self, callback) -> None:
        """注册情绪变化回调事件。"""
        if callable(callback):
            self._emotionCallbacks.append(callback)

    def ApplyActionResultEmotion(self, resultType: object) -> bool:
        """根据行为执行结果更新情绪。"""
        try:
            result = NormalizeActionResultType(resultType)
        except ValueError:
            return False

        rules = self.configs.get("emotions", {}).get("actionResultRules", {}).get(result, [])
        for rule in rules:
            # 使用配置中的闭区间随机增减，最终仍由 ApplyEmotionDelta 限制范围。
            delta = self.random.randint(int(rule["min"]), int(rule["max"]))
            self.ApplyEmotionDelta(rule["emotion"], delta)
        return True

    def _SetEmotionValueInternal(self, emotion: str, value: int) -> None:
        """写入情绪值并触发变化回调。"""
        oldValue = self.state.emotions[emotion]
        newValue = ClampValue(value)
        self.state.emotions[emotion] = newValue
        if oldValue == newValue:
            return
        for callback in list(self._emotionCallbacks):
            callback(emotion, oldValue, newValue)

    def _GetEmotionPersonalityCoefficient(self, emotion: str) -> float:
        """读取情绪性格系数，未实现性格接口时默认 1.0。"""
        if hasattr(self, "GetEmotionPersonalityCoefficientValue"):
            return float(self.GetEmotionPersonalityCoefficientValue(emotion))
        return 1.0

    def _GetEmotionEventMultiplier(
        self,
        mapping: dict[str, Any],
        metadata: dict[str, Any],
    ) -> float:
        """根据事件元数据计算额外倍率。"""
        multiplier = 1.0
        for rule in mapping.get("metadataMultipliers", []):
            if self._IsEmotionMultiplierRuleMatched(rule, metadata):
                multiplier *= float(rule.get("multiplier", 1.0))
        return multiplier

    def _IsEmotionMultiplierRuleMatched(
        self,
        rule: dict[str, Any],
        metadata: dict[str, Any],
    ) -> bool:
        """判断事件倍率规则是否命中。"""
        key = str(rule.get("key", ""))
        operator = str(rule.get("operator", "truthy"))
        value = metadata.get(key)
        if operator == "truthy":
            return bool(value)
        if operator == "eq":
            return value == rule.get("value")
        if operator in {"gt", "gte", "lt", "lte"}:
            try:
                return IsConditionMatched(float(value), operator, float(rule.get("value", 0)))
            except (TypeError, ValueError):
                return False
        return False

    def _BuildEmotionSignalEvent(
        self,
        emotion: str,
        value: int,
        timestamp: float,
    ) -> dict[str, Any]:
        """构造发布给行为组的 V2 情绪信号事件。"""
        thresholdConfig = self._GetEmotionThresholdConfigValue(emotion)
        return {
            "schema_version": "2.0",
            "timestamp": timestamp,
            "event_type": self._GetEmotionTriggerEventTypeValue(emotion),
            "emotion": emotion,
            "value": value,
            "triggerThreshold": thresholdConfig.get("triggerThreshold"),
            "triggerOperator": thresholdConfig.get("triggerOperator", "gte"),
        }

    def _GetEmotionThresholdConfigValue(self, emotion: str) -> dict[str, Any]:
        """获取指定情绪的单一阈值配置。"""
        config = (
            self.configs.get("emotions", {})
            .get("thresholds", {})
            .get(emotion, {})
        )
        return dict(config) if isinstance(config, dict) else {}

    def _GetEmotionTriggerEventTypeValue(self, emotion: str) -> str:
        """生成指定情绪的统一触发事件名。"""
        return f"EMO_{emotion.upper()}_TRIGGERED"

    def _GetEmotionSignalTimestamp(self, timestamp: float | None) -> float:
        """获取情绪信号事件时间戳。"""
        if timestamp is not None:
            return float(timestamp)
        if hasattr(self, "_GetTimestamp"):
            return float(self._GetTimestamp(None))
        return time.time()
