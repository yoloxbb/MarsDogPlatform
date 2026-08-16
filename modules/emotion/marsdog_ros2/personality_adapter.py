"""性格状态 topic 到核心系统的轻量适配。"""

from __future__ import annotations

from typing import Any

from marsdog_ros2.common.json_message import NormalizeJsonMessageValue


def ApplyPersonalityStateMessage(system: Any, message: object) -> bool:
    """把 `/personality/state` 消息同步到核心系统。"""
    payload = NormalizeJsonMessageValue(message)
    if not payload or not hasattr(system, "SetPersonalityStateValue"):
        return False
    return bool(system.SetPersonalityStateValue(payload))
