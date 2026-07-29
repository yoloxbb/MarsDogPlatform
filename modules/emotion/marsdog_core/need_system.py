"""内部需求计算系统入口。"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable

from .behavior_result import (
    MarkBehaviorResultEventHandledValue,
    NormalizeBehaviorResultEventValue,
)
from .bladder_behavior import BladderBehaviorAPI
from .cleanliness_behavior import CleanlinessBehaviorAPI
from .config_loader import LoadAllConfigs
from .demand_api import DemandAPI
from .demand_lifecycle import DemandLifecycleAPI
from .energy_behavior import EnergyBehaviorAPI
from .exploration_behavior import ExplorationBehaviorAPI
from .hunger_behavior import HungerBehaviorAPI
from .personality_api import PersonalityAPI
from .rules import IsConditionMatched
from .sleepiness_behavior import SleepinessBehaviorAPI
from .social_behavior import SocialBehaviorAPI
from .state import MarsdogState
from .types import ActionType, ClampValue, DemandType


INTERRUPTED_RESULTS = {"INTERRUPTED", "CANCELLED", "TIMEOUT"}
SOCIAL_ACTIONS = {
    ActionType.ACTION_ATTENTION_SEEK.value,
    ActionType.ACTION_PLAY_INVITE.value,
    ActionType.ACTION_RESOURCE_SHARE.value,
    ActionType.ACTION_SOCIAL_GREET.value,
    ActionType.ACTION_BOUNDARY_TEST.value,
}
EXPLORATION_ACTIONS = {
    ActionType.ACTION_EXPLORE.value,
    ActionType.ACTION_SPACE_EXPLORE.value,
    ActionType.ACTION_OBJECT_EXPLORE.value,
}


class MarsdogNeedSystem(
    DemandAPI,
    DemandLifecycleAPI,
    BladderBehaviorAPI,
    CleanlinessBehaviorAPI,
    EnergyBehaviorAPI,
    HungerBehaviorAPI,
    SleepinessBehaviorAPI,
    SocialBehaviorAPI,
    ExplorationBehaviorAPI,
    PersonalityAPI,
):
    """只负责内部需求计算和需求结果结算的系统。"""

    def __init__(
        self,
        configDir: str | Path | None = None,
        randomGenerator: random.Random | None = None,
        timeProvider: Callable[[], float] | None = None,
    ) -> None:
        """初始化内部需求计算系统。"""
        self.state = MarsdogState()
        self.configs = LoadAllConfigs(configDir)
        self.random = randomGenerator or random.Random()
        self._timeProvider = timeProvider or time.time
        self.InitializeStartupEnergy()
        self._lastDemandSignalSnapshot = self.GetDemandSignalSnapshotValue()

    def OnVisualEvent(self, metadata: dict[str, Any] | None = None) -> list[str]:
        """处理新版 `/perception/visual_event` 中会影响需求值的事件。"""
        payload = dict(metadata or {})
        emittedEvents = self._GetStringList(payload.get("events", []))
        if "EVT_VISION_MASTER" in emittedEvents:
            self.OnOwnerPresenceChanged(True)
        return emittedEvents

    def OnAudioEvent(self, metadata: dict[str, Any] | None = None) -> list[str]:
        """处理新版 `/perception/audio_event` 并更新需求上下文。"""
        payload = dict(metadata or {})
        eventName = str(payload.get("event_type", ""))
        if not eventName:
            return []
        if eventName in {"EVT_VOICE_MASTER_ID", "EVT_VOICE_CALL_NAME"}:
            self.OnOwnerPresenceChanged(True)
        return [eventName]

    def OnBehaviorResultEvent(self, resultData: dict[str, Any] | None = None) -> bool:
        """根据行为组回传的结果事件结算需求值。"""
        payload = NormalizeBehaviorResultEventValue(resultData, self._GetActionDemandMap())
        if payload is None:
            return False
        if MarkBehaviorResultEventHandledValue(self.state, payload.get("event_id")):
            return False

        action = str(payload["action_type"])
        result = str(payload["result_type"])
        metadata = payload["metadata"]
        if result == "STARTED" and action == ActionType.ACTION_SLEEP.value:
            return self.ExecuteSleep()
        if result in INTERRUPTED_RESULTS:
            return self._ApplyInterruptedBehaviorResult(action, payload)
        if result != "COMPLETED":
            return False
        return self._ApplyCompletedBehaviorResult(action, metadata)

    def GetAllDemandSignals(self) -> list[dict[str, Any]]:
        """获取全部超过触发阈值的需求信号。"""
        signals: list[dict[str, Any]] = []
        for demand, value in self.state.demands.items():
            config = self.configs.get("demands", {}).get(demand, {})
            if self._IsDemandTriggered(demand, value):
                signals.append(self._BuildDemandSignal(demand, value, config))
        return signals

    def GetInternalNeedStateValue(self, timestamp: float | None = None) -> dict[str, Any]:
        """获取可发布到 `/internal_need/state` 的完整状态。"""
        return {
            "schema_version": "2.0",
            "timestamp": self._GetTimestamp(timestamp),
            "demands": {
                demand: self._BuildDemandState(demand, value)
                for demand, value in self.state.demands.items()
            },
            "levelEvents": self.GetDemandLevelEventsValue(),
            "triggered": self.GetAllDemandSignals(),
            "sleep": {
                "isSleeping": self.IsSleeping(),
                "sleepDepth": self.GetSleepDepthValue(),
                "sleepDurationMinutes": self.state.sleepDurationMinutes,
                "shallowSleepTicksRemaining": self.state.shallowSleepTicksRemaining,
            },
        }

    def _ApplyCompletedBehaviorResult(self, action: str, metadata: dict[str, Any]) -> bool:
        """按完成结果分发到具体需求结算逻辑。"""
        if action == ActionType.ACTION_EAT.value:
            return self._ApplyEatCompleted(metadata)
        if action == ActionType.ACTION_DEFECATE.value:
            return self.SetDemandValue(DemandType.BLADDER, 0)
        if action == ActionType.ACTION_GROOM.value:
            return self._ApplyGroomCompleted()
        if action == ActionType.ACTION_RECHARGE.value:
            return self._ApplyRechargeCompleted(metadata)
        if action in SOCIAL_ACTIONS:
            return self._ApplySocialCompleted(metadata)
        if action in EXPLORATION_ACTIONS:
            return self._ApplyExplorationCompleted(metadata)
        return False

    def _ApplyEatCompleted(self, metadata: dict[str, Any]) -> bool:
        """结算进食完成后的饥渴、排泄和清洁变化。"""
        oldHunger = self.GetDemandValue(DemandType.HUNGER)
        try:
            recovery = self.GetHungerRecoveryValue(
                metadata.get("foodType", metadata.get("food_type", "NormalFood")),
                metadata.get("portions", 1),
                metadata.get("eatEfficiency", metadata.get("eat_efficiency", "Full")),
            )
        except (TypeError, ValueError):
            return False
        self.SetDemandValue(DemandType.HUNGER, oldHunger - recovery)
        self.ApplyBladderAfterEat(oldHunger)
        self.ApplyCleanlinessAfterEat()
        return True

    def _ApplyGroomCompleted(self) -> bool:
        """结算清洁完成后的清洁值变化。"""
        config = self.configs.get("demands", {}).get(DemandType.CLEANLINESS.value, {})
        recovery = int(config.get("groomRecovery", 50))
        oldValue = self.GetDemandValue(DemandType.CLEANLINESS)
        return self.SetDemandValue(DemandType.CLEANLINESS, oldValue - recovery)

    def _ApplyRechargeCompleted(self, metadata: dict[str, Any]) -> bool:
        """把充电完成后的电量百分比转换为 Energy 需求值。"""
        value = metadata.get("energyValue", metadata.get("energy_value", metadata.get("batteryValue")))
        if value is None:
            value = self.configs.get("demands", {}).get(DemandType.ENERGY.value, {}).get("rechargeTarget", 100)
        try:
            energyValue = int(value)
        except (TypeError, ValueError):
            return False
        return self.SetEnergyBatteryValue(energyValue)

    def _ApplySocialCompleted(self, metadata: dict[str, Any]) -> bool:
        """根据社交结果结算 Social。"""
        outcome = str(metadata.get("socialOutcome", metadata.get("social_outcome", "")))
        recovery = self.GetSocialOutcomeRecoveryValue(outcome)
        if recovery is None:
            return outcome in {"Rejected", "TimedOut", ""}
        oldValue = self.GetDemandValue(DemandType.SOCIAL)
        return self.SetDemandValue(DemandType.SOCIAL, oldValue - recovery)

    def _ApplyExplorationCompleted(self, metadata: dict[str, Any]) -> bool:
        """按统一完成结果结算 Exploration。"""
        del metadata
        return self.ExecuteExploration("Completed")

    def _ApplyInterruptedBehaviorResult(self, action: str, payload: dict[str, Any]) -> bool:
        """结算中断、取消或超时导致的需求值变化。"""
        if action == ActionType.ACTION_SLEEP.value and self.IsSleeping():
            self.WakeUp()
        demand = str(payload.get("demand_type", payload.get("demandType", "")))
        if not demand:
            demand = self.GetDemandTypeByAction(action) or ""
        return self.ApplyInterruptedDemandDelta(demand) if demand else False

    def _BuildDemandState(self, demand: str, value: int) -> dict[str, Any]:
        """构造单个需求状态输出。"""
        config = self.configs.get("demands", {}).get(demand, {})
        levelInfo = self.GetDemandLevelValue(demand, value)
        return {
            "value": value,
            "triggerThreshold": config.get("triggerThreshold"),
            "triggerOperator": config.get("triggerOperator"),
            "urgentThreshold": config.get("urgentThreshold"),
            "urgentOperator": config.get("urgentOperator"),
            "overflowThreshold": config.get("overflowThreshold"),
            "triggered": self._IsDemandTriggered(demand, value),
            "urgent": self._IsDemandUrgentLevel(demand, value),
            "overflow": self._IsDemandOverflow(demand, value),
            "level": levelInfo["level"],
            "levelEvent": levelInfo["eventType"],
            "levelActive": levelInfo["active"],
        }

    def _BuildDemandSignal(self, demand: str, value: int, config: dict[str, Any]) -> dict[str, Any]:
        """构造单个已触发需求信号。"""
        return {
            "type": demand,
            "value": value,
            "triggerThreshold": config.get("triggerThreshold"),
            "triggerOperator": config.get("triggerOperator"),
            "urgentThreshold": config.get("urgentThreshold"),
            "urgentOperator": config.get("urgentOperator"),
            "urgent": self._IsDemandUrgentLevel(demand, value),
            "overflow": self._IsDemandOverflow(demand, value),
        }

    def _IsDemandTriggered(self, demand: str, value: int) -> bool:
        """判断需求是否超过触发阈值。"""
        config = self.configs.get("demands", {}).get(demand, {})
        threshold = config.get("triggerThreshold")
        operator = config.get("triggerOperator", "gt")
        return threshold is not None and IsConditionMatched(
            float(value), str(operator), float(threshold)
        )

    def _IsDemandUrgentLevel(self, demand: str, value: int) -> bool:
        """判断需求是否越过可选的 URGENT 中间等级阈值。"""
        config = self.configs.get("demands", {}).get(demand, {})
        threshold = config.get("urgentThreshold")
        operator = config.get("urgentOperator", config.get("triggerOperator", "gt"))
        return threshold is not None and IsConditionMatched(
            float(value), str(operator), float(threshold)
        )

    def _IsDemandOverflow(self, demand: str, value: int) -> bool:
        """判断需求是否超过满溢阈值。"""
        config = self.configs.get("demands", {}).get(demand, {})
        threshold = config.get("overflowThreshold")
        operator = config.get(
            "overflowOperator",
            config.get("urgentOperator", config.get("triggerOperator", "gt")),
        )
        return threshold is not None and IsConditionMatched(
            float(value), str(operator), float(threshold)
        )

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

    def ApplyActionResultEmotion(self, resultType: object) -> bool:
        """需求系统不直接拥有情绪状态，行为结果情绪由情绪节点处理。"""
        del resultType
        return False

    def _GetActionDemandMap(self) -> dict[str, str]:
        """获取 action 到内部需求的映射表。"""
        return dict(self.configs.get("demandGlobalRules", {}).get("actionDemandMap", {}))
