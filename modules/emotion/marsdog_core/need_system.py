"""内部需求计算系统入口。"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable

from .bladder_behavior import BladderBehaviorAPI
from .cleanliness_behavior import CleanlinessBehaviorAPI
from .config_loader import LoadAllConfigs
from .demand_api import DemandAPI
from .demand_lifecycle import DemandLifecycleAPI
from .energy_behavior import EnergyBehaviorAPI
from .event_api import EventAPI
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
    EventAPI,
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
        self._eventHandlers: dict[str, list[Any]] = {}
        self._lastDemandSignalSnapshot = self.GetDemandSignalSnapshotValue()

    def OnVisualEvent(self, metadata: dict[str, Any] | None = None) -> list[str]:
        """处理新版 `/perception/visual_event` 并更新需求上下文。"""
        payload = dict(metadata or {})
        emittedEvents = self._GetStringList(payload.get("events", []))
        humanVisible = self._IsHumanVisible(payload, emittedEvents)
        animalVisible = self._IsAnimalVisible(payload, emittedEvents)
        self.SetSocialTargetVisibility(humanVisible, animalVisible)

        for target in payload.get("tracked_objects", []) or []:
            if isinstance(target, dict):
                self._RegisterExplorationTargetFromObject(target)
        for eventName in emittedEvents:
            self._ApplyVisualDemandEvent(eventName)
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
        payload = dict(resultData or {})
        action = str(payload.get("action_type", payload.get("actionType", "")))
        result = str(payload.get("result_type", payload.get("resultType", ""))).upper()
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        if not action or not result:
            return False
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
            threshold = config.get("urgentThreshold")
            operator = config.get("urgentOperator", "gt")
            if threshold is None:
                continue
            if IsConditionMatched(float(value), str(operator), float(threshold)):
                signals.append(self._BuildDemandSignal(demand, value, config))
        return signals

    def GetInternalNeedStateValue(self, timestamp: float | None = None) -> dict[str, Any]:
        """获取可发布到 `/internal_need/state` 的完整状态。"""
        return {
            "schema_version": "1.0",
            "timestamp": self._GetTimestamp(timestamp),
            "demands": {
                demand: self._BuildDemandState(demand, value)
                for demand, value in self.state.demands.items()
            },
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
        recovery = self.GetHungerRecoveryValue(
            metadata.get("foodType", metadata.get("food_type", "NormalFood")),
            metadata.get("portions", 1),
            metadata.get("eatEfficiency", metadata.get("eat_efficiency", "Full")),
        )
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
        """结算充电完成后的精力值变化。"""
        value = metadata.get("energyValue", metadata.get("energy_value", metadata.get("batteryValue")))
        if value is None:
            value = self.configs.get("demands", {}).get(DemandType.ENERGY.value, {}).get("rechargeTarget", 100)
        return self.SetDemandValue(DemandType.ENERGY, int(value))

    def _ApplySocialCompleted(self, metadata: dict[str, Any]) -> bool:
        """根据社交结果结算 Social。"""
        outcome = str(metadata.get("socialOutcome", metadata.get("social_outcome", "")))
        config = self.configs.get("demands", {}).get(DemandType.SOCIAL.value, {})
        recoveryMap = {
            "OwnerInteraction": int(config.get("ownerInteractionRecovery", 25)),
            "DogHumanResponded": int(config.get("dogHumanInteractionRecovery", 20)),
            "DogAnimalResponded": int(config.get("dogAnimalInteractionRecovery", 15)),
        }
        recovery = recoveryMap.get(outcome)
        if recovery is None:
            return outcome in {"Rejected", "TimedOut", ""}
        oldValue = self.GetDemandValue(DemandType.SOCIAL)
        return self.SetDemandValue(DemandType.SOCIAL, oldValue - recovery)

    def _ApplyExplorationCompleted(self, metadata: dict[str, Any]) -> bool:
        """根据探索结果结算 Exploration。"""
        discovery = str(metadata.get("discoveryType", metadata.get("discovery_type", "Completed")))
        config = self.configs.get("demands", {}).get(DemandType.EXPLORATION.value, {})
        recovery = int(config.get("recoveryRules", {}).get(discovery, 0))
        if recovery <= 0:
            return False
        oldValue = self.GetDemandValue(DemandType.EXPLORATION)
        return self.SetDemandValue(DemandType.EXPLORATION, oldValue - recovery)

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
            "triggerThreshold": config.get("urgentThreshold"),
            "triggerOperator": config.get("urgentOperator"),
            "overflowThreshold": config.get("overflowThreshold"),
            "triggered": self._IsDemandTriggered(demand, value),
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
            "triggerThreshold": config.get("urgentThreshold"),
            "triggerOperator": config.get("urgentOperator"),
            "overflow": self._IsDemandOverflow(demand, value),
        }

    def _IsDemandTriggered(self, demand: str, value: int) -> bool:
        """判断需求是否超过触发阈值。"""
        config = self.configs.get("demands", {}).get(demand, {})
        threshold = config.get("urgentThreshold")
        operator = config.get("urgentOperator", "gt")
        return threshold is not None and IsConditionMatched(float(value), str(operator), float(threshold))

    def _IsDemandOverflow(self, demand: str, value: int) -> bool:
        """判断需求是否超过满溢阈值。"""
        config = self.configs.get("demands", {}).get(demand, {})
        threshold = config.get("overflowThreshold")
        operator = config.get("overflowOperator", config.get("urgentOperator", "gt"))
        return threshold is not None and IsConditionMatched(float(value), str(operator), float(threshold))

    def _RegisterExplorationTargetFromObject(self, target: dict[str, Any]) -> None:
        """把视觉物体结果登记为探索候选目标。"""
        label = str(target.get("label", "GenericObject"))
        targetId = str(target.get("tracking_id", target.get("track_id", label)))
        confidence = float(target.get("confidence", 0.0) or 0.0)
        metadata = {"value": confidence * 100.0, "targetObject": dict(target)}
        self.OnExplorationTargetDetected(label, targetId, metadata=metadata)

    def _ApplyVisualDemandEvent(self, eventName: str) -> None:
        """根据视觉 EVT_* 事件更新需求上下文。"""
        if eventName in {"EVT_VISION_MASTER", "EVT_VISION_STRANGER"}:
            self.SetSocialTargetVisibility(True, self.state.socialAnimalVisible)
        elif eventName.startswith("EVT_VISION_ANIMAL_"):
            self.SetSocialTargetVisibility(self.state.socialHumanVisible, True)

    def _IsHumanVisible(self, payload: dict[str, Any], events: list[str]) -> bool:
        """判断视觉输入中是否存在人类目标。"""
        target = payload.get("active_target", {})
        return bool(
            payload.get("faces")
            or payload.get("humans")
            or (isinstance(target, dict) and target)
            or any(event in {"EVT_VISION_MASTER", "EVT_VISION_STRANGER"} for event in events)
        )

    def _IsAnimalVisible(self, payload: dict[str, Any], events: list[str]) -> bool:
        """判断视觉输入中是否存在动物目标。"""
        trackedObjects = payload.get("tracked_objects", []) or []
        labels = [str(item.get("label", "")).lower() for item in trackedObjects if isinstance(item, dict)]
        return any(label in {"dog", "cat", "animal"} for label in labels) or any(
            event.startswith("EVT_VISION_ANIMAL_") for event in events
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
