"""充电需求与硬件电量转换接口。"""

from __future__ import annotations

from typing import Any

from .rules import IsConditionMatched
from .types import ActionResultType, ClampValue, DemandType


class EnergyBehaviorAPI:
    """充电需求 API 混入类。"""

    def InitializeMorningEnergy(self) -> int:
        """按晨起规则初始化充电需求值。"""
        value = int(self._GetEnergyConfig().get("morningInitialValue", 0))
        self.SetDemandValue(DemandType.ENERGY, value)
        return value

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
        threshold = float(self._GetEnergyConfig().get("urgentThreshold", 80))
        operator = self._GetEnergyConfig().get("urgentOperator", "gt")
        oldTriggered = IsConditionMatched(float(oldValue), operator, threshold)
        newTriggered = IsConditionMatched(float(newValue), operator, threshold)
        if oldTriggered and not newTriggered:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_SATISFIED)
        elif newTriggered:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_UNSATISFIED)
