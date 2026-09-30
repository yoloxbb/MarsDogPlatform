"""BT's stateless audio validation; producer/Emotion tolerance stays independent.

No routing, candidate selection, deduplication, session mutation or ROS imports.
Keep each caller's existing logger and clock to preserve diagnostics and timing.
See interfaces/application/audio-event-v2 for the cross-module contract.
"""
from __future__ import annotations

import math

WAKE_ANGLE_FRAME_ID = "microphone_array"

_VOICE_SLOT_KEYS = {
    "command_key",
    "matched_phrase",
    "catalog_phrase",
    "command_catalog_version",
    "match_strategy",
    "expansion_profile",
    "expansion_rule",
    "catalog_source_rows",
    "derived_axis",
    "model_dispatch_policy",
    "specific_dispatch",
    "object_name",
    "object_mention",
    "object_matched_alias",
    "object_match_source",
    "object_catalog_version",
}


def validate_audio_contract(
    event_type: str,
    data: dict,
    *,
    logger,
    intent_entry: dict,
    expected_dispatch_role: str = "specific_command",
) -> dict[str, str] | None:
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 2
        or data.get("event_type") != event_type
    ):
        logger.warning(
            "Rejecting %s: expected matching schema-v2 event",
            event_type,
        )
        return None

    raw_slots = data.get("slots", [])
    if not isinstance(raw_slots, list):
        logger.warning("Rejecting %s: slots must be an array", event_type)
        return None
    voice_slots: dict[str, str] = {}
    for item in raw_slots:
        if not isinstance(item, dict):
            logger.warning("Rejecting %s: malformed slot", event_type)
            return None
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key or key not in _VOICE_SLOT_KEYS:
            continue
        if key in voice_slots and voice_slots[key] != value:
            logger.warning(
                "Rejecting %s: conflicting slot %s",
                event_type,
                key,
            )
            return None
        voice_slots[key] = value

    # Hardware wake is source-distinct from Model Intent CALL and catalog
    # nickname events.  It is a lifecycle event, not an executable command.
    is_hardware_wake = event_type == "EVT_VOICE_WAKEUP"
    if is_hardware_wake:
        return voice_slots

    expected_command_id = str(
        intent_entry.get("expected_command_id", "")
    ).strip()
    if not expected_command_id:
        logger.error(
            "Audio route %s has no expected_command_id",
            event_type,
        )
        return None
    if data.get("should_trigger_behavior_tree") is not True:
        logger.warning(
            "Rejecting %s: should_trigger_behavior_tree is not true",
            event_type,
        )
        return None
    if data.get("dispatch_role") != expected_dispatch_role:
        logger.warning(
            "Rejecting %s: dispatch_role is not %s",
            event_type,
            expected_dispatch_role,
        )
        return None
    if str(data.get("command_id", "")).strip() != expected_command_id:
        logger.warning(
            "Rejecting %s: command_id does not match %s",
            event_type,
            expected_command_id,
        )
        return None
    specific_event_type = str(
        data.get("specific_event_type", "")
    ).strip()
    if specific_event_type != event_type:
        logger.warning(
            "Rejecting %s: specific_event_type mismatch",
            event_type,
        )
        return None
    interaction_id = str(data.get("interaction_id", "")).strip()
    utterance_id = str(data.get("utterance_id", "")).strip()
    if not interaction_id or not utterance_id:
        logger.warning(
            "Rejecting %s: interaction_id and utterance_id are required",
            event_type,
        )
        return None
    for required_key in intent_entry.get("required_voice_slots", []):
        value = voice_slots.get(str(required_key), "")
        if not value or value == "NONE":
            logger.warning(
                "Rejecting %s: required slot %s is unavailable",
                event_type,
                required_key,
            )
            return None
    allowed_values = intent_entry.get("allowed_voice_slot_values", {})
    if isinstance(allowed_values, dict):
        for key, values in allowed_values.items():
            value = voice_slots.get(str(key), "")
            if (
                value
                and isinstance(values, list)
                and value not in values
            ):
                logger.warning(
                    "Rejecting %s: unsupported slot %s=%r",
                    event_type,
                    key,
                    value,
                )
                return None
    return voice_slots


def validate_wake_event(data: dict, *, logger, now) -> dict | None:
    """Validate the formal audio wake contract before any side effect."""
    if not isinstance(data, dict):
        return None
    schema_version = data.get("schema_version")
    if (
        type(schema_version) is not int
        or schema_version != 2
        or data.get("event_type") != "EVT_VOICE_WAKEUP"
    ):
        logger.warn(
            "Wake event rejected: expected schema_version=2 and "
            "EVT_VOICE_WAKEUP"
        )
        return None
    interaction_id = str(data.get("interaction_id", "")).strip()
    header = data.get("header")
    wake_frame_id = (
        str(header.get("frame_id", "")).strip()
        if isinstance(header, dict) else ""
    )
    try:
        wake_angle = float(data["wake_angle"])
        wake_confidence = float(data.get("wake_confidence", 0.0))
        wake_stamp = float(
            header.get("stamp", now())
            if isinstance(header, dict) else now()
        )
    except (KeyError, TypeError, ValueError):
        logger.warn("Wake event rejected: malformed numeric fields")
        return None
    if (
        not interaction_id
        or wake_frame_id != WAKE_ANGLE_FRAME_ID
        or not all(math.isfinite(value) for value in (
            wake_angle, wake_confidence, wake_stamp
        ))
    ):
        logger.warn(
            "Wake event rejected: missing id, invalid frame "
            "(expected %s), or non-finite value"
            % WAKE_ANGLE_FRAME_ID
        )
        return None
    return {
        "interaction_id": interaction_id,
        "wake_id": str(data.get("wake_id", "")).strip(),
        "wake_angle_deg": wake_angle,
        "wake_confidence": max(0.0, min(1.0, wake_confidence)),
        "wake_frame_id": wake_frame_id,
        "wake_event_stamp": wake_stamp,
    }
