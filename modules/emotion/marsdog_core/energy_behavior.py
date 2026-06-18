"""精力/电量需求驱动与执行接口。"""

from __future__ import annotations

from typing import Any

from .rules import IsConditionMatched
from .types import ActionResultType, DemandType


class EnergyBehaviorAPI:
    """精力需求 API 混入类。"""

    def InitializeMorningEnergy(self) -> int:
        """按晨起规则初始化精力值。"""
        value = int(self._GetEnergyConfig().get("morningInitialValue", 100))
        self.SetDemandValue(DemandType.ENERGY, value)
        return value

    def GetBatteryValue(self) -> int:
        """获取当前硬件电量百分比。"""
        return self.GetDemandValue(DemandType.ENERGY)

    def SetEnergyBatteryValue(self, value: int) -> bool:
        """设置当前硬件电量百分比。"""
        return self.SetDemandValue(DemandType.ENERGY, value)

    def ExecuteRecharge(self) -> bool:
        """执行恢复精力行为并回写电量。"""
        energyConfig = self._GetEnergyConfig()
        targetValue = int(energyConfig.get("rechargeTarget", 100))
        oldValue = self.GetDemandValue(DemandType.ENERGY)
        self.SetDemandValue(DemandType.ENERGY, targetValue)
        self._ApplyRechargeResultEmotion(oldValue, self.GetDemandValue(DemandType.ENERGY))
        return True

    def Recharge(self) -> bool:
        """APP 业务接口：充电。"""
        return self.ExecuteRecharge()

    def _GetEnergyConfig(self) -> dict[str, Any]:
        """获取精力配置。"""
        return self.configs.get("demands", {}).get(DemandType.ENERGY.value, {})

    def _ApplyRechargeResultEmotion(self, oldValue: int, newValue: int) -> None:
        """根据充电执行结果施加情绪变化。"""
        threshold = float(self._GetEnergyConfig().get("urgentThreshold", 20))
        operator = self._GetEnergyConfig().get("urgentOperator", "lt")
        oldTriggered = IsConditionMatched(float(oldValue), operator, threshold)
        newTriggered = IsConditionMatched(float(newValue), operator, threshold)
        if oldTriggered and not newTriggered:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_SATISFIED)
        elif newTriggered:
            self.ApplyActionResultEmotion(ActionResultType.DEMAND_UNSATISFIED)
