"""饥渴行为驱动与执行接口。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .types import (
    ActionResultType,
    ClampValue,
    DemandType,
    EatEfficiencyType,
    FoodType,
    NormalizeEatEfficiencyType,
    NormalizeFoodType,
)


class HungerBehaviorAPI:
    """饥渴行为 API 混入类。"""

    def InitializeMorningHunger(self) -> int:
        """按晨起规则初始化饥渴值。"""
        hungerConfig = self._GetHungerConfig()
        minValue, maxValue = hungerConfig.get("morningRandomRange", [60, 70])
        value = self.random.randint(int(minValue), int(maxValue))
        self.SetDemandValue(DemandType.HUNGER, value)
        return value

    def UpdateHungerByTime(self, currentTime: object | None = None) -> int:
        """按每 10 分钟 Tick 的时间规则增长饥渴值。"""
        if hasattr(self, "IsDemandLocked") and self.IsDemandLocked(currentTime):
            return self.GetDemandValue(DemandType.HUNGER)

        delta = self._GetHungerGrowthDelta(currentTime)
        if delta != 0:
            oldValue = self.GetDemandValue(DemandType.HUNGER)
            self.SetDemandValue(DemandType.HUNGER, oldValue + delta)
        return self.GetDemandValue(DemandType.HUNGER)

    def GetHungerRecoveryValue(
        self,
        foodType: object = FoodType.NORMAL_FOOD.value,
        portions: float = 1,
        eatEfficiency: object = EatEfficiencyType.FULL.value,
    ) -> int:
        """计算本次进食可恢复的饥渴值。"""
        food = NormalizeFoodType(foodType)
        efficiencyName = NormalizeEatEfficiencyType(eatEfficiency)
        hungerConfig = self._GetHungerConfig()
        recoveryPower = hungerConfig.get("foodRecovery", {}).get(food)
        efficiency = hungerConfig.get("eatEfficiency", {}).get(efficiencyName)
        if recoveryPower is None or efficiency is None:
            raise ValueError(f"Unsupported hunger recovery config: {food}, {efficiencyName}")

        # 公式：恢复值 = 单份恢复力 * 进食效率 * 提供的食物份数。
        recoveryValue = float(recoveryPower) * float(efficiency) * max(0.0, float(portions))
        return int(round(recoveryValue))

    def ExecuteEat(
        self,
        foodType: object = FoodType.NORMAL_FOOD.value,
        portions: float = 1,
        eatEfficiency: object = EatEfficiencyType.FULL.value,
    ) -> bool:
        """执行进食行为并衰减饥渴值。"""
        try:
            efficiencyName = NormalizeEatEfficiencyType(eatEfficiency)
            recoveryValue = self.GetHungerRecoveryValue(foodType, portions, efficiencyName)
        except (TypeError, ValueError):
            return False

        oldValue = self.GetDemandValue(DemandType.HUNGER)
        newValue = ClampValue(oldValue - recoveryValue)
        self.SetDemandValue(DemandType.HUNGER, newValue)
        if hasattr(self, "ApplyBladderAfterEat"):
            self.ApplyBladderAfterEat(oldValue)
        if hasattr(self, "ApplyCleanlinessAfterEat"):
            self.ApplyCleanlinessAfterEat()
        self._ApplyEatResultEmotion(oldValue, newValue, efficiencyName)
        return True

    def Feed(
        self,
        foodType: object = FoodType.NORMAL_FOOD.value,
        portions: float = 1,
        eatEfficiency: object = EatEfficiencyType.FULL.value,
    ) -> bool:
        """APP 业务接口：喂食。"""
        return self.ExecuteEat(foodType, portions, eatEfficiency)

    def _GetHungerConfig(self) -> dict[str, Any]:
        """获取饥渴配置。"""
        return self.configs.get("demands", {}).get(DemandType.HUNGER.value, {})

    def _GetHungerGrowthDelta(self, currentTime: object | None) -> int:
        """根据当前时间计算单次 Tick 增量。"""
        hour = self._GetHourValue(currentTime)
        for rule in self._GetHungerConfig().get("growthRules", []):
            startHour = int(rule["startHour"])
            endHour = int(rule["endHour"])
            if self._IsHourInRange(hour, startHour, endHour):
                return int(rule.get("delta", 0))
        return 0

    def _GetHourValue(self, currentTime: object | None) -> int:
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

    def _ApplyEatResultEmotion(self, oldValue: int, newValue: int, efficiencyName: str) -> None:
        """根据进食执行结果施加情绪变化。"""
        threshold = int(self._GetHungerConfig().get("triggerThreshold", 70))
        if efficiencyName == EatEfficiencyType.HALF_INTERRUPTED.value:
            self.ApplyActionResultEmotion(ActionResultType.ACTION_INTERRUPTED)
        elif oldValue > threshold and newValue <= threshold:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_SATISFIED)
        elif newValue > threshold:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_UNSATISFIED)
