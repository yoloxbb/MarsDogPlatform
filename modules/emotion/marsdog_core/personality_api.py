"""性格预设与性格系数接口。"""

from __future__ import annotations

from .types import (
    EmotionType,
    NormalizeEmotionType,
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

    def GetPersonalityProfileValue(self) -> str:
        """获取当前性格预设名称。"""
        return self.state.personalityProfile

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
        if emotion == EmotionType.CURIOUS.value:
            return (activity / 50.0) * (1.0 + 0.3 * (1.0 - courage / 100.0))
        if emotion == EmotionType.CALM.value:
            return (obedience + affinity) / 100.0
        return 1.0
