"""动作执行反馈消息到核心行为系统的适配。"""

from __future__ import annotations

import json
from typing import Any


def ApplyActionFeedbackMessage(system: Any, message: object) -> bool:
    """把动作执行层反馈消息转换为核心反馈接口调用。"""
    payload = _NormalizeMessageToDict(message)
    if not payload:
        return False

    commandId = payload.get("commandId", payload.get("command_id", ""))
    actionName = payload.get("actionName", payload.get("action_name", payload.get("concreteAction", "")))
    status = payload.get("status", "")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    return system.OnActionFeedback(commandId, actionName, status, metadata)


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
