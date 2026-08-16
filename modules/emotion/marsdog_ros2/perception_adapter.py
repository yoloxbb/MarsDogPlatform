"""新版感知 topic 到需求/情绪系统的轻量适配。"""

from __future__ import annotations

from typing import Any

from marsdog_ros2.common.json_message import NormalizeJsonMessageValue


def ApplyVisualEventMessage(system: Any, message: object) -> list[str]:
    """把 `/perception/visual_event` 消息转发给核心系统。"""
    payload = NormalizeJsonMessageValue(message)
    if not payload or not hasattr(system, "OnVisualEvent"):
        return []
    return list(system.OnVisualEvent(payload) or [])


def ApplyAudioEventMessage(system: Any, message: object) -> list[str]:
    """把 `/perception/audio_event` 消息转发给核心系统。"""
    payload = NormalizeJsonMessageValue(message)
    if not payload or not hasattr(system, "OnAudioEvent"):
        return []
    return list(system.OnAudioEvent(payload) or [])


def ApplyTactileEventMessage(system: Any, message: object) -> list[str]:
    """把 `/perception/tactile_event` 消息转发给核心系统。"""
    payload = NormalizeJsonMessageValue(message)
    if not payload or not hasattr(system, "OnTactileEvent"):
        return []
    return list(system.OnTactileEvent(payload) or [])
