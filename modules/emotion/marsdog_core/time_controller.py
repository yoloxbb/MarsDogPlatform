"""时间压缩测试使用的虚拟时钟与 Tick 调度器。"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Callable

from .types import NormalizeTimeModeType, TimeModeType


TIME_MODE_SCALES = {
    TimeModeType.STANDARD_24H.value: 1,
    TimeModeType.DEMO_12H.value: 2,
    TimeModeType.DEMO_2H.value: 12,
}


class MarsdogTimeController:
    """根据真实经过时间计算统一的虚拟时间。"""

    def __init__(
        self,
        timeMode: object = TimeModeType.STANDARD_24H.value,
        virtualStartTime: str = "auto",
        wallTimeProvider: Callable[[], float] | None = None,
        monotonicProvider: Callable[[], float] | None = None,
    ) -> None:
        """初始化时间模式、倍率和虚拟时间锚点。"""
        self._timeMode = NormalizeTimeModeType(timeMode)
        self._timeScale = TIME_MODE_SCALES[self._timeMode]
        self._wallTimeProvider = wallTimeProvider or time.time
        self._monotonicProvider = monotonicProvider or time.monotonic
        self._wallStartTimestamp = float(self._wallTimeProvider())
        self._monotonicStart = float(self._monotonicProvider())
        wallStartDateTime = datetime.fromtimestamp(self._wallStartTimestamp).astimezone()
        self._virtualStartDateTime = self._ResolveVirtualStartDateTimeValue(
            wallStartDateTime,
            virtualStartTime,
        )

    def GetTimeModeValue(self) -> str:
        """获取当前时间模式。"""
        return self._timeMode

    def GetTimeScaleValue(self) -> int:
        """获取当前虚拟时间倍率。"""
        return self._timeScale

    def GetVirtualStartDateTimeValue(self) -> datetime:
        """获取虚拟时间起始点。"""
        return self._virtualStartDateTime

    def GetVirtualDateTimeValue(self) -> datetime:
        """获取当前虚拟日期时间。"""
        elapsedSeconds = self._GetVirtualElapsedSecondsValue()
        return self._virtualStartDateTime + timedelta(seconds=elapsedSeconds)

    def GetVirtualTimestampValue(self) -> float:
        """获取当前虚拟 Unix 时间戳。"""
        return self.GetVirtualDateTimeValue().timestamp()

    def GetRealIntervalValue(self, virtualSeconds: float) -> float:
        """把虚拟秒数换算成真实定时器间隔。"""
        interval = float(virtualSeconds)
        if interval <= 0:
            raise ValueError("Virtual interval must be greater than zero")
        return interval / float(self._timeScale)

    def GetTimeContextValue(
        self,
        virtualDateTime: datetime | None = None,
        wallTimestamp: float | None = None,
    ) -> dict[str, object]:
        """获取可附加到状态或事件消息的时间上下文。"""
        currentVirtualTime = virtualDateTime or self.GetVirtualDateTimeValue()
        elapsedSeconds = max(
            0.0,
            (currentVirtualTime - self._virtualStartDateTime).total_seconds(),
        )
        return {
            "mode": self._timeMode,
            "scale": self._timeScale,
            "virtualStartDateTime": self._virtualStartDateTime.isoformat(),
            "virtualDateTime": currentVirtualTime.isoformat(),
            "virtualTimestamp": currentVirtualTime.timestamp(),
            "virtualElapsedSeconds": elapsedSeconds,
            "wallTimestamp": float(
                self._wallTimeProvider() if wallTimestamp is None else wallTimestamp
            ),
        }

    def _GetVirtualElapsedSecondsValue(self) -> float:
        """按单调时钟计算已经经过的虚拟秒数。"""
        realElapsedSeconds = max(
            0.0,
            float(self._monotonicProvider()) - self._monotonicStart,
        )
        return realElapsedSeconds * float(self._timeScale)

    def _ResolveVirtualStartDateTimeValue(
        self,
        wallStartDateTime: datetime,
        virtualStartTime: str,
    ) -> datetime:
        """根据模式和 HH:MM 参数确定虚拟时间起点。"""
        startTime = str(virtualStartTime).strip()
        if startTime == "auto":
            if self._timeMode == TimeModeType.STANDARD_24H.value:
                return wallStartDateTime
            return wallStartDateTime.replace(hour=6, minute=0, second=0, microsecond=0)

        match = re.fullmatch(r"(\d{2}):(\d{2})", startTime)
        if match is None:
            raise ValueError("virtual_start_time must be 'auto' or HH:MM")
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("virtual_start_time is outside the valid HH:MM range")
        return wallStartDateTime.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )


class VirtualTickScheduler:
    """按虚拟时间返回当前应补算的全部固定间隔 Tick。"""

    def __init__(self, startDateTime: datetime, intervalSeconds: float) -> None:
        """从虚拟起点后的第一个间隔开始调度。"""
        interval = float(intervalSeconds)
        if interval <= 0:
            raise ValueError("Tick interval must be greater than zero")
        self._interval = timedelta(seconds=interval)
        self._nextTickDateTime = startDateTime + self._interval

    def GetDueTickDateTimesValue(self, currentDateTime: datetime) -> list[datetime]:
        """获取并消费截至当前虚拟时间所有到期 Tick。"""
        dueTicks: list[datetime] = []
        while self._nextTickDateTime <= currentDateTime:
            dueTicks.append(self._nextTickDateTime)
            self._nextTickDateTime += self._interval
        return dueTicks

    def GetNextTickDateTimeValue(self) -> datetime:
        """获取下一次尚未消费的虚拟 Tick 时间。"""
        return self._nextTickDateTime
