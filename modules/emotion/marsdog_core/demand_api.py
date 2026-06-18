"""需求接口实现。"""

from __future__ import annotations

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
