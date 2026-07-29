"""充电需求与硬件电量转换接口。"""

from __future__ import annotations

from math import floor, isfinite
from typing import Any

from .rules import IsConditionMatched
from .types import ActionResultType, ClampValue, DemandType


class EnergyBehaviorAPI:
    """充电需求 API 混入类。"""

    def InitializeStartupEnergy(self) -> int:
        """按启动配置初始化满电状态。"""
        batteryValue = int(self._GetEnergyConfig().get("startupBatteryValue", 100))
        self.SetEnergyBatteryValue(batteryValue)
        return self.GetDemandValue(DemandType.ENERGY)

    def InitializeMorningEnergy(self) -> int:
        """兼容旧调用：显式调用时重新初始化为启动电量。"""
        return self.InitializeStartupEnergy()

    def GetBatteryValue(self) -> int:
        """根据 Energy 需求值获取当前硬件电量百分比。"""
        return 100 - self.GetDemandValue(DemandType.ENERGY)

    def SetEnergyBatteryValue(self, batteryValue: int) -> bool:
        """根据硬件电量百分比写入 Energy 充电需求值。"""
        normalizedBatteryValue = ClampValue(batteryValue)
        return self.SetDemandValue(
            DemandType.ENERGY,
            100 - normalizedBatteryValue,
        )

    def UpdateEnergyByTime(
        self,
        currentTime: object | None = None,
        elapsedSeconds: float | None = None,
    ) -> int:
        """按本次电池实际应计经过秒数结算两小时续航耗电。"""
        del currentTime
        energyConfig = self._GetEnergyConfig()
        enduranceMinutes = float(
            energyConfig.get("fullChargeEnduranceMinutes", 120)
        )
        intervalMinutes = float(
            energyConfig.get("naturalUpdateIntervalMinutes", 10)
        )
        if isinstance(elapsedSeconds, bool):
            raise ValueError("Energy elapsed time must be numeric")
        drainElapsedSeconds = (
            intervalMinutes * 60.0
            if elapsedSeconds is None
            else float(elapsedSeconds)
        )
        if (
            not isfinite(enduranceMinutes)
            or enduranceMinutes <= 0
            or not isfinite(intervalMinutes)
            or intervalMinutes <= 0
            or not isfinite(drainElapsedSeconds)
            or drainElapsedSeconds < 0
        ):
            raise ValueError(
                "Energy endurance, update interval and elapsed time are invalid"
            )

        oldValue = self.GetDemandValue(DemandType.ENERGY)
        if oldValue >= 100:
            self.state.energyDrainRemainder = 0.0
            return oldValue
        if drainElapsedSeconds == 0:
            return oldValue

        # 默认10分钟增量和凌晨不足1%的增量都要保留余量，保证累计耗电准确。
        exactDelta = (
            self.state.energyDrainRemainder
            + 100.0 * drainElapsedSeconds / (enduranceMinutes * 60.0)
        )
        integerDelta = floor(exactDelta + 1e-9)
        self.state.energyDrainRemainder = max(0.0, exactDelta - integerDelta)
        newValue = ClampValue(oldValue + integerDelta)

        # 自然耗电不能调用公共 SetDemandValue，否则小数余量会被当作外部写入清空。
        self.state.demands[DemandType.ENERGY.value] = newValue
        if newValue >= 100:
            self.state.energyDrainRemainder = 0.0
        return newValue

    def ExecuteRecharge(self) -> bool:
        """执行充电行为并把目标电量转换为 Energy 需求值。"""
        energyConfig = self._GetEnergyConfig()
        targetBatteryValue = int(energyConfig.get("rechargeTarget", 100))
        oldValue = self.GetDemandValue(DemandType.ENERGY)
        self.SetEnergyBatteryValue(targetBatteryValue)
        self._ApplyRechargeResultEmotion(oldValue, self.GetDemandValue(DemandType.ENERGY))
        return True

    def Recharge(self) -> bool:
        """APP 业务接口：充电。"""
        return self.ExecuteRecharge()

    def _GetEnergyConfig(self) -> dict[str, Any]:
        """获取 Energy 充电需求配置。"""
        return self.configs.get("demands", {}).get(DemandType.ENERGY.value, {})

    def _ApplyRechargeResultEmotion(self, oldValue: int, newValue: int) -> None:
        """根据充电执行结果施加情绪变化。"""
        threshold = float(self._GetEnergyConfig().get("triggerThreshold", 80))
        operator = self._GetEnergyConfig().get("triggerOperator", "gt")
        oldTriggered = IsConditionMatched(float(oldValue), operator, threshold)
        newTriggered = IsConditionMatched(float(newValue), operator, threshold)
        if oldTriggered and not newTriggered:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_SATISFIED)
        elif newTriggered:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_UNSATISFIED)
