"""配置与调试接口实现。"""

from __future__ import annotations

from .state import SystemStatus
from .types import ClampValue, NormalizePersonalityParam, PersonalityProfileType


class DebugAPI:
    """配置与调试 API 混入类。"""

    def GetPersonalityParams(self) -> dict[str, int]:
        """获取当前性格参数。"""
        return dict(self.state.personality)

    def SetPersonalityParam(self, paramName: object, value: int) -> bool:
        """设置性格参数。"""
        try:
            param = NormalizePersonalityParam(paramName)
            self.state.personality[param] = ClampValue(value)
            self.state.personalityProfile = PersonalityProfileType.CUSTOM.value
            return True
        except (TypeError, ValueError):
            return False

    def ResetToDefault(self) -> None:
        """重置所有状态到默认值。"""
        self.state.ResetToDefault()

    def GetSystemStatus(self) -> SystemStatus:
        """获取系统整体状态摘要。"""
        return SystemStatus(
            demands=self.GetAllDemands(),
            emotions=self.GetAllEmotions(),
            personality=self.GetPersonalityParams(),
            currentAction=self.GetCurrentAction(),
            actionQueue=self.GetActionQueue(),
            currentActionCommand=self.GetActiveActionCommand(),
            currentConcreteAction=self.GetCurrentConcreteAction(),
            behaviorTreeStatus=self.GetCurrentBehaviorTreeStatus(),
            priorityMode=self.state.priorityMode,
            debugLogEnabled=self.state.debugLogEnabled,
            pendingEventCount=len(self.state.pendingEvents),
            lastRuleName=self.state.lastRuleName,
            demandLockActive=self.state.demandLockActive,
            isSleeping=self.state.isSleeping,
            sleepDepth=self.state.sleepDepth,
            sleepDurationMinutes=self.state.sleepDurationMinutes,
            shallowSleepTicksRemaining=self.state.shallowSleepTicksRemaining,
            sleepActionAllowed=self.state.sleepActionAllowed,
            lightsOff=self.state.lightsOff,
            lastActionFeedbackStatus=self.state.lastActionFeedbackStatus,
            personalityProfile=self.GetPersonalityProfileValue(),
            socialInteraction=self.GetSocialInteractionStatus(),
            explorationContext=self.GetExplorationContext(),
        )

    def EnableDebugLog(self, enable: bool) -> None:
        """开启或关闭调试日志。"""
        self.state.debugLogEnabled = bool(enable)
