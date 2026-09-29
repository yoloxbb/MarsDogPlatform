"""Probe lifecycle/evidence tests; do not count as real ROS or model inference."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("cpu_ros_probe", Path(__file__).with_name("ros_cpu_pipeline_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_closed_capture_discards_new_input_and_cancel_discards_pending():
    audio = probe.FixtureAudio()
    audio.enqueue({"id": "inactive", "text": "sit"})
    audio.start_capture()
    assert audio.poll_result() is None
    audio.enqueue({"id": "cancelled", "text": "sit"})
    audio.cancel_capture()
    audio.start_capture()
    assert audio.poll_result() is None
    assert not audio.delivered


def test_utterance_identity_and_single_delivery_are_preserved():
    audio = probe.FixtureAudio()
    audio.set_utterance_id("node-assigned")
    audio.start_capture()
    audio.enqueue({"id": "active", "text": "sit"})
    result = audio.poll_result()
    assert result["utterance_id"] == "node-assigned"
    assert audio.poll_result() is None
    assert audio.delivered == [{"id": "active", "utterance_id": "node-assigned"}]


def test_explicit_text_fixture_is_never_claimed_as_asr():
    class Delegate:
        def transcribe(self, data):
            return {"asr_text": "actual", "reason": "ok"}
    audit = {"asr": []}
    observed = probe.ObservedASR(Delegate(), audit)
    assert observed.transcribe({"probe_case": {"id": "text", "text": "fixture"}})["reason"] == "text_fixture"
    assert observed.transcribe({"probe_case": {"id": "wav", "audio": "fixture.wav"}})["asr_text"] == "actual"
    assert [x["kind"] for x in audit["asr"]] == [
        "explicit_text_fixture_no_asr", "real_sensevoice_cpu"]


def test_wrong_model_label_does_not_hide_transport_or_execution_violations():
    case = {"id": "case", "text": "fixture", "source": "qwen_cpu",
            "expected_tag": "NONE|FOLLOW|STOP", "must_not_execute": True}
    audit = {"asr": [{"id": "case"}], "intent": [{"id": "case", "classification": {
        "raw_nlu_tag": "NONE|SIT|DO"}}]}
    events = [
        {"event_type": "speech", "interaction_id": "session"},
        {"event_type": "EVT_VOICE_COMMAND_SIT", "interaction_id": "session",
         "intent_source": "qwen_cpu", "raw_nlu_tag": "NONE|SIT|DO", "is_executable": True}]
    result = probe.check_case(case, events, audit, "session")
    assert result["quality_errors"] == ["intent_tag_mismatch"]
    assert "Unexpected executable event" in result["transport_errors"]


def test_correct_sit_cannot_pass_with_only_non_executable_semantics():
    case = {"id": "qwen-sit", "text": "fixture", "source": "qwen_cpu",
            "expected_tag": "NONE|SIT|DO", "must_not_execute": False}
    audit = {"asr": [{"id": "qwen-sit"}], "intent": [{"id": "qwen-sit", "classification": {
        "raw_nlu_tag": "NONE|SIT|DO"}}]}
    events = [
        {"event_type": "speech", "interaction_id": "session"},
        {"event_type": "EVT_VOICE_COMMAND_KNOWN", "interaction_id": "session",
         "intent_source": "qwen_cpu", "raw_nlu_tag": "NONE|SIT|DO", "is_executable": False}]
    result = probe.check_case(case, events, audit, "session")
    assert result["quality_errors"] == []
    assert "Correct Qwen SIT lost executable dispatch" in result["transport_errors"]
