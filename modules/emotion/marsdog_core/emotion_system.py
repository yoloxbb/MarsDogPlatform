"""情绪计算系统入口。"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable

from .behavior_result import (
    MarkBehaviorResultEventHandledValue,
    NormalizeBehaviorResultEventValue,
)
from .config_loader import LoadAllConfigs
from .emotion_api import EmotionAPI
from .personality_api import PersonalityAPI
from .state import MarsdogState
from .types import ActionResultType


COMPLETED_RESULTS = {"COMPLETED"}
UNSATISFIED_RESULTS = {"FAILED", "TIMEOUT"}
INTERRUPTED_RESULTS = {"INTERRUPTED", "CANCELLED"}


class MarsdogEmotionSystem(EmotionAPI, PersonalityAPI):
    """只负责情绪计算、衰减和情绪信号输出的系统。"""

    def __init__(
        self,
        configDir: str | Path | None = None,
        randomGenerator: random.Random | None = None,
        timeProvider: Callable[[], float] | None = None,
    ) -> None:
        """初始化情绪计算系统。"""
        self.state = MarsdogState()
        self.configs = LoadAllConfigs(configDir)
        self.random = randomGenerator or random.Random()
        self._timeProvider = timeProvider or time.time
        self._emotionCallbacks = []
        self._lastEmotionSignalSnapshot = self.GetEmotionSignalSnapshotValue()

    def OnAudioEvent(self, metadata: dict[str, Any] | None = None) -> list[str]:
        """处理新版 `/perception/audio_event` 情绪事件。"""
        payload = dict(metadata or {})
        eventName = str(payload.get("event_type", ""))
        if not eventName:
            return []
        return [eventName] if self.ApplyEmotionEvent(eventName, payload) else []

    def OnVisualEvent(self, metadata: dict[str, Any] | None = None) -> list[str]:
        """处理新版 `/perception/visual_event.events[]` 情绪事件。"""
        payload = dict(metadata or {})
        appliedEvents: list[str] = []
        for eventName in self._GetStringList(payload.get("events", [])):
            if self.ApplyEmotionEvent(eventName, payload):
                appliedEvents.append(eventName)
        return appliedEvents

    def OnBehaviorResultEvent(self, resultData: dict[str, Any] | None = None) -> bool:
        """根据行为组回传结果更新情绪。"""
        payload = NormalizeBehaviorResultEventValue(resultData, self._GetActionDemandMap())
        if payload is None:
            return False
        if MarkBehaviorResultEventHandledValue(self.state, payload.get("event_id")):
            return False

        result = str(payload["result_type"])
        if result in COMPLETED_RESULTS:
            return self.ApplyActionResultEmotion(ActionResultType.DEMAND_SATISFIED)
        if result in UNSATISFIED_RESULTS:
            return self.ApplyActionResultEmotion(ActionResultType.DEMAND_UNSATISFIED)
        if result in INTERRUPTED_RESULTS:
            return self.ApplyActionResultEmotion(ActionResultType.ACTION_INTERRUPTED)
        return False

    def GetEmotionStateValue(self, timestamp: float | None = None) -> dict[str, Any]:
        """获取可发布到 `/emotion/state` 的完整状态。"""
        emotionSignals = self.GetAllEmotionSignals()
        return {
            "schema_version": "2.0",
            "timestamp": self._GetTimestamp(timestamp),
            "emotions": {
                emotion: self._BuildEmotionState(emotion, value)
                for emotion, value in self.state.emotions.items()
            },
            "triggered": emotionSignals,
            "dominantEmotion": self.GetDominantEmotion(),
            "personality": dict(self.state.personality),
            "lastEmotionEventResult": self.GetLastEmotionEventResultValue(),
        }

    def _BuildEmotionState(
        self,
        emotion: str,
        value: int,
    ) -> dict[str, Any]:
        """构造单个情绪状态输出。"""
        config = self.configs.get("emotions", {}).get("thresholds", {}).get(emotion, {})
        return {
            "value": value,
            "triggerThreshold": config.get("triggerThreshold"),
            "triggerOperator": config.get("triggerOperator"),
            "triggered": self.IsEmotionTriggered(emotion),
        }

    def _GetStringList(self, value: object) -> list[str]:
        """将输入规整为字符串列表。"""
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if isinstance(value, str) and value:
            return [value]
        return []

    def _GetTimestamp(self, timestamp: float | None) -> float:
        """获取状态输出时间戳。"""
        return float(self._timeProvider() if timestamp is None else timestamp)

    def _GetActionDemandMap(self) -> dict[str, str]:
        """获取 action 到内部需求的映射表，用于过滤无关行为结果。"""
        return dict(self.configs.get("demandGlobalRules", {}).get("actionDemandMap", {}))
