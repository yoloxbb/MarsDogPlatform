"""感知理解层 ROS2 消息到核心行为事件的适配。"""

from __future__ import annotations

import json
from typing import Any


def ApplyObservationMessage(system: Any, message: object) -> list[str]:
    """把 `/perception/observation` 消息转换为核心事件。"""
    payload = _NormalizeMessageToDict(message)
    if not payload:
        return []

    emittedEvents: list[str] = []
    faces = _GetList(payload, "faces")
    humans = _GetList(payload, "humans")
    trackedObjects = _GetList(payload, "tracked_objects")
    animalObjects = [item for item in trackedObjects if _IsAnimalObject(item)]
    otherObjects = [item for item in trackedObjects if not _IsAnimalObject(item)]

    humanVisible = bool(faces or humans)
    animalVisible = bool(animalObjects)
    if hasattr(system, "SetSocialTargetVisibility"):
        system.SetSocialTargetVisibility(humanVisible, animalVisible)

    if humanVisible:
        emittedEvents.append("HumanVisible")

    if animalObjects:
        confidence = _MaxConfidence(animalObjects)
        metadata = {
            "animalCount": len(animalObjects),
            "animals": animalObjects,
            "confidence": confidence,
            "value": _ConfidenceToScore(confidence),
        }
        system.PostEvent("AnimalApproach", metadata)
        emittedEvents.append("AnimalApproach")

    if otherObjects:
        targetObject = max(
            otherObjects,
            key=lambda item: _GetFloat(item, "confidence", 0.0),
        )
        confidence = _GetFloat(targetObject, "confidence", 0.0)
        metadata = {
            "objectCount": len(otherObjects),
            "objects": otherObjects,
            "targetObject": targetObject,
            "confidence": confidence,
            "value": _ConfidenceToScore(confidence),
        }
        if hasattr(system, "OnExplorationTargetDetected"):
            accepted = system.OnExplorationTargetDetected(
                _GetExplorationTargetType(targetObject),
                _GetExplorationTargetId(targetObject),
                _GetExplorationDiscoveryType(targetObject),
                metadata,
            )
            if accepted:
                eventTag = (
                    "OldObject"
                    if system.state.explorationPendingDiscoveryType == "Old"
                    else "NewObject"
                )
                emittedEvents.append(eventTag)
        else:
            system.OnVisionInput("NewObject", metadata)
            emittedEvents.append("NewObject")

    return emittedEvents


def ApplyInteractionEventMessage(system: Any, message: object) -> list[str]:
    """把 `/perception/interaction_event` 消息转换为核心事件。"""
    payload = _NormalizeMessageToDict(message)
    if not payload:
        return []

    eventType = str(payload.get("event_type", "")).lower()
    if eventType == "wakeup":
        return _ApplyWakeupEvent(system, payload)
    if eventType == "speech":
        return _ApplySpeechEvent(system, payload)
    if eventType == "intent":
        return _ApplyIntentEvent(system, payload)
    if eventType == "danger":
        return _ApplyDangerEvent(system, payload)
    if eventType == "state":
        return _ApplyStateEvent(system, payload)
    return _PostRawEvent(system, "PerceptionEvent", payload)


def _ApplyWakeupEvent(system: Any, payload: dict[str, Any]) -> list[str]:
    """处理唤醒事件。"""
    confidence = _GetFloat(payload, "wake_confidence", 1.0)
    metadata = dict(payload)
    metadata["direction"] = str(payload.get("wake_angle", "unknown"))
    metadata["confidence"] = confidence
    if hasattr(system, "OnOwnerInteractionEvent"):
        return ["OwnerCall"] if system.OnOwnerInteractionEvent(metadata) else []
    system.PostEvent("OwnerCall", metadata)
    return ["OwnerCall"]


def _ApplySpeechEvent(system: Any, payload: dict[str, Any]) -> list[str]:
    """处理语音识别事件。"""
    metadata = dict(payload)
    metadata["value"] = _ConfidenceToScore(_GetFloat(payload, "speaker_confidence", 0.0))
    system.PostEvent("VoiceInput", metadata)
    emittedEvents = ["VoiceInput"]
    if hasattr(system, "OnOwnerInteractionEvent") and system.OnOwnerInteractionEvent(metadata):
        emittedEvents.append("OwnerCall")
    return emittedEvents


def _ApplyIntentEvent(system: Any, payload: dict[str, Any]) -> list[str]:
    """处理意图事件。"""
    commandId = str(payload.get("command_id", "")).strip()
    metadata = dict(payload)
    if _IsOwnerInteractionCommand(commandId, payload):
        if hasattr(system, "OnOwnerInteractionEvent"):
            return ["OwnerCall"] if system.OnOwnerInteractionEvent(metadata) else []
        system.PostEvent("OwnerCall", metadata)
        return ["OwnerCall"]
    system.PostEvent("Intent", metadata)
    return ["Intent"]


def _ApplyDangerEvent(system: Any, payload: dict[str, Any]) -> list[str]:
    """处理危险事件。"""
    dangerType = str(payload.get("danger_type", "")).lower()
    if dangerType in {"pain", "hit", "collision", "impact"}:
        eventTag = "Pain"
    elif dangerType in {"weightlessness", "free_fall", "falling", "失重"}:
        eventTag = "Weightlessness"
    else:
        eventTag = "Danger"

    metadata = dict(payload)
    metadata["value"] = _GetFloat(payload, "danger_value", 100.0)
    metadata["direction"] = payload.get("danger_angle", "unknown")
    system.PostEvent(eventTag, metadata)
    return [eventTag]


