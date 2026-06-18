"""行为树引擎接口实现。"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from .action_planner import ActionPlanner
from .arbiter import BehaviorArbiter
from .behavior_tree import BehaviorNodeStatus, BehaviorTreeRunner
from .bladder_behavior import BladderBehaviorAPI
from .cleanliness_behavior import CleanlinessBehaviorAPI
from .config_loader import LoadAllConfigs
from .debug_api import DebugAPI
from .demand_lifecycle import DemandLifecycleAPI
from .demand_api import DemandAPI
from .energy_behavior import EnergyBehaviorAPI
from .emotion_api import EmotionAPI
from .event_api import EventAPI
from .hunger_behavior import HungerBehaviorAPI
from .sensor_api import SensorInputAPI
from .sleepiness_behavior import SleepinessBehaviorAPI
from .state import ActionDecision, MarsdogState
from .types import (
    ActionFeedbackStatus,
    ActionResultType,
    ActionType,
    NormalizeActionFeedbackStatus,
    NormalizePriorityMode,
)


class MarsdogBehaviorSystem(
    DemandAPI,
    EmotionAPI,
    EventAPI,
    SensorInputAPI,
    DemandLifecycleAPI,
    BladderBehaviorAPI,
    CleanlinessBehaviorAPI,
    EnergyBehaviorAPI,
    HungerBehaviorAPI,
    SleepinessBehaviorAPI,
    DebugAPI,
):
    """Marsdog 行为系统核心入口。"""

    def __init__(
        self,
        configDir: str | Path | None = None,
        randomGenerator: random.Random | None = None,
    ) -> None:
        """初始化核心行为系统。"""
        self.state = MarsdogState()
        self.configs = LoadAllConfigs(configDir)
        self.random = randomGenerator or random.Random()
        self._emotionCallbacks = []
        self._eventHandlers: dict[str, list[Any]] = {}
        self.arbiter = BehaviorArbiter(self.state, self.configs)
        self.actionPlanner = ActionPlanner(self.state, self.configs, self.random)
        self.behaviorTreeRunner: BehaviorTreeRunner | None = None
        self._behaviorTreeAction = ""
        self._behaviorTreeResultApplied = False

    def Tick(self, currentTime: object | None = None, applyDemandGrowth: bool = True) -> None:
        """行为树引擎主循环，每帧调用一次。"""
        if applyDemandGrowth:
            self.UpdateNaturalDemandsByTime(currentTime)
        if hasattr(self, "UpdateSleepTriggerState"):
            self.UpdateSleepTriggerState(currentTime)
        decision = self.arbiter.DecideNextAction()
        self._ApplyDecision(decision)
        self.state.pendingEvents.clear()

    def GetCurrentAction(self) -> str:
        """获取当前正在执行的行为。"""
        return self.state.currentAction

    def GetActionQueue(self) -> list[str]:
        """获取行为队列。"""
        return list(self.state.actionQueue)

    def GetConcreteActionQueue(self) -> list[str]:
        """获取当前行为对应的具体动作队列。"""
        return self.actionPlanner.GetCurrentConcreteActions()

    def GetActionSequence(self, actionType: object) -> list[str]:
        """获取指定顶层行为对应的具体动作序列。"""
        return self.actionPlanner.GetConcreteActions(actionType)

    def GetCurrentActionSequence(self) -> list[str]:
        """获取当前行为对应的具体动作序列。"""
        return self.GetConcreteActionQueue()

    def GetCurrentActionCommand(self) -> dict[str, Any] | None:
        """获取当前需要下发给执行层的具体动作命令。"""
        self._EnsureCurrentConcreteActionReady()
        concreteAction = self.GetCurrentConcreteAction()
        if not concreteAction:
            self._ClearCurrentActionCommand()
            return None

        stepIndex = len(self.GetFinishedConcreteActions())
        if not self._IsCurrentActionCommandReusable(concreteAction, stepIndex):
            self._CreateCurrentActionCommand(concreteAction, stepIndex)
        return self.GetActiveActionCommand()

    def GetActiveActionCommand(self) -> dict[str, Any] | None:
        """获取已生成但尚未完成反馈的动作命令。"""
        if not self.state.currentActionCommandId:
            return None
        return {
            "commandId": self.state.currentActionCommandId,
            "topAction": self.state.currentActionCommandTopAction,
            "concreteAction": self.state.currentActionCommandConcreteAction,
            "stepIndex": self.state.currentActionCommandStepIndex,
            "behaviorTreeStatus": self.GetCurrentBehaviorTreeStatus(),
        }

    def OnActionFeedback(
        self,
        commandId: object,
        actionName: object,
        status: object,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """处理执行层对具体动作的完成反馈。"""
        try:
            feedbackStatus = NormalizeActionFeedbackStatus(status)
        except (TypeError, ValueError):
            return False

        command = self.GetCurrentActionCommand()
        if command is None or not self._IsFeedbackForCurrentCommand(command, commandId, actionName):
            return False

        self.state.lastActionFeedbackStatus = feedbackStatus
        self.state.lastActionFeedbackMetadata = dict(metadata or {})
        if feedbackStatus == ActionFeedbackStatus.SUCCESS.value:
            return self._ApplyActionFeedbackSuccess()
        if feedbackStatus == ActionFeedbackStatus.INTERRUPTED.value:
            return self._ApplyActionFeedbackInterrupted()
        return self._ApplyActionFeedbackFailure()

    def TickCurrentBehaviorTree(self) -> str:
        """执行当前顶层行为内部的行为树。"""
        if self.behaviorTreeRunner is None:
            self._StartBehaviorTree(self.state.currentAction)
        if self.behaviorTreeRunner is None:
            return BehaviorNodeStatus.FAILURE.value

        status = self.behaviorTreeRunner.Tick()
        if status == BehaviorNodeStatus.SUCCESS:
            self._ApplyBehaviorTreeSuccessResult()
        return status.value

    def GetCurrentConcreteAction(self) -> str:
        """获取当前行为树正在执行的具体动作。"""
        if self.behaviorTreeRunner is None:
            return ""
        return self.behaviorTreeRunner.GetCurrentConcreteAction()

    def MarkCurrentConcreteActionDone(self) -> bool:
        """标记当前行为树具体动作已完成。"""
        if self.behaviorTreeRunner is None:
            return False
        return self.behaviorTreeRunner.MarkCurrentActionDone()

    def GetFinishedConcreteActions(self) -> list[str]:
        """获取当前行为树已完成的具体动作。"""
        if self.behaviorTreeRunner is None:
            return []
        return self.behaviorTreeRunner.GetFinishedConcreteActions()

    def GetCurrentBehaviorTreeStatus(self) -> str:
        """获取当前行为树状态。"""
        if self.behaviorTreeRunner is None:
            return ""
        return self.behaviorTreeRunner.status.value

    def IsCurrentBehaviorTreeFinished(self) -> bool:
        """判断当前行为树是否结束。"""
        if self.behaviorTreeRunner is None:
            return True
        return self.behaviorTreeRunner.IsFinished()

    def ResetCurrentBehaviorTree(self) -> None:
        """重置当前行为树。"""
        if self.behaviorTreeRunner is not None:
            self.behaviorTreeRunner.Reset()
            self._behaviorTreeResultApplied = False

    def SetPriorityMode(self, mode: object) -> None:
        """设置优先级模式。"""
        self.state.priorityMode = NormalizePriorityMode(mode)

    def _ApplyDecision(self, decision: ActionDecision) -> None:
        """应用仲裁器输出并合并重复行为。"""
        action = decision.action
        shouldStartBehaviorTree = self.state.currentAction != action or self._ShouldRestartSameFinishedAction(action)
        if shouldStartBehaviorTree:
            if self._IsInterruptedByHigherPriority(decision.level):
                self.state.previousAction = self.state.currentAction
                self.state.previousDemandType = self.state.currentDemandType
                self.InterruptCurrentBehaviorTree()
                if self.state.currentDemandType is not None:
                    self.ExecuteDemandInterrupted(self.state.currentDemandType)
            self.state.currentAction = action
            self._StartBehaviorTree(action)

        self.state.currentPriorityLevel = decision.level
        self.state.currentDemandType = self._GetDecisionDemandType(decision)
        self.state.lastRuleName = decision.ruleName
        # 第一阶段每帧只输出唯一行为，同一行为请求自然合并为单项队列。
        self.state.actionQueue = [action]

    def _IsInterruptedByHigherPriority(self, newLevel: int) -> bool:
        """判断当前行为是否被更高优先级打断。"""
        return (
            self.state.currentAction != ActionType.ACTION_LOAF.value
            and newLevel < self.state.currentPriorityLevel
        )

    def _ShouldRestartSameFinishedAction(self, action: str) -> bool:
        """判断同一顶层行为是否已结束且需要重新启动。"""
        return (
            action != ActionType.ACTION_LOAF.value
            and self.state.currentAction == action
            and (self.behaviorTreeRunner is None or self.behaviorTreeRunner.IsFinished())
        )

    def _GetDecisionDemandType(self, decision: ActionDecision) -> str | None:
        """获取当前决策关联的内部需求类型。"""
        if decision.source == "demand":
            return decision.demand
        return None

    def _StartBehaviorTree(self, action: str) -> None:
        """启动指定顶层行为的内部行为树。"""
        self.behaviorTreeRunner = self.actionPlanner.BuildBehaviorTree(action)
        self._behaviorTreeAction = action
        self._behaviorTreeResultApplied = False
        self._ClearCurrentActionCommand()

    def InterruptCurrentBehaviorTree(self) -> None:
        """中断当前顶层行为内部行为树。"""
        if self.behaviorTreeRunner is not None:
            self.behaviorTreeRunner.Interrupt()
        self._ClearCurrentActionCommand()

    def _ApplyBehaviorTreeSuccessResult(self) -> None:
        """行为树成功结束后回写对应行为结果。"""
        if self._behaviorTreeResultApplied:
            return
        if self._behaviorTreeAction == ActionType.ACTION_EAT.value:
            self.ExecuteEat()
        elif self._behaviorTreeAction == ActionType.ACTION_DEFECATE.value:
            self.ExecuteDefecate()
        elif self._behaviorTreeAction == ActionType.ACTION_SLEEP.value:
            self.ExecuteSleep()
        elif self._behaviorTreeAction == ActionType.ACTION_GROOM.value:
            self.ExecuteGroom()
        elif self._behaviorTreeAction == ActionType.ACTION_RECHARGE.value:
            self.ExecuteRecharge()
        self._behaviorTreeResultApplied = True

    def _EnsureCurrentConcreteActionReady(self) -> None:
        """确保当前行为树已经推进到一个可下发的具体动作。"""
        if self.behaviorTreeRunner is None:
            self._StartBehaviorTree(self.state.currentAction)
        if self.GetCurrentConcreteAction() or self.IsCurrentBehaviorTreeFinished():
            return
        self.TickCurrentBehaviorTree()

    def _IsCurrentActionCommandReusable(self, concreteAction: str, stepIndex: int) -> bool:
        """判断当前命令是否仍对应同一个具体动作。"""
        return (
            self.state.currentActionCommandId != ""
            and self.state.currentActionCommandTopAction == self.state.currentAction
            and self.state.currentActionCommandConcreteAction == concreteAction
            and self.state.currentActionCommandStepIndex == stepIndex
        )

    def _CreateCurrentActionCommand(self, concreteAction: str, stepIndex: int) -> None:
        """创建新的具体动作命令。"""
        self.state.actionCommandCounter += 1
        self.state.currentActionCommandId = f"cmd-{self.state.actionCommandCounter:06d}"
        self.state.currentActionCommandTopAction = self.state.currentAction
        self.state.currentActionCommandConcreteAction = concreteAction
        self.state.currentActionCommandStepIndex = stepIndex

    def _ClearCurrentActionCommand(self) -> None:
        """清除当前待反馈的具体动作命令。"""
        self.state.currentActionCommandId = ""
        self.state.currentActionCommandTopAction = ""
        self.state.currentActionCommandConcreteAction = ""
        self.state.currentActionCommandStepIndex = -1

    def _IsFeedbackForCurrentCommand(
        self,
        command: dict[str, Any],
        commandId: object,
        actionName: object,
    ) -> bool:
        """判断反馈是否对应当前正在等待的动作命令。"""
        return command["commandId"] == str(commandId) and command["concreteAction"] == str(actionName)

    def _ApplyActionFeedbackSuccess(self) -> bool:
        """处理具体动作成功反馈并推进内部行为树。"""
        self._ClearCurrentActionCommand()
        if not self.MarkCurrentConcreteActionDone():
            return False
        self.TickCurrentBehaviorTree()
        return True

    def _ApplyActionFeedbackInterrupted(self) -> bool:
        """处理具体动作被外部中断的反馈。"""
        interruptedDemand = self.state.currentDemandType
        self.InterruptCurrentBehaviorTree()
        if interruptedDemand is not None:
            self.ExecuteDemandInterrupted(interruptedDemand)
        self._ResetCurrentActionAfterFeedbackStop()
        return True

    def _ApplyActionFeedbackFailure(self) -> bool:
        """处理具体动作执行失败反馈。"""
        failedDemand = self.state.currentDemandType
        self.InterruptCurrentBehaviorTree()
        if failedDemand is not None:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_UNSATISFIED)
        self._ResetCurrentActionAfterFeedbackStop()
        return True

    def _ResetCurrentActionAfterFeedbackStop(self) -> None:
        """反馈失败或中断后释放当前顶层行为，等待下一轮仲裁。"""
        self.state.previousAction = self.state.currentAction
        self.state.previousDemandType = self.state.currentDemandType
        self.state.currentAction = ActionType.ACTION_LOAF.value
        self.state.currentPriorityLevel = 6
        self.state.currentDemandType = None
        self.state.actionQueue = [ActionType.ACTION_LOAF.value]
