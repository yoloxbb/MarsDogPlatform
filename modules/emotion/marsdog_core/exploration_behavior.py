"""探索需求驱动、目标上下文和结果结算。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .rules import IsConditionMatched
from .types import (
    ActionType,
    ClampValue,
    DemandType,
    ExplorationDiscoveryType,
    ExplorationTargetType,
    NormalizeExplorationDiscoveryType,
    NormalizeExplorationTargetType,
)


EXPLORATION_ACTIONS = {
    ActionType.ACTION_EXPLORE.value,
    ActionType.ACTION_SPACE_EXPLORE.value,
    ActionType.ACTION_OBJECT_EXPLORE.value,
}


class ExplorationBehaviorAPI:
    """探索需求和探索目标 API 混入类。"""

    def InitializeMorningExploration(self) -> int:
        """按随机基础值和 k_curious 初始化晨起 Exploration。"""
        config = self._GetExplorationConfig()
        minValue, maxValue = config.get("morningRandomRange", [10, 20])
        baseValue = self.random.randint(int(minValue), int(maxValue))
        coefficient = self.GetEmotionPersonalityCoefficientValue("Curious")
        value = ClampValue(round(baseValue * coefficient))
        self.SetDemandValue(DemandType.EXPLORATION, value)
        return value

    def UpdateExplorationByTime(self, currentTime: object | None = None) -> int:
        """白天且 Energy 大于阈值时按每 10 分钟增长 Exploration。"""
        if hasattr(self, "IsDemandLocked") and self.IsDemandLocked(currentTime):
            return self.GetDemandValue(DemandType.EXPLORATION)

        delta = self._GetExplorationGrowthDelta(currentTime)
        if delta:
            oldValue = self.GetDemandValue(DemandType.EXPLORATION)
            self.SetDemandValue(DemandType.EXPLORATION, oldValue + delta)
        return self.GetDemandValue(DemandType.EXPLORATION)

    def GetExplorationContext(self) -> dict[str, Any]:
        """获取当前锁定或待执行的探索上下文。"""
        return {
            "currentAction": self.state.explorationCurrentAction,
            "targetType": self.state.explorationCurrentTargetType,
            "targetId": self.state.explorationCurrentTargetId,
            "discoveryType": self.state.explorationCurrentDiscoveryType,
            "lastResult": self.state.explorationLastResult,
            "pendingTargetType": self.state.explorationPendingTargetType,
            "pendingTargetId": self.state.explorationPendingTargetId,
            "pendingDiscoveryType": self.state.explorationPendingDiscoveryType,
        }

    def OnExplorationTargetDetected(
        self,
        targetType: object,
        targetId: object = "",
        discoveryType: object | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """登记感知到的探索目标并提交新/旧事物事件。"""
        try:
            target = NormalizeExplorationTargetType(targetType)
        except (TypeError, ValueError):
            target = ExplorationTargetType.GENERIC_OBJECT.value

        normalizedTargetId = str(targetId).strip() or target
        if self._IsSameExplorationTargetInProgress(normalizedTargetId):
            return False

        if discoveryType is None:
            discovery = (
                ExplorationDiscoveryType.OLD.value
                if normalizedTargetId in self.state.explorationKnownTargetIds
                else ExplorationDiscoveryType.NEW.value
            )
        else:
            try:
                discovery = NormalizeExplorationDiscoveryType(discoveryType)
            except (TypeError, ValueError):
                return False
            if discovery == ExplorationDiscoveryType.COMPLETED.value:
                return False

        self.state.explorationKnownTargetIds.add(normalizedTargetId)
        self.state.explorationPendingTargetType = target
        self.state.explorationPendingTargetId = normalizedTargetId
        self.state.explorationPendingDiscoveryType = discovery

        eventMetadata = dict(metadata or {})
        eventMetadata.update(
            {
                "targetType": target,
                "targetId": normalizedTargetId,
                "discoveryType": discovery,
            }
        )
        eventMetadata.setdefault("value", 100.0)
        eventTag = "NewObject" if discovery == ExplorationDiscoveryType.NEW.value else "OldObject"
        return self.PostEvent(eventTag, eventMetadata)

    def StartExplorationForDecision(self, action: str) -> bool:
        """根据顶层探索行为锁定本次目标和发现类型。"""
        if action not in EXPLORATION_ACTIONS:
            return False

        self.state.explorationCurrentAction = action
        if action == ActionType.ACTION_OBJECT_EXPLORE.value:
            self.state.explorationCurrentTargetType = (
                self.state.explorationPendingTargetType
                or ExplorationTargetType.GENERIC_OBJECT.value
            )
            self.state.explorationCurrentTargetId = self.state.explorationPendingTargetId
            self.state.explorationCurrentDiscoveryType = (
                self.state.explorationPendingDiscoveryType
                or ExplorationDiscoveryType.NEW.value
            )
        else:
            self.state.explorationCurrentTargetType = ExplorationTargetType.SPACE.value
            self.state.explorationCurrentTargetId = ExplorationTargetType.SPACE.value
            self.state.explorationCurrentDiscoveryType = ExplorationDiscoveryType.COMPLETED.value
        self._ClearPendingExplorationTarget()
        return True

    def ExecuteExploration(self, resultType: object | None = None) -> bool:
        """完成一次探索并按新、旧或普通完成结果降低 Exploration。"""
        if resultType is None:
            result = (
                self.state.explorationCurrentDiscoveryType
                or ExplorationDiscoveryType.COMPLETED.value
            )
        else:
            try:
                result = NormalizeExplorationDiscoveryType(resultType)
            except (TypeError, ValueError):
                return False

        recovery = int(self._GetExplorationConfig().get("recoveryRules", {}).get(result, 0))
        if recovery <= 0:
            return False
        oldValue = self.GetDemandValue(DemandType.EXPLORATION)
        self.SetDemandValue(DemandType.EXPLORATION, oldValue - recovery)
        self.state.explorationLastResult = result
        self._ClearCurrentExploration()
        return True

    def IsExplorationAction(self, action: str) -> bool:
        """判断顶层行为是否属于探索行为。"""
        return action in EXPLORATION_ACTIONS

    def OnExplorationActionStopped(self, result: str) -> None:
        """动作失败或被打断时清理当前探索上下文。"""
        if self.state.explorationCurrentAction:
            self.state.explorationLastResult = str(result)
            self._ClearCurrentExploration()

    def _GetExplorationGrowthDelta(self, currentTime: object | None) -> int:
        """按时段和 Energy 条件计算单次增长值。"""
        hour = self._GetExplorationHourValue(currentTime)
        energy = self.GetDemandValue(DemandType.ENERGY)
        for rule in self._GetExplorationConfig().get("growthRules", []):
            if not self._IsHourInRange(hour, int(rule["startHour"]), int(rule["endHour"])):
                continue
            if "energyThreshold" in rule and not IsConditionMatched(
                energy,
                str(rule.get("energyOperator", "gt")),
                float(rule["energyThreshold"]),
            ):
                return 0
            return int(rule.get("delta", 0))
        return 0

    def _IsSameExplorationTargetInProgress(self, targetId: str) -> bool:
        """避免持续感知重复覆盖同一个待执行或执行中目标。"""
        return targetId in {
            self.state.explorationPendingTargetId,
            self.state.explorationCurrentTargetId,
        }

    def _ClearPendingExplorationTarget(self) -> None:
        """清除尚未锁定的探索目标。"""
        self.state.explorationPendingTargetType = ""
        self.state.explorationPendingTargetId = ""
        self.state.explorationPendingDiscoveryType = ""

    def _ClearCurrentExploration(self) -> None:
        """清除本次已锁定的探索上下文。"""
        self.state.explorationCurrentTargetType = ""
        self.state.explorationCurrentTargetId = ""
        self.state.explorationCurrentDiscoveryType = ""
        self.state.explorationCurrentAction = ""

    def _GetExplorationHourValue(self, currentTime: object | None) -> int:
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

    def _GetExplorationConfig(self) -> dict[str, Any]:
        """获取 Exploration 配置。"""
        return self.configs.get("demands", {}).get(DemandType.EXPLORATION.value, {})

    def _IsHourInRange(self, hour: int, startHour: int, endHour: int) -> bool:
        """判断小时是否落入时间段。"""
        if startHour <= endHour:
            return startHour <= hour < endHour
        return hour >= startHour or hour < endHour
