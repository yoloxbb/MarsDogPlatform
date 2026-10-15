"""Behavior trigger ownership, independent of priority and action template.

These are local BT policies derived from the existing source/need_type fields;
they are not new wire fields or permission to bypass arbitration.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class BehaviorDrive(str, Enum):
    PERCEPTION_DIRECT = "perception_direct"
    INTERNAL_STATE = "internal_state"


DIRECT_SOURCES = frozenset({
    "audio_direct", "audio_reaction", "audio_session", "visual_direct",
    "touch_direct",  # Reserved candidate source; no sensor transport is implied.
})
_NEED_TYPES = frozenset({"physiological", "physiological_urgent", "psychological"})


@dataclass(frozen=True)
class DrivePolicy:
    drive: BehaviorDrive | None
    state_domain: str = ""  # emotion / need; empty means no state ownership
    legacy: bool = False


def resolve_drive(params: Mapping | None, need_type: str = "") -> DrivePolicy:
    """Explicit known source owns lifecycle; legacy inputs retain old semantics.

    source_emotion can describe an expression style used by a direct reaction.
    Neither that field, a behavior name nor its priority determines ownership.
    System/idle/unknown inputs are left unclassified unless a legacy need_type
    identifies a state owner; they are not a third business drive category.
    """
    values = params if isinstance(params, Mapping) else {}
    source = values.get("source")
    if isinstance(source, str):
        if source in DIRECT_SOURCES:
            return DrivePolicy(BehaviorDrive.PERCEPTION_DIRECT)
        if source in ("emotion", "need"):
            return DrivePolicy(BehaviorDrive.INTERNAL_STATE, source)
    if need_type == "emotional":
        return DrivePolicy(BehaviorDrive.INTERNAL_STATE, "emotion", legacy=True)
    if need_type in _NEED_TYPES:
        return DrivePolicy(BehaviorDrive.INTERNAL_STATE, "need", legacy=True)
    return DrivePolicy(None)
