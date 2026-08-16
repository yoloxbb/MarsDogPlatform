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
            if demand == DemandType.ENERGY.value:
                # 外部写入、充电或中断结算后重新开始耗电，避免继承旧的小数余量。
                self.state.energyDrainRemainder = 0.0
            return True
        except (TypeError, ValueError):
            return False

    def GetAllDemands(self) -> dict[str, int]:
        """获取所有需求的当前值。"""
        return dict(self.state.demands)

    def IsDemandUrgent(self, demandType: object) -> bool:
        """判断指定需求是否越过首次触发线，供紧迫度筛选使用。"""
        return self._IsDemandThresholdMatched(demandType)

    def _IsDemandThresholdMatched(
        self,
        demandType: object,
        value: int | None = None,
        defaultOperator: str | None = None,
    ) -> bool:
        """统一判断指定需求值是否越过首次触发阈值。"""
        demand = NormalizeDemandType(demandType)
        demandConfig = self.configs.get("demands", {}).get(demand, {})
        threshold = demandConfig.get("triggerThreshold")
        operator = demandConfig.get("triggerOperator", defaultOperator)
        if threshold is None or operator is None:
            return False
        demandValue = self.state.demands[demand] if value is None else int(value)
        return IsConditionMatched(demandValue, operator, threshold)

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
        triggerThreshold = config.get("triggerThreshold")
        triggerOperator = str(config.get("triggerOperator", "gt"))
        urgentThreshold = config.get("urgentThreshold")
        urgentOperator = (
            str(config.get("urgentOperator", triggerOperator))
            if urgentThreshold is not None
            else None
        )
        overflowThreshold = config.get("overflowThreshold")
        overflowOperator = (
            str(config.get("overflowOperator", urgentOperator or triggerOperator))
            if overflowThreshold is not None
            else None
        )

        level = "NORMAL"
        # 依次覆盖等级；未配置的中间等级会自然跳过。
        if (
            triggerThreshold is not None
            and IsConditionMatched(float(demandValue), triggerOperator, float(triggerThreshold))
        ):
            level = "TRIGGERED"
        if (
            urgentThreshold is not None
            and urgentOperator is not None
            and IsConditionMatched(float(demandValue), urgentOperator, float(urgentThreshold))
        ):
            level = "URGENT"
        if (
            overflowThreshold is not None
            and overflowOperator is not None
            and IsConditionMatched(float(demandValue), overflowOperator, float(overflowThreshold))
        ):
            level = "OVERFLOW"

        return {
            "level": level,
            "eventType": self._GetDemandLevelEventType(demand, level),
            "triggerThreshold": triggerThreshold,
            "triggerOperator": triggerOperator,
            "urgentThreshold": urgentThreshold,
            "urgentOperator": urgentOperator,
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

    def GetDemandLevelEventsValue(self) -> dict[str, str]:
        """获取全部需求当前等级对应的事件名。"""
        return {
            demand: levelInfo["eventType"]
            for demand, levelInfo in self.GetAllDemandLevels().items()
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
        """获取并刷新需求等级变化或行为完成后仍激活的重发事件。"""
        previousSnapshot = getattr(self, "_lastDemandSignalSnapshot", None)
        currentSnapshot = self.GetDemandSignalSnapshotValue()
        if previousSnapshot is None:
            self._lastDemandSignalSnapshot = currentSnapshot
            return []

        events: list[dict[str, Any]] = []
        eventTimestamp = self._GetDemandSignalTimestamp(timestamp)
        previousLevels = previousSnapshot.get("levels", {})
        pendingRetriggers = set(getattr(self, "_pendingDemandSignalRetriggers", set()))
        for demand, levelInfo in self.GetAllDemandLevels().items():
            currentLevel = str(levelInfo.get("level", "NORMAL"))
            previousLevel = str(previousLevels.get(demand, "NORMAL"))
            if currentLevel != previousLevel:
                events.append(
                    self._BuildDemandSignalEvent(
                        demand,
                        self.state.demands[demand],
                        previousLevel,
                        levelInfo,
                        eventTimestamp,
                    )
                )
                continue

            if demand not in pendingRetriggers or not bool(levelInfo.get("active")):
                continue
            # 行为已经完成但需求仍停留在原激活等级时，复用当前事件名再次通知行为侧。
            events.append(
                self._BuildDemandSignalEvent(
                    demand,
                    self.state.demands[demand],
                    previousLevel,
                    levelInfo,
                    eventTimestamp,
                    "ACTION_RESULT_STILL_ACTIVE",
                )
            )

        self._lastDemandSignalSnapshot = currentSnapshot
        self._pendingDemandSignalRetriggers = set()
        return events

    def _QueueDemandSignalRetrigger(self, demandType: object) -> bool:
        """登记一次行为完成后仍激活的需求信号重发检查。"""
        try:
            demand = NormalizeDemandType(demandType)
        except (TypeError, ValueError):
            return False
        pendingRetriggers = set(getattr(self, "_pendingDemandSignalRetriggers", set()))
        pendingRetriggers.add(demand)
        self._pendingDemandSignalRetriggers = pendingRetriggers
        return True

    def _BuildDemandSignalEvent(
        self,
        demand: str,
        value: int,
        previousLevel: str,
        levelInfo: dict[str, Any],
        timestamp: float,
        triggerReason: str = "LEVEL_CHANGED",
    ) -> dict[str, Any]:
        """构造发布到 `/internal_need/signal_event` 的需求事件。"""
        return {
            "schema_version": "2.0",
            "timestamp": timestamp,
            "event_type": levelInfo.get("eventType"),
            "demand": demand,
            "value": value,
            "level": levelInfo.get("level"),
            "previousLevel": previousLevel,
            "triggerThreshold": levelInfo.get("triggerThreshold"),
            "triggerOperator": levelInfo.get("triggerOperator"),
            "urgentThreshold": levelInfo.get("urgentThreshold"),
            "urgentOperator": levelInfo.get("urgentOperator"),
            "overflowThreshold": levelInfo.get("overflowThreshold"),
            "overflowOperator": levelInfo.get("overflowOperator"),
            "trigger": triggerReason,
        }

    def _GetDemandLevelEventType(self, demand: str, level: str) -> str:
        """根据需求和等级生成事件名。"""
        demandName = demand.upper()
        if level == "OVERFLOW":
            return f"NEED_{demandName}_OVERFLOW"
        if level == "URGENT":
            return f"NEED_{demandName}_URGENT"
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
