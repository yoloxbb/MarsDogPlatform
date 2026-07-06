"""行为组结果事件到需求/情绪核心系统的适配。"""

from __future__ import annotations

import json
from typing import Any


def ApplyBehaviorResultMessage(system: Any, message: object) -> bool:
    """把 `/behavior/result_event` 消息转换为核心结果接口调用。"""
    payload = _NormalizeMessageToDict(message)
    if not payload or not hasattr(system, "OnBehaviorResultEvent"):
        return False
    return bool(system.OnBehaviorResultEvent(payload))


def _NormalizeMessageToDict(message: object) -> dict[str, Any]:
    """把 ROS2 消息、JSON 字符串或 dict 统一转成字典。"""
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
    """读取 JSON 字符串。"""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
