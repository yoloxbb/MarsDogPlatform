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

    def GetEmotionLevelValue(self, emotionType: object, value: int | None = None) -> dict[str, Any]:
        """获取指定情绪当前所在的强度区间。"""
        emotion = NormalizeEmotionType(emotionType)
        emotionValue = ClampValue(self.state.emotions[emotion] if value is None else int(value))
        for levelConfig in self.configs.get("emotions", {}).get("levels", {}).get(emotion, []):
            minValue = int(levelConfig.get("min", 0))
            maxValue = int(levelConfig.get("max", 100))
            if minValue <= emotionValue <= maxValue:
                return {
                    "level": str(levelConfig.get("level", "")),
                    "eventType": str(levelConfig.get("eventType", "")),
                    "range": [minValue, maxValue],
                    "active": True,
                }
        return {
            "level": "NONE",
            "eventType": None,
            "range": None,
            "active": False,
        }

    def GetAllEmotionLevels(self) -> dict[str, dict[str, Any]]:
        """获取全部情绪当前所在的强度区间。"""
        return {
            emotion: self.GetEmotionLevelValue(emotion)
            for emotion in self.state.emotions
        }

    def GetDominantEmotionSignalValue(self) -> dict[str, Any]:
        """获取主导情绪及其当前强度区间。"""
        emotion = self.GetDominantEmotion()
        value = self.state.emotions[emotion]
        levelInfo = self.GetEmotionLevelValue(emotion)
        return {
            "emotion": emotion,
            "value": value,
            "level": levelInfo["level"],
            "eventType": levelInfo["eventType"],
            "range": levelInfo["range"],
            "active": levelInfo["active"],
        }

    def GetEmotionSignalSnapshotValue(self) -> dict[str, Any]:
        """获取当前情绪等级快照，用于判断区间变化。"""
        levels = self.GetAllEmotionLevels()
        dominant = self.GetDominantEmotionSignalValue()
        return {
            "levels": {
                emotion: levelInfo.get("eventType")
                for emotion, levelInfo in levels.items()
            },
            "dominant": {
                "emotion": dominant.get("emotion"),
                "eventType": dominant.get("eventType"),
            },
        }

    def GetEmotionSignalEventsValue(self, timestamp: float | None = None) -> list[dict[str, Any]]:
        """获取并刷新情绪区间变化事件。"""
        previousSnapshot = getattr(self, "_lastEmotionSignalSnapshot", None)
        currentSnapshot = self.GetEmotionSignalSnapshotValue()
        currentLevels = self.GetAllEmotionLevels()
        dominant = self.GetDominantEmotionSignalValue()
        if previousSnapshot is None:
            self._lastEmotionSignalSnapshot = currentSnapshot
            return []

        events: list[dict[str, Any]] = []
        eventsByEmotion: dict[str, dict[str, Any]] = {}
        eventTimestamp = self._GetEmotionSignalTimestamp(timestamp)
        previousLevels = previousSnapshot.get("levels", {})
        for emotion, levelInfo in currentLevels.items():
            currentEventType = levelInfo.get("eventType")
            if previousLevels.get(emotion) == currentEventType:
                continue
            if not currentEventType:
                continue
            event = self._BuildEmotionSignalEvent(
                emotion,
                self.state.emotions[emotion],
                levelInfo,
                eventTimestamp,
                "LEVEL_CHANGED",
                dominant.get("emotion") == emotion,
            )
            events.append(event)
            eventsByEmotion[emotion] = event

        previousDominant = previousSnapshot.get("dominant", {})
        dominantChanged = (
            previousDominant.get("emotion") != dominant.get("emotion")
            or previousDominant.get("eventType") != dominant.get("eventType")
        )
        if dominantChanged and dominant.get("eventType"):
            dominantEmotion = str(dominant["emotion"])
            existingEvent = eventsByEmotion.get(dominantEmotion)
            if existingEvent:
                existingEvent["trigger"] = "LEVEL_CHANGED_AND_DOMINANT_CHANGED"
                existingEvent["dominantChanged"] = True
            else:
                event = self._BuildEmotionSignalEvent(
                    dominantEmotion,
                    int(dominant["value"]),
                    dominant,
                    eventTimestamp,
                    "DOMINANT_CHANGED",
                    True,
                )
                event["dominantChanged"] = True
                events.append(event)

        self._lastEmotionSignalSnapshot = currentSnapshot
        return events

    def GetAllEmotionSignals(self) -> list[dict[str, Any]]:
        """获取全部处于已定义强度区间的情绪信号。"""
        signals: list[dict[str, Any]] = []
        thresholds = self.configs.get("emotions", {}).get("thresholds", {})
        for emotion, value in self.state.emotions.items():
            levelInfo = self.GetEmotionLevelValue(emotion)
            if not levelInfo["active"]:
                continue
            thresholdConfig = thresholds.get(emotion, {})
            threshold = thresholdConfig.get("triggerThreshold")
            operator = thresholdConfig.get("triggerOperator", "gte")
            signals.append(
                {
                    "type": emotion,
                    "value": value,
                    "level": levelInfo["level"],
                    "eventType": levelInfo["eventType"],
                    "range": levelInfo["range"],
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
        levelInfo: dict[str, Any],
        timestamp: float,
        trigger: str,
        isDominant: bool,
    ) -> dict[str, Any]:
        """构造发布给行为组的情绪区间变化事件。"""
        return {
            "schema_version": "1.0",
            "timestamp": timestamp,
            "event_type": levelInfo.get("eventType"),
            "emotion": emotion,
            "value": value,
            "level": levelInfo.get("level"),
            "range": levelInfo.get("range"),
            "trigger": trigger,
            "isDominant": isDominant,
            "dominantChanged": False,
        }

    def _GetEmotionSignalTimestamp(self, timestamp: float | None) -> float:
        """获取情绪信号事件时间戳。"""
        if timestamp is not None:
            return float(timestamp)
        if hasattr(self, "_GetTimestamp"):
            return float(self._GetTimestamp(None))
        return time.time()
