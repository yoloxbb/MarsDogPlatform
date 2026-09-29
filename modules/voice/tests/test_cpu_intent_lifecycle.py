"""CPU scheduling contracts with controllable inference; no model or DDS claims."""
from concurrent.futures import Future
import threading
import time

from marsdog_voice_interaction.nodes.voice_interaction_node import VoiceInteractionNode
from marsdog_voice_interaction.messages.intent_protocol import classification_to_event
from test_command_lexicon import _DirectRouteHarness
from test_session_recovery import _NodeHarness, _FakeAudio, _FakeWakeup


def pending_node():
    audio = _FakeAudio()
    node = _NodeHarness(audio, _FakeWakeup())
    node._idle_timeout = node._max_interaction_duration = 0
    future = Future()
    context = {"utterance_id": "old-turn", "utterance_wake_id": ""}
    node._pending_intent = (node._interaction_id, context, future)
    completions = []
    node._complete_intent = lambda result, **kw: completions.append((result, kw))
    return node, audio, future, completions


def test_stop_and_restart_respond_without_waiting_and_discard_old_result():
    node, audio, future, completions = pending_node()
    old_id = node._interaction_id
    assert node._run_task("stop_listening", {})["listening"] is False
    new_id = node._run_task("start_listening", {})["interaction_id"]
    assert new_id != old_id
    assert node._run_task("get_interaction_state", {})["interaction_id"] == new_id
    assert not audio.is_capturing(), "Must not queue another inference"
    assert node._poll_pending_intent(audio)
    future.set_result({"intent": "SIT", "control": "DO"})
    assert not node._poll_pending_intent(audio)
    assert not completions
    node._poll()
    assert audio.is_capturing()
    assert not any(e.get("intent") == "SIT" for e in node.published)


def test_timeout_during_inference_discards_even_already_completed_result(monkeypatch):
    node, audio, future, completions = pending_node()
    node._idle_timeout = 1
    monkeypatch.setattr(time, "monotonic", lambda: 102)
    future.set_result({"intent": "SIT"})
    assert not node._poll_pending_intent(audio)
    assert not node._interaction_active and not completions
    assert node.published[-1]["state_reason"] == "interaction_timeout"


def test_new_wakeup_never_receives_old_completion():
    node, audio, future, completions = pending_node()
    node._latest_wake_id = "new-wake"
    node._command_tracker.begin("new-turn")
    future.set_result({"intent": "SIT"})
    assert not node._poll_pending_intent(audio)
    assert not completions
    assert node._command_tracker.utterance_id == "new-turn"


def test_worker_failure_returns_to_capture_without_executable_result():
    node, audio, future, completions = pending_node()
    future.set_exception(RuntimeError("inference failed"))
    assert node._poll_pending_intent(audio)
    assert completions[0][0] is None
    assert audio.is_capturing()


def test_live_completion_is_delivered_once():
    node, audio, future, completions = pending_node()
    future.set_result({"intent": "SIT"})
    assert node._poll_pending_intent(audio)
    assert not node._poll_pending_intent(audio)
    assert len(completions) == 1 and audio.is_capturing()


def test_real_thread_does_computation_only_until_ros_completion():
    entered, release = threading.Event(), threading.Event()
    calls = []
    class Provider:
        preserve_asr_text = True
        background_intent = True
        input_rejected = False
        def is_available(self):
            return True
        def parse_intent(self, text):
            calls.append((text, threading.get_ident()))
            entered.set()
            assert release.wait(5)
            return classification_to_event("NONE", "SIT", "DO", asr_text=text, source="qwen_cpu")
    class Harness(_DirectRouteHarness):
        _parse_intent = VoiceInteractionNode._parse_intent
        _poll_pending_intent = VoiceInteractionNode._poll_pending_intent
        def _timeout_interaction_id(self, now):
            return ""
        def _finish_speech_capture(self, audio):
            self.completed_on = threading.get_ident()
    node = Harness("请在原地坐下。")
    node._providers["intent_llm"] = Provider()
    node._interaction_lock = threading.RLock()
    node._interaction_active = True
    node._latest_wake_id = ""
    try:
        assert node._process_speech({"has_voice": True}, "async-turn")
        assert entered.wait(2)
        assert not any(e.get("intent_source") == "qwen_cpu" for e in node.published)
        assert calls[0][0] == "请在原地坐下。"
        assert calls[0][1] != threading.get_ident()
        release.set()
        node._pending_intent[2].result(timeout=5)
        assert node._poll_pending_intent(None)
        assert node.completed_on == threading.get_ident()
        assert any(e.get("intent_source") == "qwen_cpu" for e in node.published)
    finally:
        release.set()
        node._intent_executor.shutdown(wait=True)
