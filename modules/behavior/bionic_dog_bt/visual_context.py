"""Pure visual-context classification for need-driven behaviors.

The ROS2 adapter and standalone mock both use these helpers so Social and
Exploration make identical routing decisions from object-detection results.
"""

from __future__ import annotations

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


def target_from_detection(item: dict, target_type: str) -> dict:
    """Convert one detector item into executor-friendly target metadata."""
    label = normalize_label(item.get("label"))
    target = {
        "target_type": target_type,
        "target_id": str(item.get("track_id", label or "unknown")),
        "label": label,
        "confidence": _confidence(item),
    }
    for key in ("track_id", "x", "y", "w", "h", "center_x", "center_y"):
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
