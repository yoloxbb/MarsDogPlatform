"""清洁需求驱动与执行接口。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .rules import IsConditionMatched
from .types import ActionResultType, ClampValue, DemandType


class CleanlinessBehaviorAPI:
    """清洁需求 API 混入类。"""

    def InitializeMorningCleanliness(self) -> int:
        """按晨起规则初始化清洁值。"""
        cleanlinessConfig = self._GetCleanlinessConfig()
        minValue, maxValue = cleanlinessConfig.get("morningRandomRange", [5, 15])
        value = self.random.randint(int(minValue), int(maxValue))
        self.SetDemandValue(DemandType.CLEANLINESS, value)
        return value

    def UpdateCleanlinessByTime(self, currentTime: object | None = None) -> int:
        """按每 10 分钟 Tick 的时间规则增长清洁值。"""
        if hasattr(self, "IsDemandLocked") and self.IsDemandLocked(currentTime):
            return self.GetDemandValue(DemandType.CLEANLINESS)

        delta = self._GetCleanlinessGrowthDelta(currentTime)
        if delta != 0:
            oldValue = self.GetDemandValue(DemandType.CLEANLINESS)
            self.SetDemandValue(DemandType.CLEANLINESS, oldValue + delta)
        return self.GetDemandValue(DemandType.CLEANLINESS)

    def ApplyCleanlinessAfterEat(self) -> int:
        """进食后增加身体脏污程度。"""
        delta = int(self._GetCleanlinessConfig().get("afterEatBonus", 20))
        oldValue = self.GetDemandValue(DemandType.CLEANLINESS)
        self.SetDemandValue(DemandType.CLEANLINESS, oldValue + delta)
        return self.GetDemandValue(DemandType.CLEANLINESS)

    def ExecuteGroom(self) -> bool:
        """执行清洁行为并降低身体脏污程度。"""
        cleanlinessConfig = self._GetCleanlinessConfig()
        recoveryValue = int(cleanlinessConfig.get("groomRecovery", 50))
        oldValue = self.GetDemandValue(DemandType.CLEANLINESS)
        newValue = ClampValue(oldValue - recoveryValue)
        self.SetDemandValue(DemandType.CLEANLINESS, newValue)
        self._ApplyGroomResultEmotion(oldValue, newValue)
        return True

    def Groom(self) -> bool:
        """APP 业务接口：清洁。"""
        return self.ExecuteGroom()

    def _GetCleanlinessConfig(self) -> dict[str, Any]:
        """获取清洁配置。"""
        return self.configs.get("demands", {}).get(DemandType.CLEANLINESS.value, {})

    def _GetCleanlinessGrowthDelta(self, currentTime: object | None) -> int:
        """根据当前时间计算清洁值增量。"""
        hour = self._GetCleanlinessHourValue(currentTime)
        for rule in self._GetCleanlinessConfig().get("growthRules", []):
            startHour = int(rule["startHour"])
            endHour = int(rule["endHour"])
            if self._IsHourInRange(hour, startHour, endHour):
                return int(rule.get("delta", 0))
        return 0

    def _GetCleanlinessHourValue(self, currentTime: object | None) -> int:
        """从不同时间对象中取小时值。"""
        if currentTime is None:
            return datetime.now().hour
        if isinstance(currentTime, datetime):
            return currentTime.hour
        if isinstance(currentTime, time):
            return currentTime.hour
        if isinstance(currentTime, int):
            return currentTime
        raise ValueError(f"Unsupported time value: {currentTime}")

    def _IsHourInRange(self, hour: int, startHour: int, endHour: int) -> bool:
        """判断小时是否落入时间段。"""
        if startHour <= endHour:
            return startHour <= hour < endHour
        return hour >= startHour or hour < endHour

    def _ApplyGroomResultEmotion(self, oldValue: int, newValue: int) -> None:
        """根据清洁执行结果施加情绪变化。"""
        threshold = float(self._GetCleanlinessConfig().get("urgentThreshold", 70))
        operator = self._GetCleanlinessConfig().get("urgentOperator", "gt")
        oldTriggered = IsConditionMatched(float(oldValue), operator, threshold)
        newTriggered = IsConditionMatched(float(newValue), operator, threshold)
        if oldTriggered and not newTriggered:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_SATISFIED)
        elif newTriggered:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_UNSATISFIED)
