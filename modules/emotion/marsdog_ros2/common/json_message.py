"""ROS2 JSON 消息的统一解析工具。"""

from __future__ import annotations

import json
from typing import Any


def NormalizeJsonMessageValue(message: object) -> dict[str, Any]:
    """把 ROS2 String、JSON 字符串或字典统一转换为新字典。"""
    if message is None:
        return {}
    if isinstance(message, dict):
        return dict(message)
    if isinstance(message, str):
        return LoadJsonObjectValue(message)
    if hasattr(message, "data"):
        return NormalizeJsonMessageValue(getattr(message, "data"))
    return {}


def LoadJsonObjectValue(text: str) -> dict[str, Any]:
    """解析 JSON 对象字符串，非法内容或非对象结果返回空字典。"""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
