"""行为组结果事件到需求/情绪核心系统的适配。"""

from __future__ import annotations

from typing import Any

from marsdog_ros2.common.json_message import NormalizeJsonMessageValue


def ApplyBehaviorResultMessage(system: Any, message: object) -> bool:
    """把 `/behavior/result_event` 消息转换为核心结果接口调用。"""
    payload = NormalizeJsonMessageValue(message)
    if not payload or not hasattr(system, "OnBehaviorResultEvent"):
        return False
    return bool(system.OnBehaviorResultEvent(payload))
