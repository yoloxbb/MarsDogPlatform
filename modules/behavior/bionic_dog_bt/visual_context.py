"""Pure visual-context classification for need-driven behaviors.

The ROS2 adapter and standalone mock both use these helpers so Social and
Exploration make identical routing decisions from object-detection results.
"""

from __future__ import annotations

import math
from typing import Any


ANIMAL_LABELS = frozenset({"cat", "dog"})

DOG_FOOD_LABELS = frozenset({
    "dog food",
    "dog food can",
    "dog treat bag",
    "dog kibble",
    "pet food",
})

PLAY_ITEM_LABELS = frozenset({
    "ball",
    "red ball",
    "toy",
    "dog toy ball",
    "dog frisbee toy",
    "dog tug ring toy",
    "slipper",
    "sock",
    # These remain familiar dog-owned objects from the previous routing rule.
    "dog collar",
    "dog leash",
    "dog bed",
})

EXPLORATION_ROUTE_LABELS = {
    "play_item": PLAY_ITEM_LABELS,
    "trash_can": frozenset({"trash can", "garbage can"}),
    "delivery_box": frozenset({
        "cardboard shipping box",
        "delivery box",
        "shipping box",
    }),
    "tissue": frozenset({"tissue", "tissue paper"}),
    "door": frozenset({"door"}),
    "dog_food": DOG_FOOD_LABELS | frozenset({"dog bowl"}),
}

FAMILIAR_OBJECT_LABELS = frozenset().union(
    *EXPLORATION_ROUTE_LABELS.values()
)

_EXECUTOR_OBJECT_CATEGORIES = {
    "trash_can": "trash_can",
    "delivery_box": "delivery_box",
    "tissue": "tissue",
    "door": "door",
    "dog_food": "food_bowl",
}


def normalize_label(value: Any) -> str:
    """Normalize detector labels for stable exact matching."""
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _confidence(item: dict) -> float:
    try:
        return float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _best(items: list[dict]) -> dict | None:
    return max(items, key=_confidence, default=None)


