"""性格状态 topic 到核心系统的轻量适配。"""

from __future__ import annotations

import json
from typing import Any


def ApplyPersonalityStateMessage(system: Any, message: object) -> bool:
    """把 `/personality/state` 消息同步到核心系统。"""
    payload = _NormalizeMessageToDict(message)
    if not payload or not hasattr(system, "SetPersonalityStateValue"):
        return False
    return bool(system.SetPersonalityStateValue(payload))


def _NormalizeMessageToDict(message: object) -> dict[str, Any]:
    """把 ROS2 String、JSON 字符串或 dict 统一转换为字典。"""
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
    """解析 JSON 字符串，非法输入返回空字典。"""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
