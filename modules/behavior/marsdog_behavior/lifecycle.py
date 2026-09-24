"""Behavior ownership rules shared by queued and running voice work."""

from __future__ import annotations

from collections.abc import Mapping


def cancel_on_voice_idle(params: Mapping[str, object] | None) -> bool:
    """Only a voice-owned behavior ends when its source conversation closes.

    Missing metadata retains the existing session-owned behavior.  A behavior
    scope or explicit false value transfers ownership to the behavior Goal.
    """
    values = params if isinstance(params, Mapping) else {}
    return (
        values.get("lifecycle_scope") != "behavior"
        and values.get("cancel_on_voice_idle") is not False
    )


def discard_unstarted_on_voice_idle(params: Mapping[str, object] | None) -> bool:
    """A waiting emotion must be re-resolved after voice context disappears."""
    values = params if isinstance(params, Mapping) else {}
    return (
        values.get("session_role") == "voice_waiting_emotion"
        or cancel_on_voice_idle(values)
    )
