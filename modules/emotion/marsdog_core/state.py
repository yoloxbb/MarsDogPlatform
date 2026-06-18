"""系统状态数据结构。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .types import ActionType, DemandType, EmotionType, PersonalityParam, PriorityMode, SleepDepthType


def GetDefaultDemands() -> dict[str, int]:
    """获取默认需求状态。"""
    return {
        DemandType.HUNGER.value: 65,
        DemandType.BLADDER.value: 0,
        DemandType.SLEEPINESS.value: 15,
        DemandType.CLEANLINESS.value: 10,
        DemandType.ENERGY.value: 100,
        DemandType.SOCIAL.value: 60,
        DemandType.EXPLORATION.value: 0,
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
class ActionDecision:
    """仲裁器输出的行为决策。"""

    action: str
    level: int
    ruleName: str
    score: float = 0.0
    source: str = ""
    demand: str | None = None


@dataclass
class SystemStatus:
    """系统整体状态快照。"""

    demands: dict[str, int]
    emotions: dict[str, int]
    personality: dict[str, int]
    currentAction: str
    actionQueue: list[str]
    currentActionCommand: dict[str, Any] | None
    currentConcreteAction: str
    behaviorTreeStatus: str
    priorityMode: str
    debugLogEnabled: bool
    pendingEventCount: int
    lastRuleName: str
    demandLockActive: bool
    isSleeping: bool
    sleepDepth: str
    sleepDurationMinutes: int
    shallowSleepTicksRemaining: int
    sleepActionAllowed: bool
    lightsOff: bool
    lastActionFeedbackStatus: str


@dataclass
class MarsdogState:
    """Marsdog 行为系统运行态。"""

    demands: dict[str, int] = field(default_factory=GetDefaultDemands)
    emotions: dict[str, int] = field(default_factory=GetDefaultEmotions)
    personality: dict[str, int] = field(default_factory=GetDefaultPersonalityParams)
    currentAction: str = ActionType.ACTION_LOAF.value
    currentPriorityLevel: int = 6
    previousAction: str | None = None
    actionQueue: list[str] = field(default_factory=lambda: [ActionType.ACTION_LOAF.value])
    priorityMode: str = PriorityMode.NORMAL.value
    debugLogEnabled: bool = False
    pendingEvents: list[EventData] = field(default_factory=list)
    lastRuleName: str = "Idle"
    currentDemandType: str | None = None
    previousDemandType: str | None = None
    actionCommandCounter: int = 0
    currentActionCommandId: str = ""
    currentActionCommandTopAction: str = ""
    currentActionCommandConcreteAction: str = ""
    currentActionCommandStepIndex: int = -1
    lastActionFeedbackStatus: str = ""
    lastActionFeedbackMetadata: dict[str, Any] = field(default_factory=dict)
    demandLockActive: bool = False
    lastDemandLockState: bool | None = None
    lastMorningResetKey: str | None = None
    isSleeping: bool = False
    sleepDepth: str = SleepDepthType.SHALLOW.value
    sleepDurationMinutes: int = 0
    shallowSleepTicksRemaining: int = 0
    sleepActionAllowed: bool = False
    lightsOff: bool = False

    def ResetToDefault(self) -> None:
        """重置所有运行态到默认值。"""
        self.demands = GetDefaultDemands()
        self.emotions = GetDefaultEmotions()
        self.personality = GetDefaultPersonalityParams()
        self.currentAction = ActionType.ACTION_LOAF.value
        self.currentPriorityLevel = 6
        self.previousAction = None
        self.actionQueue = [ActionType.ACTION_LOAF.value]
        self.priorityMode = PriorityMode.NORMAL.value
        self.debugLogEnabled = False
        self.pendingEvents = []
        self.lastRuleName = "Idle"
        self.currentDemandType = None
        self.previousDemandType = None
        self.actionCommandCounter = 0
        self.currentActionCommandId = ""
        self.currentActionCommandTopAction = ""
        self.currentActionCommandConcreteAction = ""
        self.currentActionCommandStepIndex = -1
        self.lastActionFeedbackStatus = ""
        self.lastActionFeedbackMetadata = {}
        self.demandLockActive = False
        self.lastDemandLockState = None
        self.lastMorningResetKey = None
        self.isSleeping = False
        self.sleepDepth = SleepDepthType.SHALLOW.value
        self.sleepDurationMinutes = 0
        self.shallowSleepTicksRemaining = 0
        self.sleepActionAllowed = False
        self.lightsOff = False


EmotionCallback = Callable[[str, int, int], None]
EventCallback = Callable[[EventData], None]
