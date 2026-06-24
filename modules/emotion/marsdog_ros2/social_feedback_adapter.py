"""社交互动回应消息到核心状态机的适配。"""

from __future__ import annotations

import json
from typing import Any


def ApplySocialFeedbackMessage(system: Any, message: object) -> bool:
    """把社交回应 JSON 转换为核心互动反馈接口调用。"""
    payload = _NormalizeMessageToDict(message)
    if not payload:
        return False

    interactionId = payload.get("interactionId", payload.get("interaction_id", ""))
    targetType = payload.get("targetType", payload.get("target_type", ""))
    responseType = payload.get("responseType", payload.get("response_type", ""))
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return system.OnSocialInteractionFeedback(
        interactionId,
        responseType,
        targetType,
        metadata,
    )


def _NormalizeMessageToDict(message: object) -> dict[str, Any]:
    """把 ROS2 String、JSON 字符串或字典统一转换为字典。"""
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
