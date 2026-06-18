"""情绪接口实现。"""

from __future__ import annotations

from .types import (
    ClampValue,
    EmotionType,
    NormalizeActionResultType,
    NormalizeEmotionType,
)


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
