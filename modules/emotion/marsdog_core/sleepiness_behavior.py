"""困倦行为驱动与睡眠恢复接口。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .rules import IsConditionMatched
from .types import DemandType, SleepDepthType


class SleepinessBehaviorAPI:
    """困倦行为 API 混入类。"""

    def InitializeMorningSleepiness(self) -> int:
        """按晨起规则初始化困倦值。"""
        sleepinessConfig = self._GetSleepinessConfig()
        minValue, maxValue = sleepinessConfig.get("morningRandomRange", [10, 15])
        value = self.random.randint(int(minValue), int(maxValue))
        self.SetDemandValue(DemandType.SLEEPINESS, value)
        self.UpdateSleepTriggerState()
        return value

    def UpdateSleepinessByTime(self, currentTime: object | None = None) -> int:
        """按每 10 分钟 Tick 的时间规则更新困倦值。"""
        if self.IsSleeping():
            value = self.ApplySleepRecovery(currentTime)
            self.UpdateSleepTriggerState(currentTime)
            return value

        forcedValue = self._GetForcedSleepinessValue(currentTime)
        if forcedValue is not None:
            self.SetDemandValue(DemandType.SLEEPINESS, forcedValue)
            self.UpdateSleepTriggerState(currentTime)
            return self.GetDemandValue(DemandType.SLEEPINESS)

        delta = self._GetSleepinessGrowthDelta(currentTime)
        if delta != 0:
            oldValue = self.GetDemandValue(DemandType.SLEEPINESS)
            self.SetDemandValue(DemandType.SLEEPINESS, oldValue + delta)
        self.UpdateSleepTriggerState(currentTime)
        return self.GetDemandValue(DemandType.SLEEPINESS)

    def UpdateSleepTriggerState(self, currentTime: object | None = None) -> bool:
        """刷新当前 Tick 是否允许触发睡眠行为。"""
        self.state.sleepActionAllowed = self.IsSleepActionAllowed(currentTime)
        return self.state.sleepActionAllowed

    def IsSleepActionAllowed(self, currentTime: object | None = None) -> bool:
        """判断当前时段和困倦值是否允许进入睡眠。"""
        if self.IsSleeping():
            return True

        sleepiness = self.GetDemandValue(DemandType.SLEEPINESS)
        threshold = float(self._GetSleepinessConfig().get("triggerThreshold", 65))
        operator = self._GetSleepinessConfig().get("triggerOperator", "gt")
        if not IsConditionMatched(float(sleepiness), operator, threshold):
            return False

        if self.IsForcedSleepTime(currentTime):
            return True
        return self.IsDaytimeSleepEntryTime(currentTime) and not self.IsForcedAwakeTime(currentTime)

    def SetLightsOffValue(self, isLightsOff: bool) -> None:
        """设置是否识别到关灯。"""
        self.state.lightsOff = bool(isLightsOff)
        self.UpdateSleepTriggerState()

    def IsSleeping(self) -> bool:
        """判断当前是否处于睡眠状态。"""
        return bool(self.state.isSleeping)

    def GetSleepDepthValue(self) -> str:
        """获取当前睡眠深度。"""
        return self.state.sleepDepth

    def ExecuteSleep(self) -> bool:
        """执行入睡结果，进入浅睡状态。"""
        self.state.sleepDepth = SleepDepthType.SHALLOW.value
        self.state.isSleeping = True
        self.state.sleepDurationMinutes = 0
        self.state.shallowSleepTicksRemaining = int(
            self._GetSleepinessConfig().get("shallowSleepTicks", 14)
        )
        self.UpdateSleepTriggerState()
        return True

    def ApplySleepRecovery(self, currentTime: object | None = None) -> int:
        """睡眠中按浅睡/深睡规则恢复困倦值。"""
        if not self.IsSleeping():
            return self.GetDemandValue(DemandType.SLEEPINESS)

        if self.state.sleepDepth == SleepDepthType.SHALLOW.value:
            return self._ApplyShallowSleepRecovery(currentTime)
        return self._ApplyDeepSleepRecovery(currentTime)

    def WakeUp(self, currentTime: object | None = None) -> None:
        """结束睡眠状态。"""
        self.state.isSleeping = False
        self.state.sleepDepth = SleepDepthType.SHALLOW.value
        self.state.shallowSleepTicksRemaining = 0
        self.UpdateSleepTriggerState(currentTime)

    def IsForcedSleepTime(self, currentTime: object | None = None) -> bool:
        """判断当前是否处于凌晨或关灯强制睡眠条件。"""
        return self._GetForcedSleepinessValue(currentTime) is not None

    def IsForcedAwakeTime(self, currentTime: object | None = None) -> bool:
        """判断当前是否处于强制清醒时段。"""
        hour = self._GetSleepinessHourValue(currentTime)
        for rule in self._GetSleepinessConfig().get("forcedAwakeRules", []):
            if self._IsHourInRange(hour, int(rule["startHour"]), int(rule["endHour"])):
                return True
        return False

    def IsDaytimeSleepEntryTime(self, currentTime: object | None = None) -> bool:
        """判断当前是否处于白天可入睡时段。"""
        entryWindow = self._GetSleepinessConfig().get(
            "sleepEntryWindow",
            {"startHour": 6, "endHour": 21},
        )
        hour = self._GetSleepinessHourValue(currentTime)
        return self._IsHourInRange(hour, int(entryWindow["startHour"]), int(entryWindow["endHour"]))

    def _ApplyShallowSleepRecovery(self, currentTime: object | None) -> int:
        """执行一次浅睡恢复，并在配置时长结束后决定醒来或转深睡。"""
        self._ApplySleepinessDelta(SleepDepthType.SHALLOW.value)
        self.state.shallowSleepTicksRemaining = max(0, self.state.shallowSleepTicksRemaining - 1)

        if self.state.shallowSleepTicksRemaining == 0:
            threshold = int(self._GetSleepinessConfig().get("triggerThreshold", 65))
            if self.GetDemandValue(DemandType.SLEEPINESS) > threshold or self.IsForcedSleepTime(currentTime):
                self._EnterDeepSleep()
            else:
                self.WakeUp()
        return self.GetDemandValue(DemandType.SLEEPINESS)

    def _ApplyDeepSleepRecovery(self, currentTime: object | None) -> int:
        """执行一次深睡恢复，凌晨强制睡眠期间不自然醒来。"""
        self._ApplySleepinessDelta(SleepDepthType.DEEP.value)
        wakeUpThreshold = int(self._GetSleepinessConfig().get("wakeUpThreshold", 20))
        if (
            self.GetDemandValue(DemandType.SLEEPINESS) <= wakeUpThreshold
            and not self.IsForcedSleepTime(currentTime)
        ):
            self.WakeUp()
        return self.GetDemandValue(DemandType.SLEEPINESS)

    def _ApplySleepinessDelta(self, sleepDepth: str) -> None:
        """按睡眠深度应用一次困倦恢复值。"""
        recoveryRules = self._GetSleepinessConfig().get("recoveryRules", {})
        delta = int(recoveryRules.get(sleepDepth, 0))
        oldValue = self.GetDemandValue(DemandType.SLEEPINESS)
        self.SetDemandValue(DemandType.SLEEPINESS, oldValue + delta)
        self.state.sleepDurationMinutes += 10

    def _EnterDeepSleep(self) -> None:
        """从浅睡切换到深睡状态。"""
        self.state.sleepDepth = SleepDepthType.DEEP.value
        self.state.shallowSleepTicksRemaining = 0

    def _GetSleepinessConfig(self) -> dict[str, Any]:
        """获取困倦配置。"""
        return self.configs.get("demands", {}).get(DemandType.SLEEPINESS.value, {})

    def _GetForcedSleepinessValue(self, currentTime: object | None) -> int | None:
        """获取凌晨或关灯强制困倦值。"""
        for rule in self._GetSleepinessConfig().get("forceSleepRules", []):
            if rule.get("event") == "LightsOff" and self.state.lightsOff:
                return int(rule["value"])
            if "startHour" in rule and "endHour" in rule:
                hour = self._GetSleepinessHourValue(currentTime)
                if self._IsHourInRange(hour, int(rule["startHour"]), int(rule["endHour"])):
                    return int(rule["value"])
        return None

    def _GetSleepinessGrowthDelta(self, currentTime: object | None) -> int:
        """根据当前时间计算困倦增量。"""
        hour = self._GetSleepinessHourValue(currentTime)
        for rule in self._GetSleepinessConfig().get("growthRules", []):
            startHour = int(rule["startHour"])
            endHour = int(rule["endHour"])
            if self._IsHourInRange(hour, startHour, endHour):
                return int(rule.get("delta", 0))
        return 0

    def _GetSleepinessHourValue(self, currentTime: object | None) -> int:
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