def _finite_float(value: Any) -> float | None:
    """Return a finite float, or ``None`` for malformed perception data."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def select_wake_speaker(
    candidates: list[dict],
    *,
    reference_bearing_deg: float = 0.0,
    min_confidence: float = 0.3,
    max_age_ms: float = 300.0,
    max_bearing_error_deg: float = 25.0,
) -> dict | None:
    """Select the human most consistent with the wake-source direction.

    This policy deliberately differs from social targeting.  A registered
    person elsewhere in the image must not displace the person who actually
    called the robot.  Angular agreement is therefore the primary key;
    speaking/detection/identity evidence only breaks progressively closer
    ties.  The returned dictionary is a copy suitable for an immutable
    Action ``target`` reference.
    """
    reference = _finite_float(reference_bearing_deg)
    if reference is None:
        return None

    eligible: list[tuple[tuple, dict]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        target_type = str(raw.get("target_type", "human")).strip().lower()
        if target_type not in ("human", "person"):
            continue
        if str(raw.get("tracking_state", "tracking")).lower() != "tracking":
            continue

        target_id = str(raw.get("target_id", "")).strip()
        vision_epoch = str(raw.get("vision_epoch", "")).strip()
        if not target_id or not vision_epoch:
            continue

        age_ms = _finite_float(raw.get("last_seen_age_ms", 0.0))
        confidence = _finite_float(
            raw.get("detection_confidence", raw.get("confidence", 0.0))
        )
        if (
            age_ms is None
            or not 0.0 <= age_ms <= float(max_age_ms)
            or confidence is None
            or confidence < float(min_confidence)
        ):
            continue

        bearing = _finite_float(raw.get("bearing_deg"))
        if bearing is None:
            center_x = _finite_float(raw.get("center_x"))
            if center_x is None:
                center = raw.get("center")
                if isinstance(center, (list, tuple)) and center:
                    center_x = _finite_float(center[0])
            if center_x is None or not 0.0 <= center_x <= 1.0:
                continue
            # Only a ranking proxy when calibrated intrinsics are unavailable.
            bearing = (center_x - 0.5) * 90.0

        identity_confidence = _finite_float(
            raw.get("identity_confidence", 0.0)
        ) or 0.0
        speaking_confidence = _finite_float(
            raw.get("speaking_confidence", 1.0 if raw.get("is_speaking") else 0.0)
        ) or 0.0
        angular_error = abs((bearing - reference + 180.0) % 360.0 - 180.0)
        if angular_error > float(max_bearing_error_deg):
            continue
        selected = dict(raw)
        selected["target_type"] = "human"
        selected["target_id"] = target_id
        selected["vision_epoch"] = vision_epoch
        selected["detection_confidence"] = confidence
        selected["selection_reason"] = "wake_bearing_first"
        selected["wake_bearing_error_deg"] = angular_error
        eligible.append((
            (
                angular_error,
                -speaking_confidence,
                -confidence,
                -identity_confidence,
                target_id,
            ),
            selected,
        ))

    return min(eligible, key=lambda item: item[0])[1] if eligible else None


def target_from_detection(item: dict, target_type: str) -> dict:
    """Convert one detector item into executor-friendly target metadata."""
    label = normalize_label(item.get("label"))
    stable_target_id = (
        item.get("target_id")
        or item.get("track_id")
        or label
        or "unknown"
    )
    target = {
        "target_type": target_type,
        "target_id": str(stable_target_id),
        "label": label,
        "confidence": _confidence(item),
    }
    for key in (
        "vision_epoch",
        "track_id",
        "x",
        "y",
        "w",
        "h",
        "center_x",
        "center_y",
    ):
        if key in item:
            target[key] = item[key]
    if target_type == "animal":
        target["species"] = label
    return target


def select_social_animal(objects: list[dict]) -> dict | None:
    """Return the highest-confidence visible cat/dog as an interaction target."""
    animals = [
        item
        for item in objects
        if isinstance(item, dict)
        and normalize_label(item.get("label")) in ANIMAL_LABELS
    ]
    selected = _best(animals)
    return (
        target_from_detection(selected, "animal")
        if selected is not None
        else None
    )


def select_hunger_context(objects: list[dict]) -> dict:
    """Route Hunger by whether a dog-food resource is visible."""
    food = [
        item
        for item in objects
        if isinstance(item, dict)
        and normalize_label(item.get("label")) in DOG_FOOD_LABELS
    ]
    selected = _best(food)
    if selected is None:
        return {"route": "no_dog_food", "target": None}

    target = target_from_detection(selected, "object")
    target["object_category"] = "food_bowl"
    return {"route": "dog_food", "target": target}


def _exploration_route(label: str) -> str | None:
    for route, labels in EXPLORATION_ROUTE_LABELS.items():
        if label in labels:
            return route
    return None


def _object_category(route: str, label: str) -> str:
    if route == "play_item":
        return (
            "slippers_socks"
            if label in {"slipper", "sock"}
            else "toy"
        )
    return _EXECUTOR_OBJECT_CATEGORIES.get(route, "generic")


def select_exploration_context(objects: list[dict]) -> dict:
    """Classify exploration into six familiar routes, unfamiliar, or empty."""
    detected = [
        item
        for item in objects
        if isinstance(item, dict)
        and normalize_label(item.get("label"))
        not in ANIMAL_LABELS | {"person", "human"}
    ]
    familiar = [
        (item, _exploration_route(normalize_label(item.get("label"))))
        for item in detected
        if _exploration_route(normalize_label(item.get("label"))) is not None
    ]
    selected_pair = max(
        familiar,
        key=lambda pair: _confidence(pair[0]),
        default=None,
    )
    if selected_pair is not None:
        selected, route = selected_pair
        label = normalize_label(selected.get("label"))
        target = target_from_detection(selected, "object")
        target["object_category"] = _object_category(route, label)
        return {
            "route": route,
            "target": target,
        }

    selected = _best(detected)
    if selected is not None:
        return {
            "route": "unfamiliar_object",
            "target": target_from_detection(selected, "object"),
        }

    return {"route": "empty", "target": None}
