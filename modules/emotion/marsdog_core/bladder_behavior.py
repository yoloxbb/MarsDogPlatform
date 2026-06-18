"""排泄需求驱动与执行接口。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .rules import IsConditionMatched
from .types import ActionResultType, ClampValue, DemandType


class BladderBehaviorAPI:
    """排泄需求 API 混入类。"""

    def InitializeMorningBladder(self) -> int:
        """按晨起规则初始化排泄值。"""
        bladderConfig = self._GetBladderConfig()
        minValue, maxValue = bladderConfig.get("morningRandomRange", [20, 30])
        value = self.random.randint(int(minValue), int(maxValue))
        self.SetDemandValue(DemandType.BLADDER, value)
        return value

    def UpdateBladderByTime(self, currentTime: object | None = None) -> int:
        """按每 10 分钟 Tick 的时间规则增长排泄值。"""
        if hasattr(self, "IsDemandLocked") and self.IsDemandLocked(currentTime):
            return self.GetDemandValue(DemandType.BLADDER)

        delta = self._GetBladderGrowthDelta(currentTime)
        if delta != 0:
            oldValue = self.GetDemandValue(DemandType.BLADDER)
            self.SetDemandValue(DemandType.BLADDER, oldValue + delta)
        return self.GetDemandValue(DemandType.BLADDER)

    def ApplyBladderAfterEat(self, hungerBeforeEat: int) -> int:
        """根据进食前饥渴值增加排泄值。"""
        delta = self._GetEatBonusDelta(hungerBeforeEat)
        if delta == 0:
            return self.GetDemandValue(DemandType.BLADDER)
        oldValue = self.GetDemandValue(DemandType.BLADDER)
        self.SetDemandValue(DemandType.BLADDER, oldValue + delta)
        return self.GetDemandValue(DemandType.BLADDER)

    def ApplyBladderEventBonus(self, eventType: str) -> bool:
        """根据关键事件增加排泄值。"""
        eventBonus = self._GetBladderConfig().get("eventBonus", {})
        if eventType not in eventBonus:
            return False
        oldValue = self.GetDemandValue(DemandType.BLADDER)
        self.SetDemandValue(DemandType.BLADDER, oldValue + int(eventBonus[eventType]))
        return True

    def ExecuteDefecate(self) -> bool:
        """执行排泄成功结果。"""
        oldValue = self.GetDemandValue(DemandType.BLADDER)
        self.SetDemandValue(DemandType.BLADDER, 0)
        if oldValue > 0:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_SATISFIED)
        return True

    def Defecate(self) -> bool:
        """APP 业务接口：排泄。"""
        return self.ExecuteDefecate()

    def _GetBladderConfig(self) -> dict[str, Any]:
        """获取排泄配置。"""
        return self.configs.get("demands", {}).get(DemandType.BLADDER.value, {})

    def _GetEatBonusDelta(self, hungerBeforeEat: int) -> int:
        """按进食前饥渴值获取排泄加成。"""
        for rule in self._GetBladderConfig().get("eatBonusRules", []):
            if IsConditionMatched(
                float(hungerBeforeEat),
                rule["hungerOperator"],
                float(rule["hungerThreshold"]),
            ):
                return int(rule["delta"])
        return 0

    def _GetBladderGrowthDelta(self, currentTime: object | None) -> int:
        """根据当前时间计算排泄值增量。"""
        hour = self._GetBladderHourValue(currentTime)
        for rule in self._GetBladderConfig().get("growthRules", []):
            startHour = int(rule["startHour"])
            endHour = int(rule["endHour"])
            if self._IsHourInRange(hour, startHour, endHour):
                return int(rule.get("delta", 0))
        return 0

    def _GetBladderHourValue(self, currentTime: object | None) -> int:
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
