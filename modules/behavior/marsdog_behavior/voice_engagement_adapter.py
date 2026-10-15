"""Composition boundary for legacy ROS/standalone shells; no scenario policy.

Resolve collaborators on each call so existing client replacement, monkeypatches
and authoritative session/generation ownership keep their original semantics.
The coordinator receives only typed state/capabilities, never the ROS node.
"""
from types import SimpleNamespace

from .voice_engagement_coordinator import VoiceEngagementCoordinator, VoiceEngagementPorts


class _NodeVoiceState:
    def __init__(self, node):
        self._node = node

    @property
    def session(self):
        return self._node._voice_session

    @property
    def config(self):
        return self._node._voice_engagement

    @property
    def generation(self):
        return self._node._voice_session_generation

    @generation.setter
    def generation(self, value):
        self._node._voice_session_generation = value

    @property
    def attention_interaction_id(self):
        return self._node._attention_interaction_id

    @attention_interaction_id.setter
    def attention_interaction_id(self, value):
        self._node._attention_interaction_id = value

    @property
    def attention_mode(self):
        return self._node._attention_mode

    @attention_mode.setter
    def attention_mode(self, value):
        self._node._attention_mode = value


def for_node(node) -> VoiceEngagementCoordinator:
    coordinator = getattr(node, '_voice_coordinator', None)
    if coordinator is not None:
        return coordinator

    def resume_emotions():
        node._pending_emotion_retry_at.clear()
        node._flush_pending_emotions()

    ports = VoiceEngagementPorts(
        lease=SimpleNamespace(
            hold=lambda *a, **kw: node._voice_session_client.hold(*a, **kw),
            release=lambda *a, **kw: node._voice_session_client.release(*a, **kw),
        ),
        targets=SimpleNamespace(
            request_wake_speaker=lambda *a, **kw: node._perception.request_wake_speaker(*a, **kw),
        ),
        candidates=SimpleNamespace(
            add=lambda candidate: node._add_candidate(candidate),
            discard_session=lambda interaction: node._candidate_pool.discard_session(interaction),
            discard_where=lambda predicate: node._candidate_pool.discard_where(predicate),
        ),
        execution=SimpleNamespace(
            discard_pending_interaction=lambda interaction: node._runtime.discard_pending_interaction(interaction),
            cancel_current_interaction=lambda *a, **kw: node._runtime.cancel_current_interaction(*a, **kw),
        ),
        emotions=SimpleNamespace(
            defer=lambda interaction: node._defer_queued_voice_emotions(interaction),
            resume=resume_emotions,
        ),
        publish_attention=lambda enabled, data: node._publish_attention_control(enabled, data),
        build_approach_candidate=lambda **kw: node._intent_mapper.build_voice_approach_candidate(**kw),
        logger=SimpleNamespace(
            info=lambda message: node._logger.info(message),
            warn=lambda message: node._logger.warn(message),
        ),
    )
    coordinator = VoiceEngagementCoordinator(_NodeVoiceState(node), ports)
    node._voice_coordinator = coordinator
    return coordinator
