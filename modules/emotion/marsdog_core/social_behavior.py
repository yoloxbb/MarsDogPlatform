"""社交需求数值更新接口。"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .types import ClampValue, DemandType


class SocialBehaviorAPI:
    """只负责 Social 数值初始化、自然增长和结果结算辅助。"""

    def InitializeMorningSocial(self) -> int:
        """按随机基础值和性格系数初始化晨起 Social。"""
        value = self._CalculateMorningSocialValue()
        self.SetDemandValue(DemandType.SOCIAL, value)
        return value

    def UpdateSocialByTime(self, currentTime: object | None = None) -> int:
        """按每 10 分钟 Tick 的时间规则增长 Social。"""
        if hasattr(self, "IsDemandLocked") and self.IsDemandLocked(currentTime):
            return self.GetDemandValue(DemandType.SOCIAL)

        delta = self._GetSocialGrowthDelta(currentTime)
        if delta:
            oldValue = self.GetDemandValue(DemandType.SOCIAL)
            self.SetDemandValue(DemandType.SOCIAL, oldValue + delta)
        return self.GetDemandValue(DemandType.SOCIAL)

    def OnOwnerPresenceChanged(self, isPresent: bool) -> None:
        """处理明确的主人在家或离家状态变化。"""
        present = bool(isPresent)
        if not present and self.state.ownerPresent is not False:
            delta = int(self._GetSocialConfig().get("ownerLeftHomeDelta", 30))
            oldValue = self.GetDemandValue(DemandType.SOCIAL)
            self.SetDemandValue(DemandType.SOCIAL, oldValue + delta)
        self.state.ownerPresent = present

    def GetSocialOutcomeRecoveryValue(self, socialOutcome: object) -> int | None:
        """根据外部结果里的 socialOutcome 读取 Social 恢复值。"""
        outcome = str(socialOutcome)
        config = self._GetSocialConfig()
        recoveryMap = {
            "OwnerInteraction": int(config.get("ownerInteractionRecovery", 25)),
            "DogHumanResponded": int(config.get("dogHumanInteractionRecovery", 20)),
            "DogAnimalResponded": int(config.get("dogAnimalInteractionRecovery", 15)),
        }
        return recoveryMap.get(outcome)

    def _CalculateMorningSocialValue(self) -> int:
        """计算经过性格修正的晨起 Social。"""
        minValue, maxValue = self._GetSocialConfig().get("morningRandomRange", [20, 30])
        baseValue = self.random.randint(int(minValue), int(maxValue))
        coefficient = self.GetSocialPersonalityCoefficientValue()
        return ClampValue(round(baseValue * coefficient))

    def _GetSocialGrowthDelta(self, currentTime: object | None) -> int:
        """根据当前时间计算单次 Social 增量。"""
        hour = self._GetSocialHourValue(currentTime)
        for rule in self._GetSocialConfig().get("growthRules", []):
            if self._IsHourInRange(hour, int(rule["startHour"]), int(rule["endHour"])):
                return int(rule.get("delta", 0))
        return 0

    def _GetSocialHourValue(self, currentTime: object | None) -> int:
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

    def _GetSocialConfig(self) -> dict[str, Any]:
        """获取 Social 配置。"""
        return self.configs.get("demands", {}).get(DemandType.SOCIAL.value, {})

    def _IsHourInRange(self, hour: int, startHour: int, endHour: int) -> bool:
        """判断小时是否落入时间段。"""
        if startHour <= endHour:
            return startHour <= hour < endHour
        return hour >= startHour or hour < endHour
