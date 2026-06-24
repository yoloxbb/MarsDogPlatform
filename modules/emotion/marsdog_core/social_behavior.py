"""社交需求驱动与互动会话状态机。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .rules import IsConditionMatched
from .types import (
    ActionType,
    ClampValue,
    DemandType,
    NormalizeSocialResponseType,
    NormalizeSocialTargetType,
    SocialInitiatorType,
    SocialInteractionState,
    SocialResponseType,
    SocialTargetType,
)


SOCIAL_ACTIONS = {
    ActionType.ACTION_ATTENTION_SEEK.value,
    ActionType.ACTION_PLAY_INVITE.value,
    ActionType.ACTION_RESOURCE_SHARE.value,
    ActionType.ACTION_SOCIAL_GREET.value,
    ActionType.ACTION_BOUNDARY_TEST.value,
}


class SocialBehaviorAPI:
    """社交需求和互动会话 API 混入类。"""

    def InitializeMorningSocial(self) -> int:
        """按随机基础值和性格系数初始化晨起 Social。"""
        value = self._CalculateMorningSocialValue()
        self.SetDemandValue(DemandType.SOCIAL, value)
        return value

    def UpdateSocialByTime(self, currentTime: object | None = None) -> int:
        """按每 10 分钟 Tick 的时间规则增长 Social。"""
        if hasattr(self, "IsDemandLocked") and self.IsDemandLocked(currentTime):
            return self.GetDemandValue(DemandType.SOCIAL)

        delta = self._GetSocialGrowthDelta(currentTime)
        if delta:
            oldValue = self.GetDemandValue(DemandType.SOCIAL)
            self.SetDemandValue(DemandType.SOCIAL, oldValue + delta)
        return self.GetDemandValue(DemandType.SOCIAL)

    def IsSocialInteractionActive(self) -> bool:
        """判断当前是否正在执行社交动作或等待回应。"""
        return self.state.socialInteractionState in {
            SocialInteractionState.EXECUTING_ACTION.value,
            SocialInteractionState.WAITING_RESPONSE.value,
        }

    def GetSocialInteractionStatus(self) -> dict[str, Any]:
        """获取当前社交互动会话状态。"""
        return {
            "interactionId": self.state.socialInteractionId,
            "initiator": self.state.socialInteractionInitiator,
            "targetType": self.state.socialInteractionTargetType,
            "targetVisible": self.state.socialInteractionTargetVisible,
            "selectedAction": self.state.socialInteractionSelectedAction,
            "state": self.state.socialInteractionState,
            "responseDeadline": self.state.socialInteractionResponseDeadline,
            "settlementApplied": self.state.socialInteractionSettlementApplied,
            "lastResult": self.state.socialInteractionLastResult,
        }

    def SetSocialTargetVisibility(self, humanVisible: bool, animalVisible: bool) -> None:
        """更新当前感知到的人类和动物目标可见性。"""
        self.state.socialHumanVisible = bool(humanVisible)
        self.state.socialAnimalVisible = bool(animalVisible)
        if not self.IsSocialInteractionActive() and not self._IsPendingSocialTargetCurrent():
            self._ClearPendingSocialAction()

    def PrepareSocialActionIntent(self) -> str:
        """为本轮社交需求仲裁准备目标和顶层行为。"""
        if self.IsSocialInteractionActive() or not self._IsSocialDemandTriggered():
            self._ClearPendingSocialAction()
            return ""
        if self.state.socialPendingAction and self._IsPendingSocialTargetCurrent():
            return self.state.socialPendingAction

        if self.state.socialHumanVisible:
            targetType = SocialTargetType.HUMAN.value
            action = self.random.choice(
                [
                    ActionType.ACTION_ATTENTION_SEEK.value,
                    ActionType.ACTION_PLAY_INVITE.value,
                    ActionType.ACTION_RESOURCE_SHARE.value,
                ]
            )
            targetVisible = True
        elif self.state.socialAnimalVisible:
            targetType = SocialTargetType.ANIMAL.value
            action = self.random.choice(
                [
                    ActionType.ACTION_SOCIAL_GREET.value,
                    ActionType.ACTION_PLAY_INVITE.value,
                    ActionType.ACTION_BOUNDARY_TEST.value,
                ]
            )
            targetVisible = True
        else:
            targetType = SocialTargetType.HUMAN.value
            action = ActionType.ACTION_ATTENTION_SEEK.value
            targetVisible = False

        self.state.socialPendingAction = action
        self.state.socialPendingTargetType = targetType
        self.state.socialPendingTargetVisible = targetVisible
        return action

    def StartSocialInteractionForDecision(self, action: str, source: str) -> bool:
        """根据仲裁结果创建并锁定本次社交互动会话。"""
        if action not in SOCIAL_ACTIONS:
            return False

        if self.IsSocialInteractionActive():
            self._FinishSocialInteraction(SocialInteractionState.INTERRUPTED.value, "Superseded")

        if source == "event":
            initiator = SocialInitiatorType.OWNER.value
            targetType = SocialTargetType.HUMAN.value
            targetVisible = self.state.socialHumanVisible
        else:
            initiator = SocialInitiatorType.DOG.value
            targetType = self.state.socialPendingTargetType or SocialTargetType.HUMAN.value
            targetVisible = self.state.socialPendingTargetVisible

        self.state.socialInteractionCounter += 1
        self.state.socialInteractionId = f"social-{self.state.socialInteractionCounter:06d}"
        self.state.socialInteractionInitiator = initiator
        self.state.socialInteractionTargetType = targetType
        self.state.socialInteractionTargetVisible = targetVisible
        self.state.socialInteractionSelectedAction = action
        self.state.socialInteractionState = SocialInteractionState.EXECUTING_ACTION.value
        self.state.socialInteractionResponseDeadline = 0.0
        self.state.socialInteractionSettlementApplied = False
        self.state.socialInteractionLastResult = ""
        self._ClearPendingSocialAction()
        return True

    def ExecuteSocialInteraction(self) -> bool:
        """在社交动作树完成后结算或进入等待回应状态。"""
        if self.state.socialInteractionState != SocialInteractionState.EXECUTING_ACTION.value:
            return False

        if self.state.socialInteractionInitiator == SocialInitiatorType.OWNER.value:
            recovery = int(self._GetSocialConfig().get("ownerInteractionRecovery", 25))
            self._ApplySocialRecovery(recovery)
            self.state.socialInteractionSettlementApplied = True
            self._FinishSocialInteraction(SocialInteractionState.COMPLETED.value, "OwnerInteractionCompleted")
            return True

        timeoutSeconds = float(self._GetSocialConfig().get("responseTimeoutSeconds", 30))
        self.state.socialInteractionState = SocialInteractionState.WAITING_RESPONSE.value
        self.state.socialInteractionResponseDeadline = self._GetCurrentTimestamp() + timeoutSeconds
        self.state.socialInteractionLastResult = "WaitingResponse"
        return True

    def OnSocialInteractionFeedback(
        self,
        interactionId: object,
        responseType: object,
        targetType: object,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """处理人类或动物对狗主动社交的回应。"""
        del metadata
        try:
            response = NormalizeSocialResponseType(responseType)
            target = NormalizeSocialTargetType(targetType)
        except (TypeError, ValueError):
            return False

        self.UpdateSocialInteractionState()
        if (
            self.state.socialInteractionState != SocialInteractionState.WAITING_RESPONSE.value
            or self.state.socialInteractionId != str(interactionId)
            or self.state.socialInteractionTargetType != target
            or self.state.socialInteractionSettlementApplied
        ):
            return False

        if response == SocialResponseType.RESPONDED.value:
            recoveryKey = (
                "dogHumanInteractionRecovery"
                if target == SocialTargetType.HUMAN.value
                else "dogAnimalInteractionRecovery"
            )
            recovery = int(self._GetSocialConfig().get(recoveryKey, 20 if target == "Human" else 15))
            self._ApplySocialRecovery(recovery)
            self.state.socialInteractionSettlementApplied = True
            self._FinishSocialInteraction(SocialInteractionState.COMPLETED.value, "Responded")
            return True

        self._FinishSocialInteraction(SocialInteractionState.COMPLETED.value, "Rejected")
        return True

    def UpdateSocialInteractionState(self, currentTimestamp: float | None = None) -> str:
        """刷新等待回应超时状态。"""
        if self.state.socialInteractionState != SocialInteractionState.WAITING_RESPONSE.value:
            return self.state.socialInteractionState
        now = self._GetCurrentTimestamp() if currentTimestamp is None else float(currentTimestamp)
        if now >= self.state.socialInteractionResponseDeadline:
            self._FinishSocialInteraction(SocialInteractionState.TIMED_OUT.value, "TimedOut")
        return self.state.socialInteractionState

    def OnSocialActionInterrupted(self) -> None:
        """将当前社交会话标记为被高优先级行为中断。"""
        if self.IsSocialInteractionActive():
            self._FinishSocialInteraction(SocialInteractionState.INTERRUPTED.value, "Interrupted")

    def OnSocialActionFailed(self) -> None:
        """将当前社交会话标记为动作执行失败。"""
        if self.IsSocialInteractionActive():
            self._FinishSocialInteraction(SocialInteractionState.FAILED.value, "ActionFailed")

    def OnOwnerInteractionEvent(
        self,
        metadata: dict[str, Any] | None = None,
        currentTimestamp: float | None = None,
    ) -> bool:
        """合并 10 秒内的主人 wakeup/speech/intent 交互事件。"""
        now = self._GetCurrentTimestamp() if currentTimestamp is None else float(currentTimestamp)
        if now < self.state.ownerInteractionWindowUntil:
            return False
        mergeWindow = float(self._GetSocialConfig().get("ownerInteractionMergeWindowSeconds", 10))
        self.state.ownerInteractionWindowUntil = now + mergeWindow
        eventMetadata = dict(metadata or {})
        try:
            eventValue = float(eventMetadata.get("value", 0.0))
        except (TypeError, ValueError):
            eventValue = 0.0
        eventMetadata["value"] = max(90.0, eventValue)
        return self.PostEvent("OwnerCall", eventMetadata)

    def OnOwnerPresenceChanged(self, isPresent: bool) -> None:
        """处理明确的主人在家或离家状态变化。"""
        present = bool(isPresent)
        if not present and self.state.ownerPresent is not False:
            delta = int(self._GetSocialConfig().get("ownerLeftHomeDelta", 30))
            oldValue = self.GetDemandValue(DemandType.SOCIAL)
            self.SetDemandValue(DemandType.SOCIAL, oldValue + delta)
        self.state.ownerPresent = present

    def IsSocialAction(self, action: str) -> bool:
        """判断顶层行为是否属于社交行为。"""
        return action in SOCIAL_ACTIONS

    def _CalculateMorningSocialValue(self) -> int:
        """计算经过性格修正的晨起 Social。"""
        minValue, maxValue = self._GetSocialConfig().get("morningRandomRange", [20, 30])
        baseValue = self.random.randint(int(minValue), int(maxValue))
        coefficient = self.GetSocialPersonalityCoefficientValue()
        return ClampValue(round(baseValue * coefficient))

    def _IsSocialDemandTriggered(self) -> bool:
        """判断 Social 是否达到主动社交阈值。"""
        config = self._GetSocialConfig()
        value = self.GetDemandValue(DemandType.SOCIAL)
        return IsConditionMatched(
            value,
            str(config.get("urgentOperator", "gt")),
            float(config.get("urgentThreshold", 60)),
        )

    def _ApplySocialRecovery(self, recovery: int) -> None:
        """对成功社交应用需求恢复值。"""
        oldValue = self.GetDemandValue(DemandType.SOCIAL)
        self.SetDemandValue(DemandType.SOCIAL, oldValue - max(0, int(recovery)))

    def _FinishSocialInteraction(self, state: str, result: str) -> None:
        """结束当前社交互动会话并保留结果快照。"""
        self.state.socialInteractionState = state
        self.state.socialInteractionResponseDeadline = 0.0
        self.state.socialInteractionLastResult = result

    def _ClearPendingSocialAction(self) -> None:
        """清除尚未进入仲裁执行的社交意图。"""
        self.state.socialPendingAction = ""
        self.state.socialPendingTargetType = ""
        self.state.socialPendingTargetVisible = False

    def _IsPendingSocialTargetCurrent(self) -> bool:
        """判断待执行社交意图是否仍符合当前目标可见性。"""
        target = self.state.socialPendingTargetType
        if target == SocialTargetType.HUMAN.value:
            if self.state.socialPendingTargetVisible:
                return self.state.socialHumanVisible
            return not self.state.socialHumanVisible and not self.state.socialAnimalVisible
        if target == SocialTargetType.ANIMAL.value:
            return (
                not self.state.socialHumanVisible
                and self.state.socialAnimalVisible
                and self.state.socialPendingTargetVisible
            )
        return False

    def _GetSocialGrowthDelta(self, currentTime: object | None) -> int:
        """根据当前时间计算单次 Social 增量。"""
        hour = self._GetSocialHourValue(currentTime)
        for rule in self._GetSocialConfig().get("growthRules", []):
            if self._IsHourInRange(hour, int(rule["startHour"]), int(rule["endHour"])):
                return int(rule.get("delta", 0))
        return 0

    def _GetSocialHourValue(self, currentTime: object | None) -> int:
        """从不同时间对象中读取小时值。"""
        if currentTime is None:
            return datetime.now().hour
        if isinstance(currentTime, datetime):
            return currentTime.hour
        if isinstance(currentTime, time):
            return currentTime.hour
        if isinstance(currentTime, int):
            return currentTime
        raise ValueError(f"Unsupported time value: {currentTime}")

    def _GetCurrentTimestamp(self) -> float:
        """读取可注入的系统时钟。"""
        return float(self._timeProvider())

    def _GetSocialConfig(self) -> dict[str, Any]:
        """获取 Social 配置。"""
        return self.configs.get("demands", {}).get(DemandType.SOCIAL.value, {})

    def _IsHourInRange(self, hour: int, startHour: int, endHour: int) -> bool:
        """判断小时是否落入时间段。"""
        if startHour <= endHour:
            return startHour <= hour < endHour
        return hour >= startHour or hour < endHour
