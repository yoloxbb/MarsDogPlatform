"""行为结果事件的统一校验和去重工具。"""

from __future__ import annotations

from typing import Any

from .types import NormalizeActionType, NormalizeDemandType


VALID_BEHAVIOR_RESULT_TYPES = {
    "STARTED",
    "COMPLETED",
    "FAILED",
    "INTERRUPTED",
    "CANCELLED",
    "TIMEOUT",
}

MAX_PROCESSED_BEHAVIOR_RESULT_IDS = 256


def NormalizeBehaviorResultEventValue(
    resultData: dict[str, Any] | None,
    actionDemandMap: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """校验并规范化 `/behavior/result_event` 输入。"""
    if not isinstance(resultData, dict):
        return None

    payload = dict(resultData)
    try:
        action = NormalizeActionType(payload.get("action_type", payload.get("actionType", "")))
    except (TypeError, ValueError):
        return None

    result = str(payload.get("result_type", payload.get("resultType", ""))).upper()
    if result not in VALID_BEHAVIOR_RESULT_TYPES:
        return None

    metadata = payload.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        return None

    expectedDemand = _GetExpectedDemand(action, actionDemandMap)
    if actionDemandMap is not None and expectedDemand is None:
        return None

    demand = _NormalizeOptionalDemand(payload.get("demand_type", payload.get("demandType")))
    if demand is not None and expectedDemand is not None and demand != expectedDemand:
        return None

    return {
        "event_id": _NormalizeOptionalText(payload.get("event_id", payload.get("eventId"))),
        "timestamp": payload.get("timestamp"),
        "action_type": action,
        "demand_type": demand or expectedDemand,
        "result_type": result,
        "metadata": dict(metadata),
    }


def MarkBehaviorResultEventHandledValue(state: object, eventId: str | None) -> bool:
    """记录已处理的 result event id；返回 True 表示重复事件。"""
    if not eventId:
        return False

    handledIds = getattr(state, "processedBehaviorResultEventIds", set())
    handledOrder = getattr(state, "processedBehaviorResultEventIdOrder", [])
    if eventId in handledIds:
        return True

    handledIds.add(eventId)
    handledOrder.append(eventId)

    # 限制内存占用，保留最近一批事件 id 即可。
    while len(handledOrder) > MAX_PROCESSED_BEHAVIOR_RESULT_IDS:
        expiredId = handledOrder.pop(0)
        handledIds.discard(expiredId)

    state.processedBehaviorResultEventIds = handledIds
    state.processedBehaviorResultEventIdOrder = handledOrder
    return False


def _GetExpectedDemand(action: str, actionDemandMap: dict[str, str] | None) -> str | None:
    """根据 action 映射读取期望 demand。"""
    if actionDemandMap is None:
        return None
    demand = actionDemandMap.get(action)
    if demand is None:
        return None
    try:
        return NormalizeDemandType(demand)
    except (TypeError, ValueError):
        return None


def _NormalizeOptionalDemand(value: object) -> str | None:
    """规范化可选 demand_type。"""
    if value is None or value == "":
        return None
    try:
        return NormalizeDemandType(value)
    except (TypeError, ValueError):
        return None


def _NormalizeOptionalText(value: object) -> str | None:
    """规范化可选字符串字段。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
