"""性格预设与性格系数接口。"""

from __future__ import annotations

import time
from typing import Any

from .types import (
    EmotionType,
    NormalizeEmotionType,
    NormalizePersonalityParam,
    NormalizePersonalityProfileType,
    PersonalityParam,
    PersonalityProfileType,
)


class PersonalityAPI:
    """性格参数、预设和情绪性格系数 API。"""

    def SetPersonalityProfileValue(self, profileName: object) -> bool:
        """应用指定性格预设。"""
        try:
            profile = NormalizePersonalityProfileType(profileName)
        except (TypeError, ValueError):
            return False
        if profile == PersonalityProfileType.CUSTOM.value:
            self.state.personalityProfile = profile
            return True

        profileConfig = self.configs.get("personalityProfiles", {}).get(profile)
        if not profileConfig:
            return False
        for paramName, value in profileConfig.get("params", {}).items():
            self.state.personality[paramName] = max(0, min(100, int(value)))
        self.state.personalityProfile = profile
        return True

    def SetPersonalityParamValue(self, paramName: object, value: object) -> bool:
        """设置单个性格参数，并切换为自定义性格。"""
        try:
            param = NormalizePersonalityParam(paramName)
            normalizedValue = self._NormalizePersonalityParamValue(value)
        except (TypeError, ValueError):
            return False
        self.state.personality[param] = normalizedValue
        self.state.personalityProfile = PersonalityProfileType.CUSTOM.value
        return True

    def SetPersonalityParamsValue(self, params: object) -> bool:
        """设置完整 A/O/E/C 参数，并切换为自定义性格。"""
        normalizedParams = self._NormalizePersonalityParams(params)
        if normalizedParams is None:
            return False
        self.state.personality.update(normalizedParams)
        self.state.personalityProfile = PersonalityProfileType.CUSTOM.value
        return True

    def SetPersonalityStateValue(self, stateData: object) -> bool:
        """从状态字典同步性格参数和预设名。"""
        if not isinstance(stateData, dict):
            return False
        normalizedParams = self._NormalizePersonalityParams(stateData.get("params"))
        if normalizedParams is None:
            return False
        try:
            profile = NormalizePersonalityProfileType(stateData.get("profile", PersonalityProfileType.CUSTOM.value))
        except (TypeError, ValueError):
            return False
        if profile != PersonalityProfileType.CUSTOM.value and not self.configs.get("personalityProfiles", {}).get(profile):
            return False
        self.state.personality.update(normalizedParams)
        self.state.personalityProfile = profile
        return True

    def GetPersonalityProfileValue(self) -> str:
        """获取当前性格预设名称。"""
        return self.state.personalityProfile

    def GetAllPersonalityParams(self) -> dict[str, int]:
        """获取全部 A/O/E/C 性格参数。"""
        return dict(self.state.personality)

    def GetPersonalityStateValue(self, timestamp: float | None = None) -> dict[str, Any]:
        """获取可发布到 `/personality/state` 的完整性格状态。"""
        return {
            "schema_version": "1.0",
            "timestamp": self._GetPersonalityTimestamp(timestamp),
            "profile": self.GetPersonalityProfileValue(),
            "params": self.GetAllPersonalityParams(),
            "coefficients": self._BuildPersonalityCoefficients(),
        }

    def GetSocialPersonalityCoefficientValue(self) -> float:
        """获取 Social 晨起初始化使用的性格系数。"""
        return self.GetEmotionPersonalityCoefficientValue(EmotionType.JOY)

    def GetEmotionPersonalityCoefficientValue(self, emotionType: object) -> float:
        """按 A/O/E/C 计算指定情绪的性格系数。"""
        emotion = NormalizeEmotionType(emotionType)
        affinity = self.state.personality[PersonalityParam.AFFINITY.value]
        obedience = self.state.personality[PersonalityParam.OBEDIENCE.value]
        activity = self.state.personality[PersonalityParam.EXTRAVERSION.value]
        courage = self.state.personality[PersonalityParam.COURAGE.value]

        if emotion == EmotionType.JOY.value:
            return (affinity / 50.0) * 0.8 + (activity / 50.0) * 0.2
        if emotion == EmotionType.EXCITE.value:
            return (affinity / 50.0) * 0.3 + (activity / 50.0) * 0.7
        if emotion == EmotionType.ANXIETY.value:
            return (1.5 - courage / 100.0) * (affinity / 50.0)
        if emotion == EmotionType.FEAR.value:
            return 2.0 - courage / 50.0
        if emotion == EmotionType.CURIOUS.value:
            return (activity / 50.0) * (1.0 + 0.3 * (1.0 - courage / 100.0))
        if emotion == EmotionType.CALM.value:
            return (obedience + affinity) / 100.0
        return 1.0

    def _BuildPersonalityCoefficients(self) -> dict[str, float]:
        """构造全部情绪和社交性格系数。"""
        coefficients = {
            emotion.value: round(self.GetEmotionPersonalityCoefficientValue(emotion), 4)
            for emotion in EmotionType
        }
        coefficients["Social"] = round(self.GetSocialPersonalityCoefficientValue(), 4)
        return coefficients

    def _NormalizePersonalityParams(self, params: object) -> dict[str, int] | None:
        """校验并规整完整 A/O/E/C 参数。"""
        if not isinstance(params, dict):
            return None
        normalized: dict[str, int] = {}
        for param in PersonalityParam:
            if param.value not in params:
                return None
            try:
                normalized[param.value] = self._NormalizePersonalityParamValue(params[param.value])
            except (TypeError, ValueError):
                return None
        return normalized

    def _NormalizePersonalityParamValue(self, value: object) -> int:
        """校验单个性格参数值。"""
        if isinstance(value, bool):
            raise ValueError("Personality param must be an integer, not bool")
        normalizedValue = int(value)
        if normalizedValue < 0 or normalizedValue > 100:
            raise ValueError("Personality param must be in 0-100")
        return normalizedValue

    def _GetPersonalityTimestamp(self, timestamp: float | None) -> float:
        """获取性格状态输出时间戳。"""
        if timestamp is not None:
            return float(timestamp)
        if hasattr(self, "_timeProvider"):
            return float(self._timeProvider())
        return time.time()
