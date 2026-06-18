"""外部传感输入接口实现。"""

from __future__ import annotations

from typing import Any


class SensorInputAPI:
    """外部传感输入 API 混入类。"""

    def OnVoiceInput(self, soundType: str, direction: str, confidence: float) -> None:
        """声音输入事件回调。"""
        eventTag = "OwnerCall" if str(soundType) in {"OwnerCall", "Call", "HumanVoice"} else "VoiceInput"
        self.PostEvent(
            eventTag,
            {"soundType": soundType, "direction": direction, "confidence": confidence},
        )

    def OnVisionInput(self, visionType: str, metadata: dict[str, Any] | None = None) -> None:
        """视觉输入事件回调。"""
        visionMetadata = dict(metadata or {})
        if str(visionType) in {"Owner", "Human", "Person", "HumanApproach"}:
            eventTag = "HumanApproach"
        elif str(visionType) in {"NewObject", "Object"}:
            eventTag = "NewObject"
        else:
            eventTag = "VisionInput"
        visionMetadata["visionType"] = visionType
        self.PostEvent(eventTag, visionMetadata)

    def OnTouchInput(self, touchType: str, position: str, pressure: float) -> None:
        """触觉输入事件回调。"""
        eventTag = "Pain" if float(pressure) >= 80 else "TouchInput"
        self.PostEvent(
            eventTag,
            {"touchType": touchType, "position": position, "pressure": pressure},
        )

    def OnEnvironmentChange(self, contextType: str, value: float) -> None:
        """环境变化事件回调。"""
        eventTag = "Danger" if float(value) > 60 else "EnvironmentChange"
        self.PostEvent(eventTag, {"contextType": contextType, "value": value})
