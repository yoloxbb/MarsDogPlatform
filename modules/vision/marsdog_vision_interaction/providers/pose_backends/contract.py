"""Public pose keypoint format names and stable index maps."""

from __future__ import annotations

from typing import Mapping

MEDIAPIPE_33 = "mediapipe_33"
COCO_17 = "coco_17"

COCO_TO_MEDIAPIPE = {
    0: 0,
    1: 2,
    2: 5,
    3: 7,
    4: 8,
    5: 11,
    6: 12,
    7: 13,
    8: 14,
    9: 15,
    10: 16,
    11: 23,
    12: 24,
    13: 25,
    14: 26,
    15: 27,
    16: 28,
}

KEYPOINT_INDEX_MAP: Mapping[str, Mapping[str, tuple[int, ...]]] = {
    MEDIAPIPE_33: {
        "wrist": (15, 16),
        "torso": (11, 12, 23, 24),
    },
    COCO_17: {
        "wrist": (9, 10),
        "torso": (5, 6, 11, 12),
    },
}


def normalize_keypoint_format(value: object, *, missing_is_legacy: bool = True) -> str:
    """Validate a public format field, preserving old records without it."""

    if value is None and missing_is_legacy:
        return MEDIAPIPE_33
    normalized = str(value).strip().lower()
    if normalized not in KEYPOINT_INDEX_MAP:
        raise ValueError(f"unsupported keypoint_format {value!r}")
    return normalized


def keypoint_ids(value: object, group: str) -> tuple[int, ...]:
    fmt = normalize_keypoint_format(value)
    try:
        return KEYPOINT_INDEX_MAP[fmt][group]
    except KeyError as exc:
        raise ValueError(f"unsupported pose keypoint group {group!r}") from exc
