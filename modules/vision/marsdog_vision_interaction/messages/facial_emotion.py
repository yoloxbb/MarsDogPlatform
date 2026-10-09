"""Validated human facial expression projection (not robot emotion state)."""

from __future__ import annotations

import math
from numbers import Real
from typing import Any

EMOTIONS = ("angry", "contempt", "disgust", "fear", "happy", "neutral", "sad", "surprise")


def normalize_facial_emotion(value: Any) -> dict[str, Any] | None:
    """Return only a canonical category and finite original confidence."""
    if not isinstance(value, dict) or value.get("emotion") not in EMOTIONS:
        return None
    intensity = value.get("intensity")
    if isinstance(intensity, bool) or not isinstance(intensity, Real):
        return None
    probability = float(intensity)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        return None
    return {"emotion": value["emotion"], "intensity": probability}


def expire_facial_emotions(event: dict[str, Any], elapsed_sec: float) -> None:
    """Age optional expression metadata in a cached debug-event copy."""
    if "facial_emotion_valid_for_sec" not in event:
        return
    lifetime = event["facial_emotion_valid_for_sec"]
    if isinstance(lifetime, bool) or not isinstance(lifetime, Real) or not math.isfinite(float(lifetime)):
        remaining = 0.0
    else:
        remaining = float(lifetime) - max(0.0, elapsed_sec)
    if remaining > 0:
        event["facial_emotion_valid_for_sec"] = remaining
        return
    event.pop("facial_emotion_valid_for_sec", None)
    for key in ("faces", "debug_faces"):
        for face in event.get(key, []):
            if isinstance(face, dict):
                face.pop("facial_emotion", None)


class FacialEmotionExpiry:
    """Keep the earliest debug deadline for repeated source-frame packets.

    Sequences identify publications, not new image evidence. Transport delay
    is not measured here; remaining lifetime is aged from local receipt.
    """

    def __init__(self) -> None:
        self._source: tuple[str, str, str] | None = None
        self._deadline = 0.0

    def apply(self, event: dict[str, Any], now: float) -> None:
        expire_facial_emotions(event, 0.0)
        lifetime = event.get("facial_emotion_valid_for_sec")
        if lifetime is None:
            return
        header = event.get("header", {})
        if not isinstance(header, dict):
            header = {}
        source = (str(event.get("vision_epoch", "")), str(header.get("stamp", "")),
                  str(header.get("frame_id", "")))
        deadline = now + float(lifetime)
        if source == self._source:
            deadline = min(deadline, self._deadline)
        self._source, self._deadline = source, deadline
        event["facial_emotion_valid_for_sec"] = max(0.0, deadline - now)
        expire_facial_emotions(event, 0.0)