def _ApplyStateEvent(system: Any, payload: dict[str, Any]) -> list[str]:
    """处理感知状态事件。"""
    state = str(payload.get("state", "")).lower()
    if state in {"lights_off", "light_off", "dark", "关灯"} and hasattr(system, "SetLightsOffValue"):
        system.SetLightsOffValue(True)
        if hasattr(system, "UpdateSleepinessByTime"):
            system.UpdateSleepinessByTime()
    elif state in {"lights_on", "light_on", "bright", "开灯"} and hasattr(system, "SetLightsOffValue"):
        system.SetLightsOffValue(False)
    elif state in {"owner_left_home", "owner_away", "主人离家"} and hasattr(system, "OnOwnerPresenceChanged"):
        system.OnOwnerPresenceChanged(False)
    elif state in {"owner_at_home", "owner_home", "主人在家"} and hasattr(system, "OnOwnerPresenceChanged"):
        system.OnOwnerPresenceChanged(True)

    system.PostEvent("StateChange", dict(payload))
    return ["StateChange"]


def _PostRawEvent(system: Any, eventTag: str, payload: dict[str, Any]) -> list[str]:
    """提交未细分的感知事件。"""
    system.PostEvent(eventTag, dict(payload))
    return [eventTag]


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
    return _ObjectToDict(message)


def _LoadJsonDict(text: str) -> dict[str, Any]:
    """读取 JSON 字符串。"""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ObjectToDict(value: object) -> dict[str, Any]:
    """把简单 ROS2 对象转换为字典。"""
    result: dict[str, Any] = {}
    for key in dir(value):
        if key.startswith("_"):
            continue
        item = getattr(value, key)
        if callable(item):
            continue
        result[key] = _NormalizeValue(item)
    return result


def _NormalizeValue(value: Any) -> Any:
    """递归转换 ROS2 子对象。"""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_NormalizeValue(item) for item in value]
    if isinstance(value, tuple):
        return [_NormalizeValue(item) for item in value]
    if isinstance(value, dict):
        return {key: _NormalizeValue(item) for key, item in value.items()}
    return _ObjectToDict(value)


def _GetList(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """读取列表字段。"""
    value = payload.get(key, [])
    if not isinstance(value, list):
        return []
    return [item if isinstance(item, dict) else _ObjectToDict(item) for item in value]


def _MaxConfidence(items: list[dict[str, Any]]) -> float:
    """获取对象列表中的最高置信度。"""
    if not items:
        return 0.0
    return max(_GetFloat(item, "confidence", 0.0) for item in items)


def _ConfidenceToScore(confidence: float) -> float:
    """把 0-1 置信度转换为 0-100 分值。"""
    return confidence * 100.0 if 0.0 <= confidence <= 1.0 else confidence


def _IsAnimalObject(item: dict[str, Any]) -> bool:
    """判断跟踪物体是否属于可社交动物。"""
    label = str(item.get("label", "")).strip().lower()
    return label in {"dog", "cat", "animal", "狗", "猫", "动物"}


def _GetExplorationTargetType(item: dict[str, Any]) -> str:
    """把感知标签映射到探索动作池目标类型。"""
    label = str(item.get("label", "")).strip().lower()
    if label in {"slipper", "slippers", "sock", "socks", "拖鞋", "袜子"}:
        return "SlippersOrSocks"
    if label in {"trash_can", "trashcan", "garbage_can", "垃圾桶"}:
        return "TrashCan"
    if label in {"delivery_box", "parcel", "package", "快递盒", "快递箱"}:
        return "DeliveryBox"
    if label in {"tissue", "paper_tissue", "纸巾"}:
        return "Tissue"
    if label in {"door", "门"}:
        return "Door"
    if label in {"person", "human", "人"}:
        return "Human"
    if label in {"map", "地图"}:
        return "Map"
    return "GenericObject"


def _GetExplorationTargetId(item: dict[str, Any]) -> str:
    """获取用于新旧目标去重的稳定标识。"""
    for key in ("tracking_id", "track_id", "id", "object_id"):
        value = item.get(key)
        if value not in {None, ""}:
            return str(value)
    return str(item.get("label", "GenericObject"))


def _GetExplorationDiscoveryType(item: dict[str, Any]) -> str | None:
    """读取感知层显式提供的新旧目标标记。"""
    value = item.get("discovery_type", item.get("novelty"))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"new", "新", "新事物"}:
            return "New"
        if normalized in {"old", "known", "旧", "旧事物", "已知"}:
            return "Old"
    if "is_new" in item:
        return "New" if bool(item["is_new"]) else "Old"
    return None


def _GetFloat(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    """从字典里读取浮点值。"""
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def _IsOwnerInteractionCommand(commandId: str, payload: dict[str, Any]) -> bool:
    """判断意图是否属于主人交互类命令。"""
    intentCategory = str(payload.get("intent_category", "")).lower()
    normalizedCommand = commandId.upper()
    if intentCategory in {"social", "interaction", "owner_interaction"}:
        return True
    return normalizedCommand in {
        "CMD_COME",
        "CMD_FOLLOW_OWNER",
        "CMD_PLAY",
        "CMD_GREETING",
        "CMD_CALL_DOG",
    }
