"""需求接口实现。"""

from __future__ import annotations

import time
from typing import Any

from .rules import IsConditionMatched
from .types import ClampValue, DemandType, NormalizeDemandType


class DemandAPI:
    """需求 API 混入类。"""

    def GetDemandValue(self, demandType: object) -> int:
        """获取指定需求的当前值。"""
        demand = NormalizeDemandType(demandType)
        return self.state.demands[demand]

    def SetDemandValue(self, demandType: object, value: int) -> bool:
        """设置指定需求的当前值。"""
        try:
            demand = NormalizeDemandType(demandType)
            self.state.demands[demand] = ClampValue(value)
            return True
        except (TypeError, ValueError):
            return False

    def GetAllDemands(self) -> dict[str, int]:
        """获取所有需求的当前值。"""
        return dict(self.state.demands)

    def IsDemandUrgent(self, demandType: object) -> bool:
        """判断指定需求是否达到紧急阈值。"""
        demand = NormalizeDemandType(demandType)
        demandConfig = self.configs.get("demands", {}).get(demand, {})
        threshold = demandConfig.get("urgentThreshold")
        operator = demandConfig.get("urgentOperator")
        if threshold is None or operator is None:
            return False
        return IsConditionMatched(self.state.demands[demand], operator, threshold)

    def GetMostUrgentDemand(self) -> str:
        """获取当前最紧急的需求名称。"""
        urgentDemands: list[tuple[int, str]] = []
        for demand in DemandType:
            if self.IsDemandUrgent(demand):
                # 同层需求不换算紧迫度，直接按原始值排序。
                urgentDemands.append((self.state.demands[demand.value], demand.value))
        if not urgentDemands:
            return ""
        urgentDemands.sort(reverse=True)
        return urgentDemands[0][1]

    def GetDemandLevelValue(self, demandType: object, value: int | None = None) -> dict[str, Any]:
        """获取指定需求当前所在等级。"""
        demand = NormalizeDemandType(demandType)
        demandValue = ClampValue(self.state.demands[demand] if value is None else int(value))
        config = self.configs.get("demands", {}).get(demand, {})
        triggerThreshold = config.get("urgentThreshold")
        triggerOperator = str(config.get("urgentOperator", "gt"))
        overflowThreshold = config.get("overflowThreshold")
        overflowOperator = str(config.get("overflowOperator", triggerOperator))

        level = "NORMAL"
        if (
            triggerThreshold is not None
            and IsConditionMatched(float(demandValue), triggerOperator, float(triggerThreshold))
        ):
            level = "TRIGGERED"
        if (
            overflowThreshold is not None
            and IsConditionMatched(float(demandValue), overflowOperator, float(overflowThreshold))
        ):
            level = "OVERFLOW"

        return {
            "level": level,
            "eventType": self._GetDemandLevelEventType(demand, level),
            "triggerThreshold": triggerThreshold,
            "triggerOperator": triggerOperator,
            "overflowThreshold": overflowThreshold,
            "overflowOperator": overflowOperator,
            "active": level != "NORMAL",
        }

    def GetAllDemandLevels(self) -> dict[str, dict[str, Any]]:
        """获取全部需求当前所在等级。"""
        return {
            demand: self.GetDemandLevelValue(demand)
            for demand in self.state.demands
        }

    def GetDemandSignalSnapshotValue(self) -> dict[str, Any]:
        """获取当前需求等级快照，用于判断等级变化。"""
        levels = self.GetAllDemandLevels()
        return {
            "levels": {
                demand: levelInfo.get("level")
                for demand, levelInfo in levels.items()
            }
        }

    def GetDemandSignalEventsValue(self, timestamp: float | None = None) -> list[dict[str, Any]]:
        """获取并刷新需求等级变化事件。"""
        previousSnapshot = getattr(self, "_lastDemandSignalSnapshot", None)
        currentSnapshot = self.GetDemandSignalSnapshotValue()
        if previousSnapshot is None:
            self._lastDemandSignalSnapshot = currentSnapshot
            return []

        events: list[dict[str, Any]] = []
        eventTimestamp = self._GetDemandSignalTimestamp(timestamp)
        previousLevels = previousSnapshot.get("levels", {})
        for demand, levelInfo in self.GetAllDemandLevels().items():
            currentLevel = str(levelInfo.get("level", "NORMAL"))
            previousLevel = str(previousLevels.get(demand, "NORMAL"))
            if currentLevel == previousLevel:
                continue
            events.append(
                self._BuildDemandSignalEvent(
                    demand,
                    self.state.demands[demand],
                    previousLevel,
                    levelInfo,
                    eventTimestamp,
                )
            )

        self._lastDemandSignalSnapshot = currentSnapshot
        return events

    def _BuildDemandSignalEvent(
        self,
        demand: str,
        value: int,
        previousLevel: str,
        levelInfo: dict[str, Any],
        timestamp: float,
    ) -> dict[str, Any]:
        """构造发布到 `/internal_need/signal_event` 的需求事件。"""
        return {
            "schema_version": "1.0",
            "timestamp": timestamp,
            "event_type": levelInfo.get("eventType"),
            "demand": demand,
            "value": value,
            "level": levelInfo.get("level"),
            "previousLevel": previousLevel,
            "triggerThreshold": levelInfo.get("triggerThreshold"),
            "triggerOperator": levelInfo.get("triggerOperator"),
            "overflowThreshold": levelInfo.get("overflowThreshold"),
            "overflowOperator": levelInfo.get("overflowOperator"),
            "trigger": "LEVEL_CHANGED",
        }

    def _GetDemandLevelEventType(self, demand: str, level: str) -> str:
        """根据需求和等级生成事件名。"""
        demandName = demand.upper()
        if level == "OVERFLOW":
            return f"NEED_{demandName}_OVERFLOW"
        if level == "TRIGGERED":
            return f"NEED_{demandName}_TRIGGERED"
        return f"NEED_{demandName}_RECOVERED"

    def _GetDemandSignalTimestamp(self, timestamp: float | None) -> float:
        """获取需求事件时间戳。"""
        if timestamp is not None:
            return float(timestamp)
        if hasattr(self, "_GetTimestamp"):
            return float(self._GetTimestamp(None))
        return time.time()
