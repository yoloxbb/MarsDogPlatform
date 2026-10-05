"""Fixed face identities shared by enrollment and HTTP management."""

from __future__ import annotations

from enum import Enum


class FaceIdentity(str, Enum):
    """Device-local identity slots exposed by the face API."""

    OWNER = "owner"
    FAMILY_MEMBER_1 = "family_member_1"
    FAMILY_MEMBER_2 = "family_member_2"
    FAMILY_MEMBER_3 = "family_member_3"
    FAMILY_MEMBER_4 = "family_member_4"


ALLOWED_FACE_IDENTITIES = tuple(item.value for item in FaceIdentity)

_DISPLAY_NAMES = {
    FaceIdentity.OWNER.value: "主人",
    FaceIdentity.FAMILY_MEMBER_1.value: "家人1",
    FaceIdentity.FAMILY_MEMBER_2.value: "家人2",
    FaceIdentity.FAMILY_MEMBER_3.value: "家人3",
    FaceIdentity.FAMILY_MEMBER_4.value: "家人4",
}


def validate_face_identity(value: str | FaceIdentity) -> str:
    """Return one fixed identity or raise a stable validation error."""
    raw_value = value.value if isinstance(value, FaceIdentity) else str(value)
    if raw_value not in ALLOWED_FACE_IDENTITIES:
        allowed = "、".join(ALLOWED_FACE_IDENTITIES)
        raise ValueError(f"人脸身份只能是：{allowed}")
    return raw_value


def face_identity_role(value: str | FaceIdentity) -> str:
    """Classify a fixed identity without treating legacy names as family."""
    raw_value = value.value if isinstance(value, FaceIdentity) else str(value)
    if raw_value == FaceIdentity.OWNER.value:
        return "owner"
    if raw_value in ALLOWED_FACE_IDENTITIES[1:]:
        return "family"
    return "unknown"


def pose_event_identity_eligible(
    identity: str,
    identity_state: str,
    tracking_state: str,
) -> bool:
    """Return whether a tracked target may emit a pose or hand event.

    Registered identities must be confirmed by the face state machine.  An
    unknown face may also emit the established pose event names after the
    unknown state has been confirmed.  Candidate and unverified states remain
    gated so a transient recognition result cannot become an event.
    """
    normalized_identity = str(identity or "")
    normalized_identity_state = str(identity_state or "")
    return str(tracking_state or "") == "tracking" and (
        (
            normalized_identity in ALLOWED_FACE_IDENTITIES
            and normalized_identity_state == "confirmed_known"
        )
        or (
            normalized_identity == "unknown"
            and normalized_identity_state == "confirmed_unknown"
        )
    )


def face_identity_display_name(value: str | FaceIdentity) -> str:
    """Return the operator-facing Chinese slot label."""
    raw_value = value.value if isinstance(value, FaceIdentity) else str(value)
    return _DISPLAY_NAMES.get(raw_value, raw_value)
