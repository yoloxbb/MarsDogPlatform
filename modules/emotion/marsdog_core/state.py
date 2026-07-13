"""系统状态数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .types import (
    DemandType,
    EmotionType,
    PersonalityParam,
    PersonalityProfileType,
    SleepDepthType,
)


def GetDefaultDemands() -> dict[str, int]:
    """获取默认需求状态。"""
    return {
        DemandType.HUNGER.value: 65,
        DemandType.BLADDER.value: 0,
        DemandType.SLEEPINESS.value: 15,
        DemandType.CLEANLINESS.value: 10,
        DemandType.ENERGY.value: 100,
        DemandType.SOCIAL.value: 20,
        DemandType.EXPLORATION.value: 10,
    }


def GetDefaultEmotions() -> dict[str, int]:
    """获取默认情绪状态。"""
    return {
        EmotionType.JOY.value: 0,
        EmotionType.EXCITE.value: 0,
        EmotionType.ANXIETY.value: 0,
        EmotionType.FEAR.value: 0,
        EmotionType.CURIOUS.value: 0,
        EmotionType.CALM.value: 30,
    }


def GetDefaultPersonalityParams() -> dict[str, int]:
    """获取默认性格参数。"""
    return {
        PersonalityParam.AFFINITY.value: 50,
        PersonalityParam.OBEDIENCE.value: 50,
        PersonalityParam.EXTRAVERSION.value: 50,
        PersonalityParam.COURAGE.value: 50,
    }


@dataclass
class MarsdogState:
    """Marsdog 需求与情绪计算运行态。"""

    demands: dict[str, int] = field(default_factory=GetDefaultDemands)
    emotions: dict[str, int] = field(default_factory=GetDefaultEmotions)
    personality: dict[str, int] = field(default_factory=GetDefaultPersonalityParams)
    lastEmotionEventResult: dict[str, Any] = field(default_factory=dict)
    debugLogEnabled: bool = False
    demandLockActive: bool = False
    lastDemandLockState: bool | None = None
    lastMorningResetKey: str | None = None
    isSleeping: bool = False
    sleepDepth: str = SleepDepthType.SHALLOW.value
    sleepDurationMinutes: int = 0
    shallowSleepTicksRemaining: int = 0
    sleepActionAllowed: bool = False
    lightsOff: bool = False
    personalityProfile: str = PersonalityProfileType.CUSTOM.value
    ownerPresent: bool | None = None
    processedBehaviorResultEventIds: set[str] = field(default_factory=set)
    processedBehaviorResultEventIdOrder: list[str] = field(default_factory=list)

    def ResetToDefault(self) -> None:
        """重置所有运行态到默认值。"""
        self.demands = GetDefaultDemands()
        self.emotions = GetDefaultEmotions()
        self.personality = GetDefaultPersonalityParams()
        self.lastEmotionEventResult = {}
        self.debugLogEnabled = False
        self.demandLockActive = False
        self.lastDemandLockState = None
        self.lastMorningResetKey = None
        self.isSleeping = False
        self.sleepDepth = SleepDepthType.SHALLOW.value
        self.sleepDurationMinutes = 0
        self.shallowSleepTicksRemaining = 0
        self.sleepActionAllowed = False
        self.lightsOff = False
        self.personalityProfile = PersonalityProfileType.CUSTOM.value
        self.ownerPresent = None
        self.processedBehaviorResultEventIds = set()
        self.processedBehaviorResultEventIdOrder = []


EmotionCallback = Callable[[str, int, int], None]
