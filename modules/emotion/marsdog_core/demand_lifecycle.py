"""全局需求生命周期规则。"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from .types import ClampValue, DemandType, NormalizeDemandType


class DemandLifecycleAPI:
    """全局需求生命周期 API 混入类。"""

    def IsDemandLocked(self, currentTime: object | None = None) -> bool:
        """判断当前是否处于需求自然计算锁定时段。"""
        lockWindow = self._GetDemandLockWindow()
        hour = self._GetDemandHourValue(currentTime)
        locked = self._IsHourInRange(hour, int(lockWindow["startHour"]), int(lockWindow["endHour"]))
        self.state.demandLockActive = locked
        return locked

    def UpdateNaturalDemandsByTime(self, currentTime: object | None = None) -> dict[str, int]:
        """按全局规则更新所有自然增长需求。"""
        locked = self.IsDemandLocked(currentTime)
        if locked:
            if hasattr(self, "UpdateSleepinessByTime"):
                self.UpdateSleepinessByTime(currentTime)
            self.state.lastDemandLockState = True
            return self.GetAllDemands()

        if self._ShouldResetMorningDemands(currentTime):
            self.ResetDemandsToMorningInitialValues(currentTime)
            self.state.lastDemandLockState = False
            return self.GetAllDemands()

        self.state.lastDemandLockState = False
        self.UpdateHungerByTime(currentTime)
        if hasattr(self, "UpdateBladderByTime"):
            self.UpdateBladderByTime(currentTime)
        if hasattr(self, "UpdateSleepinessByTime"):
            self.UpdateSleepinessByTime(currentTime)
        if hasattr(self, "UpdateCleanlinessByTime"):
            self.UpdateCleanlinessByTime(currentTime)
        if hasattr(self, "UpdateSocialByTime"):
            self.UpdateSocialByTime(currentTime)
        if hasattr(self, "UpdateExplorationByTime"):
            self.UpdateExplorationByTime(currentTime)
        return self.GetAllDemands()

    def ResetDemandsToMorningInitialValues(self, currentTime: object | None = None) -> dict[str, int]:
        """将所有需求恢复为晨起初始值。"""
        for demand in DemandType:
            if demand == DemandType.SOCIAL and hasattr(self, "InitializeMorningSocial"):
                self.InitializeMorningSocial()
                continue
            if demand == DemandType.EXPLORATION and hasattr(self, "InitializeMorningExploration"):
                self.InitializeMorningExploration()
                continue
            value = self._GetMorningDemandValue(demand.value)
            self.SetDemandValue(demand, value)
        self.state.lastMorningResetKey = self.GetMorningResetKey(currentTime)
        if hasattr(self, "IsSleeping") and hasattr(self, "WakeUp") and self.IsSleeping():
            self.WakeUp(currentTime)
        return self.GetAllDemands()

    def GetMorningResetKey(self, currentTime: object | None = None) -> str:
        """获取晨起重置去重标识。"""
        if currentTime is None:
            return date.today().isoformat()
        if isinstance(currentTime, datetime):
            return currentTime.date().isoformat()
        # 没有日期信息时，只能保证本进程内单次去重。
        return "static-day"

    def ApplyInterruptedDemandDelta(self, demandType: object) -> bool:
        """对被打断的内部需求施加统一数值衰减。"""
        try:
            demand = NormalizeDemandType(demandType)
        except ValueError:
            return False

        demandConfig = self.configs.get("demands", {}).get(demand, {})
        delta = int(demandConfig.get("interruptedDelta", self.configs.get("demandGlobalRules", {}).get("interruptedDemandDelta", -20)))
        oldValue = self.GetDemandValue(demand)
        self.SetDemandValue(demand, ClampValue(oldValue + delta))
        return True

    def ExecuteDemandInterrupted(self, demandType: object) -> bool:
        """执行内部需求被打断后的数值与情绪映射。"""
        if not self.ApplyInterruptedDemandDelta(demandType):
            return False
        self.ApplyActionResultEmotion("ActionInterrupted")
        return True

    def GetDemandTypeByAction(self, actionType: str) -> str | None:
        """根据顶层行为获取对应的内部需求类型。"""
        return self.configs.get("demandGlobalRules", {}).get("actionDemandMap", {}).get(actionType)

    def _GetDemandLockWindow(self) -> dict[str, int]:
        """获取全局需求锁定窗口。"""
        return self.configs.get("demandGlobalRules", {}).get(
            "lockWindow",
            {"startHour": 0, "endHour": 6},
        )

    def _GetMorningDemandValue(self, demand: str) -> int:
        """获取某个需求的晨起初始值。"""
        demandConfig = self.configs.get("demands", {}).get(demand, {})
        if "morningRandomRange" in demandConfig:
            minValue, maxValue = demandConfig["morningRandomRange"]
            return self.random.randint(int(minValue), int(maxValue))
        return int(demandConfig.get("morningInitialValue", self.state.demands.get(demand, 0)))

    def _ShouldResetMorningDemands(self, currentTime: object | None) -> bool:
        """判断本次 Tick 是否需要执行晨起重置。"""
        resetKey = self.GetMorningResetKey(currentTime)
        if self.state.lastMorningResetKey == resetKey:
            return False

        lockWindow = self._GetDemandLockWindow()
        wakeHour = int(lockWindow["endHour"])
        currentHour = self._GetDemandHourValue(currentTime)
        return self.state.lastDemandLockState is True or currentHour == wakeHour

    def _GetDemandHourValue(self, currentTime: object | None) -> int:
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
