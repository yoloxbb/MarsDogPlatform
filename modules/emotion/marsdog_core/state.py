"""系统状态数据结构。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .types import (
    DemandType,
    EmotionType,
    PersonalityParam,
    PersonalityProfileType,
    SleepDepthType,
    SocialInteractionState,
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
class EventData:
    """外部事件数据。"""

    eventTag: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class MarsdogState:
    """Marsdog 需求与情绪计算运行态。"""

    demands: dict[str, int] = field(default_factory=GetDefaultDemands)
    emotions: dict[str, int] = field(default_factory=GetDefaultEmotions)
    personality: dict[str, int] = field(default_factory=GetDefaultPersonalityParams)
    lastEmotionEventResult: dict[str, Any] = field(default_factory=dict)
    debugLogEnabled: bool = False
    pendingEvents: list[EventData] = field(default_factory=list)
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
    socialHumanVisible: bool = False
    socialAnimalVisible: bool = False
    socialPendingAction: str = ""
    socialPendingTargetType: str = ""
    socialPendingTargetVisible: bool = False
    socialInteractionCounter: int = 0
    socialInteractionId: str = ""
    socialInteractionInitiator: str = ""
    socialInteractionTargetType: str = ""
    socialInteractionTargetVisible: bool = False
    socialInteractionSelectedAction: str = ""
    socialInteractionState: str = SocialInteractionState.IDLE.value
    socialInteractionResponseDeadline: float = 0.0
    socialInteractionSettlementApplied: bool = False
    socialInteractionLastResult: str = ""
    ownerInteractionWindowUntil: float = 0.0
    ownerPresent: bool | None = None
    explorationPendingTargetType: str = ""
    explorationPendingTargetId: str = ""
    explorationPendingDiscoveryType: str = ""
    explorationCurrentTargetType: str = ""
    explorationCurrentTargetId: str = ""
    explorationCurrentDiscoveryType: str = ""
    explorationCurrentAction: str = ""
    explorationLastResult: str = ""
    explorationKnownTargetIds: set[str] = field(default_factory=set)

    def ResetToDefault(self) -> None:
        """重置所有运行态到默认值。"""
        self.demands = GetDefaultDemands()
        self.emotions = GetDefaultEmotions()
        self.personality = GetDefaultPersonalityParams()
        self.lastEmotionEventResult = {}
        self.debugLogEnabled = False
        self.pendingEvents = []
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
        self.socialHumanVisible = False
        self.socialAnimalVisible = False
        self.socialPendingAction = ""
        self.socialPendingTargetType = ""
        self.socialPendingTargetVisible = False
        self.socialInteractionCounter = 0
        self.socialInteractionId = ""
        self.socialInteractionInitiator = ""
        self.socialInteractionTargetType = ""
        self.socialInteractionTargetVisible = False
        self.socialInteractionSelectedAction = ""
        self.socialInteractionState = SocialInteractionState.IDLE.value
        self.socialInteractionResponseDeadline = 0.0
        self.socialInteractionSettlementApplied = False
        self.socialInteractionLastResult = ""
        self.ownerInteractionWindowUntil = 0.0
        self.ownerPresent = None
        self.explorationPendingTargetType = ""
        self.explorationPendingTargetId = ""
        self.explorationPendingDiscoveryType = ""
        self.explorationCurrentTargetType = ""
        self.explorationCurrentTargetId = ""
        self.explorationCurrentDiscoveryType = ""
        self.explorationCurrentAction = ""
        self.explorationLastResult = ""
        self.explorationKnownTargetIds = set()


EmotionCallback = Callable[[str, int, int], None]
EventCallback = Callable[[EventData], None]
