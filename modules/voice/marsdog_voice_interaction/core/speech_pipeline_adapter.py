"""ROS shell composition only; no orchestration or copied mutable state."""
import time
import uuid
from .speech_pipeline_ports import SpeechPorts, SpeechRuntime


class _NodeState:
    def __init__(self, node):
        self._node = node

    @property
    def interaction_id(self):
        return getattr(self._node, '_interaction_id', '')

    @interaction_id.setter
    def interaction_id(self, value):
        self._node._interaction_id = value

    @property
    def latest_wake_id(self):
        return getattr(self._node, '_latest_wake_id', '')

    @latest_wake_id.setter
    def latest_wake_id(self, value):
        self._node._latest_wake_id = value

    @property
    def pending_intent(self):
        return getattr(self._node, '_pending_intent', None)

    @pending_intent.setter
    def pending_intent(self, value):
        self._node._pending_intent = value

    @property
    def intent_executor(self):
        return getattr(self._node, '_intent_executor', None)

    @intent_executor.setter
    def intent_executor(self, value):
        self._node._intent_executor = value


def for_node(node) -> SpeechRuntime:
    return SpeechRuntime(_NodeState(node), SpeechPorts(
        perf_counter=lambda: time.perf_counter(),
        new_utterance_id=lambda: uuid.uuid4().hex,
        clean_text=lambda *a, **kw: node._clean_text(*a, **kw),
        command_fuzzy_matching=getattr(node, '_command_fuzzy_matching', True),
        command_lexicon=getattr(node, '_command_lexicon', None),
        command_tracker=getattr(node, '_command_tracker', None),
        complete_intent=lambda *a, **kw: node._complete_intent(*a, **kw),
        effective_kws_arbitration=lambda *a, **kw: node._effective_kws_arbitration(*a, **kw),
        is_short_asr_text=lambda *a, **kw: node._is_short_asr_text(*a, **kw),
        object_target_resolver=getattr(node, '_object_target_resolver', None),
        parse_intent=lambda *a, **kw: node._parse_intent(*a, **kw),
        providers=getattr(node, '_providers', None),
        publish=lambda *a, **kw: node._publish(*a, **kw),
        publish_selected_kws_candidate=lambda *a, **kw: node._publish_selected_kws_candidate(*a, **kw),
        refresh_for_asr_result=lambda *a, **kw: node._refresh_for_asr_result(*a, **kw),
        select_kws_candidate=lambda *a, **kw: node._select_kws_candidate(*a, **kw),
        speaker_operation_lock=getattr(node, '_speaker_operation_lock', None),
        state_machine=getattr(node, '_state_machine', None),
        trace=lambda *a, **kw: node._trace(*a, **kw),
        trace_recognition_arbitration=lambda *a, **kw: node._trace_recognition_arbitration(*a, **kw),
        wakeup_supersedes_utterance=lambda *a, **kw: node._wakeup_supersedes_utterance(*a, **kw),
    ))
