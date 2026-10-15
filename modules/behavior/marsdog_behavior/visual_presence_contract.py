"""Behavior-side qualification for v1 visual presence state events."""

OWNER_PRESENCE_EVENT = "EVT_VISION_MASTER"
OWNER_BEND_SQUAT_EVENT = "EVT_VISION_OWNER_BEND_SQUAT"
OWNER_RECALL_GESTURE_EVENT = "EVT_VISION_OWNER_RECALL_GESTURE"
FAMILY_MEMBER_EVENT = "EVT_VISION_FAMILY_MEMBER"
STRANGER_PRESENCE_EVENT = "EVT_VISION_STRANGER"
TOY_FOUND_EVENT = "EVT_VISION_TOY"

# The toy event is a scene-level object state.  Keep it outside the human
# presence qualifiers below: object candidates have no identity gate.
SUPPORTED_TOY_LABELS = frozenset({
    "dog toy ball",
    "dog frisbee toy",
    "dog tug ring toy",
})
VISUAL_OBJECT_EVENT_NAMES = frozenset({TOY_FOUND_EVENT})
VISUAL_OBJECT_TARGET_MAX_AGE_MS = 500.0


def supported_toy_target_age_ms(candidate: dict, vision_epoch: str) -> float | None:
    """Return source age for a current tracked toy row, or ``None``.

    Object IDs are Vision tracking references.  This validates their public
    provenance and freshness without applying human identity rules or
    estimating range from a two-dimensional box.
    """
    if not isinstance(candidate, dict) or not isinstance(vision_epoch, str):
        return None
    epoch = vision_epoch.strip()
    label = candidate.get("label")
    target_id = candidate.get("target_id")
    track_id = candidate.get("track_id")
    if (
        not epoch
        or not isinstance(label, str)
        or " ".join(label.casefold().split()) not in SUPPORTED_TOY_LABELS
        or str(candidate.get("target_type", "")) != "object"
        or str(candidate.get("tracking_state", "")) != "tracking"
        or str(candidate.get("vision_epoch", "")).strip() != epoch
        or not isinstance(target_id, str)
        or not target_id.strip()
        or isinstance(track_id, bool)
        or not isinstance(track_id, int)
        or track_id <= 0
        or target_id.strip() != f"{epoch}:object:{track_id}"
    ):
        return None
    object_track_id = candidate.get("object_track_id")
    if object_track_id is not None and (
        isinstance(object_track_id, bool)
        or not isinstance(object_track_id, int)
        or object_track_id != track_id
    ):
        return None

    source_snapshot_id = candidate.get("source_snapshot_id")
    source_sequence = candidate.get("source_sequence")
    if source_snapshot_id is not None or source_sequence is not None:
        if (
            not isinstance(source_snapshot_id, str)
            or source_snapshot_id.strip()
            != f"{epoch}:object-result:{source_sequence}"
            or isinstance(source_sequence, bool)
            or not isinstance(source_sequence, int)
            or source_sequence <= 0
        ):
            return None
    try:
        age_ms = float(candidate.get("last_seen_age_ms"))
    except (TypeError, ValueError):
        return None
    if age_ms != age_ms or age_ms in (float("inf"), float("-inf")):
        return None
    if not 0.0 <= age_ms < VISUAL_OBJECT_TARGET_MAX_AGE_MS:
        return None
    return age_ms


def resolve_toy_event_target(data: dict, event_type: str) -> tuple[dict | None, str]:
    """Bind one active toy cycle to one deterministic same-payload toy row."""
    if (
        event_type not in VISUAL_OBJECT_EVENT_NAMES
        or not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
        or not isinstance(data.get("events"), list)
        or event_type not in data["events"]
    ):
        return None, ""
    epoch = data.get("vision_epoch")
    snapshot_id = data.get("snapshot_id")
    sequence = data.get("sequence")
    if (
        not isinstance(epoch, str) or not epoch.strip()
        or not isinstance(snapshot_id, str) or not snapshot_id.strip()
        or isinstance(sequence, bool) or not isinstance(sequence, int)
        or sequence <= 0
    ):
        return None, ""
    instances = data.get("event_instances")
    instance = instances.get(event_type) if isinstance(instances, dict) else None
    raw_event_id = instance.get("event_id") if isinstance(instance, dict) else None
    event_id = raw_event_id.strip() if isinstance(raw_event_id, str) else ""
    raw_objects = data.get("tracked_objects")
    if not event_id or not isinstance(raw_objects, list):
        return None, ""

    by_target_id: dict[str, tuple[dict, float, float]] = {}
    for candidate in raw_objects:
        age_ms = supported_toy_target_age_ms(candidate, epoch)
        if age_ms is None:
            continue
        raw_confidence = candidate.get(
            "detection_confidence", candidate.get("confidence", 0.0)
        )
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence != confidence or confidence in (float("inf"), float("-inf")):
            confidence = 0.0
        target_id = str(candidate["target_id"])
        prior = by_target_id.get(target_id)
        if prior is None or (age_ms, -confidence) < (prior[1], -prior[2]):
            by_target_id[target_id] = (candidate, age_ms, confidence)
    qualified = list(by_target_id.values())
    if not qualified:
        return None, ""
    qualified.sort(key=lambda item: (
        -item[2],
        " ".join(item[0]["label"].casefold().split()),
        str(item[0]["target_id"]),
        int(item[0]["track_id"]),
    ))
    target, age_ms, _ = qualified[0]
    result = dict(target)
    result.update({
        "last_seen_age_ms": age_ms,
        "snapshot_id": snapshot_id.strip(),
        "snapshot_sequence": sequence,
    })
    return result, event_id

VISUAL_PRESENCE_EVENT_QUALIFIERS = {
    OWNER_PRESENCE_EVENT: (frozenset({"owner"}), "confirmed_known"),
    OWNER_BEND_SQUAT_EVENT: (frozenset({"owner"}), "confirmed_known"),
    OWNER_RECALL_GESTURE_EVENT: (frozenset({"owner"}), "confirmed_known"),
    FAMILY_MEMBER_EVENT: (
        frozenset({
            "family_member_1", "family_member_2",
            "family_member_3", "family_member_4",
        }),
        "confirmed_known",
    ),
    STRANGER_PRESENCE_EVENT: (
        frozenset({"unknown"}),
        "confirmed_unknown",
    ),
}

VISUAL_PRESENCE_EVENT_NAMES = frozenset(VISUAL_PRESENCE_EVENT_QUALIFIERS)
VISUAL_POSTURE_EVENT_NAMES = frozenset({OWNER_BEND_SQUAT_EVENT})
VISUAL_POSTURE_ACTIONS = frozenset({"bend_over", "squat_down"})
VISUAL_PRESENCE_TARGET_MAX_AGE_MS = 500.0
