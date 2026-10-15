"""Compatible voice entrypoints; policies live in VoiceEngagementCoordinator."""
from __future__ import annotations
from .voice_interaction_session import VoiceInteractionSession
from .voice_engagement_adapter import for_node


def request_voice_hold(node, session: VoiceInteractionSession):
    return for_node(node).request_voice_hold(session)


def renew_voice_hold_if_due(node):
    return for_node(node).renew_voice_hold_if_due()


def expire_wake_target_query_if_due(node):
    return for_node(node).expire_wake_target_query_if_due()


def expire_wake_identity_if_due(node):
    return for_node(node).expire_wake_identity_if_due()


def continue_wake_after_identity(node, session: VoiceInteractionSession):
    return for_node(node).continue_wake_after_identity(session)


def release_voice_hold(node, session: VoiceInteractionSession, *, reset_idle_timer: bool):
    return for_node(node).release_voice_hold(session, reset_idle_timer=reset_idle_timer)


def close_voice_session(node, interaction_id: str, *, reason: str):
    return for_node(node).close_voice_session(interaction_id, reason=reason)


def enter_voice_waiting(node, session: VoiceInteractionSession, *, reason: str):
    return for_node(node).enter_voice_waiting(session, reason=reason)


def request_wake_speaker(node, session: VoiceInteractionSession):
    return for_node(node).request_wake_speaker(session)


def on_wake_speaker_resolved(node, interaction_id: str, generation: int, target: dict | None):
    return for_node(node).on_wake_speaker_resolved(interaction_id, generation, target)


def handle_voice_behavior_terminal(node, active, completed):
    return for_node(node).handle_voice_behavior_terminal(active, completed)


def consume_voice_session_turn(node, session, kind: str):
    return for_node(node).consume_voice_session_turn(session, kind)
