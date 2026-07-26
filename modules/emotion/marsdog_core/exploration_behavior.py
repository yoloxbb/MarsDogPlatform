"""探索需求数值更新接口。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .rules import IsConditionMatched
from .types import ClampValue, DemandType


class ExplorationBehaviorAPI:
    """只负责 Exploration 初始化、自然增长和结果结算。"""

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
        """白天且 Energy 需求低于阈值时按每 10 分钟增长 Exploration。"""
        if hasattr(self, "IsDemandLocked") and self.IsDemandLocked(currentTime):
            return self.GetDemandValue(DemandType.EXPLORATION)

        delta = self._GetExplorationGrowthDelta(currentTime)
        if delta:
            oldValue = self.GetDemandValue(DemandType.EXPLORATION)
            self.SetDemandValue(DemandType.EXPLORATION, oldValue + delta)
        return self.GetDemandValue(DemandType.EXPLORATION)

    def ExecuteExploration(self, resultType: object | None = None) -> bool:
        """探索完成后统一按 Completed 规则降低 Exploration。"""
        del resultType
        recovery = int(self._GetExplorationConfig().get("recoveryRules", {}).get("Completed", 0))
        if recovery <= 0:
            return False
        oldValue = self.GetDemandValue(DemandType.EXPLORATION)
        return self.SetDemandValue(DemandType.EXPLORATION, oldValue - recovery)

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
