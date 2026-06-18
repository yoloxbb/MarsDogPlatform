"""规则判断工具。"""

from __future__ import annotations

from typing import Any


def IsConditionMatched(value: float, operator: str, threshold: float) -> bool:
    """判断数值是否满足配置中的比较条件。"""
    if operator == "gt":
        return value > threshold
    if operator == "gte":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    if operator == "eq":
        return value == threshold
    raise ValueError(f"Unsupported operator: {operator}")


def GetMetadataNumber(metadata: dict[str, Any], key: str, default: float = 0.0) -> float:
    """从事件元数据中读取数值字段。"""
    value = metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
