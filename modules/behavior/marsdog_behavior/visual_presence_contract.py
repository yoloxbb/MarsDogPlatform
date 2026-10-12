"""Behavior-side qualification for v1 visual presence state events."""

OWNER_PRESENCE_EVENT = "EVT_VISION_OWNER_PRESENT"
FAMILY_PRESENCE_EVENT = "EVT_VISION_FAMILY_PRESENT"
STRANGER_PRESENCE_EVENT = "EVT_VISION_STRANGER_PRESENT"

VISUAL_PRESENCE_EVENT_QUALIFIERS = {
    OWNER_PRESENCE_EVENT: (frozenset({"owner"}), "confirmed_known"),
    FAMILY_PRESENCE_EVENT: (
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
VISUAL_PRESENCE_TARGET_MAX_AGE_MS = 500.0
