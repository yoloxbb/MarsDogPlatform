"""统一虚拟时间状态 Topic 的消息解析。"""

from __future__ import annotations

import json
from datetime import datetime
from math import isfinite
from typing import Any


TIME_EVENT_TYPES = {
    "TIME_INITIALIZED",
    "TIME_TICK",
    "TIME_MODE_CHANGED",
    "TIME_TEST_STEP",
    "TIME_ACCELERATION_CHANGED",
    "TIME_ACCELERATED_STEP",
}
DEFAULT_DEMAND_TICK_SECONDS = 10 * 60


def GetTimeStateMessageValue(message: object) -> dict[str, Any]:
    """解析并校验 `/simulation/time_state` 消息。"""
    payload = _NormalizeMessageToDict(message)
    if not payload or payload.get("event_type") not in TIME_EVENT_TYPES:
        return {}
    if not isinstance(payload.get("timeContext"), dict):
        return {}
    return payload


def GetTimeContextDateTimeValue(
    payload: dict[str, Any],
    fieldName: str,
) -> datetime | None:
    """从时间状态消息读取带时区的 ISO 8601 时间。"""
    timeContext = payload.get("timeContext", {})
    value = timeContext.get(fieldName) if isinstance(timeContext, dict) else None
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None else None


def GetEnergyElapsedSecondsPerDemandTickValue(
    payload: dict[str, Any],
) -> float:
    """读取每个需求 Tick 应计入电池衰减的秒数。"""
    eventType = str(payload.get("event_type", ""))
    if eventType == "TIME_ACCELERATED_STEP":
        timeContext = payload.get("timeContext", {})
        acceleration = (
            timeContext.get("midnightAcceleration", {})
            if isinstance(timeContext, dict)
            else {}
        )
        return _GetRealSecondsPerStepValue(acceleration)
    if eventType == "TIME_TEST_STEP":
        return _GetRealSecondsPerStepValue(payload.get("testScenario", {}))
    return float(DEFAULT_DEMAND_TICK_SECONDS)


def _GetRealSecondsPerStepValue(metadata: object) -> float:
    """把凌晨加速的总真实时长平均分配到每个离散步骤。"""
    if not isinstance(metadata, dict):
        return 0.0
    durationValue = metadata.get(
        "durationSeconds",
        metadata.get("scenarioDurationSeconds"),
    )
    stepCountValue = metadata.get("stepCount")
    if isinstance(durationValue, bool) or isinstance(stepCountValue, bool):
        return 0.0
    try:
        durationSeconds = float(durationValue)
        stepCountNumber = float(stepCountValue)
    except (TypeError, ValueError):
        return 0.0
    if (
        not isfinite(durationSeconds)
        or not isfinite(stepCountNumber)
        or durationSeconds <= 0
        or stepCountNumber <= 0
        or not stepCountNumber.is_integer()
    ):
        return 0.0
    stepCount = int(stepCountNumber)
    # 凌晨特殊加速只按真实经过时间以1倍耗电，不按六小时虚拟跳时耗电。
    return durationSeconds / stepCount


def _NormalizeMessageToDict(message: object) -> dict[str, Any]:
    """把 ROS2 String、JSON 字符串或 dict 转换为字典。"""
    if message is None:
        return {}
    if isinstance(message, dict):
        return dict(message)
    if isinstance(message, str):
        return _LoadJsonDict(message)
    if hasattr(message, "data"):
        return _NormalizeMessageToDict(getattr(message, "data"))
    return {}


def _LoadJsonDict(text: str) -> dict[str, Any]:
    """解析 JSON 对象，非法内容返回空字典。"""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
