"""新版感知 topic 到需求/情绪系统的轻量适配。"""

from __future__ import annotations

import json
from typing import Any


def ApplyVisualEventMessage(system: Any, message: object) -> list[str]:
    """把 `/perception/visual_event` 消息转发给核心系统。"""
    payload = _NormalizeMessageToDict(message)
    if not payload or not hasattr(system, "OnVisualEvent"):
        return []
    return list(system.OnVisualEvent(payload) or [])


def ApplyAudioEventMessage(system: Any, message: object) -> list[str]:
    """把 `/perception/audio_event` 消息转发给核心系统。"""
    payload = _NormalizeMessageToDict(message)
    if not payload or not hasattr(system, "OnAudioEvent"):
        return []
    return list(system.OnAudioEvent(payload) or [])


def ApplyTactileEventMessage(system: Any, message: object) -> list[str]:
    """把 `/perception/tactile_event` 消息转发给核心系统。"""
    payload = _NormalizeMessageToDict(message)
    if not payload or not hasattr(system, "OnTactileEvent"):
        return []
    return list(system.OnTactileEvent(payload) or [])


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
