"""统一虚拟时间状态 Topic 的消息解析。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


TIME_EVENT_TYPES = {
    "TIME_INITIALIZED",
    "TIME_TICK",
    "TIME_MODE_CHANGED",
    "TIME_TEST_STEP",
}


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
