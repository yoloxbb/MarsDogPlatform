"""时间压缩使用的虚拟时钟及虚拟、真实 Tick 调度器。"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from math import floor, isfinite
from typing import Callable

from .types import NormalizeTimeScaleValue


TIME_SCALE_MODE_LABELS = {
    1: "standard_24h",
    2: "demo_12h",
    12: "demo_2h",
}


class MarsdogTimeController:
    """根据真实经过时间计算统一的虚拟时间。"""

    def __init__(
        self,
        timeScale: object = 1,
        virtualStartTime: str = "auto",
        wallTimeProvider: Callable[[], float] | None = None,
        monotonicProvider: Callable[[], float] | None = None,
    ) -> None:
        """初始化整数倍率和虚拟时间锚点。"""
        self._timeScale = NormalizeTimeScaleValue(timeScale)
        self._wallTimeProvider = wallTimeProvider or time.time
        self._monotonicProvider = monotonicProvider or time.monotonic
        self._wallStartTimestamp = float(self._wallTimeProvider())
        self._monotonicAnchor = float(self._monotonicProvider())
        wallStartDateTime = datetime.fromtimestamp(self._wallStartTimestamp).astimezone()
        self._virtualStartDateTime = self._ResolveVirtualStartDateTimeValue(
            wallStartDateTime,
            virtualStartTime,
        )
        self._virtualAnchorDateTime = self._virtualStartDateTime
        self._timeRevision = 0

    def GetTimeScaleValue(self) -> int:
        """获取当前虚拟时间倍率。"""
        return self._timeScale

    def GetTimeRevisionValue(self) -> int:
        """获取运行时倍率配置修订号。"""
        return self._timeRevision

    def GetVirtualStartDateTimeValue(self) -> datetime:
        """获取虚拟时间起始点。"""
        return self._virtualStartDateTime

    def GetVirtualDateTimeValue(self) -> datetime:
        """获取当前虚拟日期时间。"""
        return self._GetVirtualDateTimeAtMonotonicValue(
            float(self._monotonicProvider())
        )

    def GetVirtualTimestampValue(self) -> float:
        """获取当前虚拟 Unix 时间戳。"""
        return self.GetVirtualDateTimeValue().timestamp()

    def GetRealIntervalValue(self, virtualSeconds: float) -> float:
        """把虚拟秒数换算成真实定时器间隔。"""
        interval = float(virtualSeconds)
        if interval <= 0:
            raise ValueError("Virtual interval must be greater than zero")
        return interval / float(self._timeScale)

    def SetTimeScaleValue(self, timeScale: object) -> bool:
        """连续切换到指定整数倍率，不改变当前虚拟时间。"""
        normalizedScale = NormalizeTimeScaleValue(timeScale)
        if normalizedScale == self._timeScale:
            return True

        # 切换前按旧倍率计算当前虚拟时间，再将其设为新倍率的连续锚点。
        monotonicNow = float(self._monotonicProvider())
        currentVirtualTime = self._GetVirtualDateTimeAtMonotonicValue(monotonicNow)
        self._virtualAnchorDateTime = currentVirtualTime
        self._monotonicAnchor = monotonicNow
        self._timeScale = normalizedScale
        self._timeRevision += 1
        return True

    def SetTimeContextValue(self, timeContext: dict[str, object]) -> bool:
        """使用权威时间节点的上下文同步本地虚拟时钟。"""
        if not isinstance(timeContext, dict):
            raise ValueError("timeContext must be an object")

        normalizedScale = NormalizeTimeScaleValue(timeContext.get("scale"))

        startDateTime = self._NormalizeDateTimeValue(
            timeContext.get("virtualStartDateTime"),
            "virtualStartDateTime",
        )
        currentDateTime = self._NormalizeDateTimeValue(
            timeContext.get("virtualDateTime"),
            "virtualDateTime",
        )
        if currentDateTime < startDateTime:
            raise ValueError("virtualDateTime must not precede virtualStartDateTime")

        revision = int(timeContext.get("revision", 0))
        if revision < 0:
            raise ValueError("timeContext revision must be non-negative")

        self._timeScale = normalizedScale
        self._virtualStartDateTime = startDateTime
        self._virtualAnchorDateTime = currentDateTime
        self._monotonicAnchor = float(self._monotonicProvider())
        self._timeRevision = revision
        return True

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
            "mode": TIME_SCALE_MODE_LABELS.get(self._timeScale, "custom"),
            "scale": self._timeScale,
            "revision": self._timeRevision,
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
        return max(
            0.0,
            (
                self.GetVirtualDateTimeValue() - self._virtualStartDateTime
            ).total_seconds(),
        )

    def _GetVirtualDateTimeAtMonotonicValue(self, monotonicValue: float) -> datetime:
        """根据指定单调时钟值计算虚拟时间。"""
        realElapsedSeconds = max(0.0, monotonicValue - self._monotonicAnchor)
        return self._virtualAnchorDateTime + timedelta(
            seconds=realElapsedSeconds * float(self._timeScale)
        )

    def _NormalizeDateTimeValue(self, value: object, fieldName: str) -> datetime:
        """校验并解析带时区的 ISO 8601 时间。"""
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, str):
            try:
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(f"{fieldName} must be ISO 8601 datetime") from error
        else:
            raise ValueError(f"{fieldName} must be ISO 8601 datetime")
        if result.tzinfo is None:
            raise ValueError(f"{fieldName} must include timezone information")
        return result

    def _ResolveVirtualStartDateTimeValue(
        self,
        wallStartDateTime: datetime,
        virtualStartTime: str,
    ) -> datetime:
        """根据倍率和 HH:MM 参数确定虚拟时间起点。"""
        startTime = str(virtualStartTime).strip()
        if startTime == "auto":
            if self._timeScale == 1:
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
        self._startDateTime = startDateTime
        self._intervalSeconds = interval
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

    def AlignToDateTimeValue(
        self,
        currentDateTime: datetime,
        includeCurrent: bool = False,
    ) -> datetime:
        """快速对齐到当前时间附近，避免首次同步回放过多历史 Tick。"""
        elapsedSeconds = max(
            0.0,
            (currentDateTime - self._startDateTime).total_seconds(),
        )
        completedIntervals = int(elapsedSeconds // self._intervalSeconds)
        candidate = self._startDateTime + timedelta(
            seconds=completedIntervals * self._intervalSeconds
        )
        isBoundary = abs((currentDateTime - candidate).total_seconds()) < 1e-6
        if includeCurrent and isBoundary and completedIntervals > 0:
            self._nextTickDateTime = candidate
        else:
            self._nextTickDateTime = candidate + self._interval
        return self._nextTickDateTime


class RealTimeTickScheduler:
    """按单调真实时间计算应补算的固定间隔 Tick 数量。"""

    def __init__(self, startSeconds: float, intervalSeconds: float = 1.0) -> None:
        """从指定单调时间后的第一个间隔开始调度。"""
        start = float(startSeconds)
        interval = float(intervalSeconds)
        if not isfinite(start):
            raise ValueError("Real-time scheduler start must be finite")
        if not isfinite(interval) or interval <= 0:
            raise ValueError(
                "Real-time Tick interval must be finite and greater than zero"
            )
        self._intervalSeconds = interval
        self._nextTickSeconds = start + interval

    def GetDueTickCountValue(self, currentSeconds: float) -> int:
        """获取并消费截至当前单调时间全部到期 Tick。"""
        current = float(currentSeconds)
        if not isfinite(current):
            raise ValueError("Current monotonic time must be finite")

        # 浮点累加可能略小于整数边界，加入极小容差避免漏掉到期 Tick。
        tolerance = min(1e-9, self._intervalSeconds * 1e-9)
        if current + tolerance < self._nextTickSeconds:
            return 0
        dueTickCount = floor(
            (current - self._nextTickSeconds + tolerance) / self._intervalSeconds
        ) + 1
        self._nextTickSeconds += dueTickCount * self._intervalSeconds
        return dueTickCount

    def GetNextTickSecondsValue(self) -> float:
        """获取下一次尚未消费的单调时间 Tick。"""
        return self._nextTickSeconds
