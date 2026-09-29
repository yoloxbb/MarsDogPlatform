"""Offline audio/ASR adapter contracts; all recognizer doubles are explicit."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import wave

import numpy as np
import pytest

from marsdog_voice_interaction import replay
from marsdog_voice_interaction.core.command_lexicon import CommandLexicon
from marsdog_voice_interaction.providers.asr_sherpa import ASRSherpaProvider

CATALOG = Path(__file__).resolve().parents[1] / "config/command_catalog.yaml"


def wav(path, channels=1, rate=16000, width=2, frames=160):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(bytes(frames * channels * width))
    return path


def request(tmp_path):
    for name in ("asr.onnx", "tokens.txt"):
        (tmp_path / name).write_text("test-double-only")
    audio = wav(tmp_path / "go-home.wav")
    return {"model": str(tmp_path / "asr.onnx"), "tokens": str(tmp_path / "tokens.txt"),
            "command_catalog": str(CATALOG), "model_type": "sense_voice", "language": "zh",
            "num_threads": 2, "samples": [{"id": "go-home", "audio": str(audio),
            "expected_text": "回家", "expected_event_type": "EVT_VOICE_COMMAND_GO_HOME"}]}


def test_valid_pcm16_is_float32(tmp_path):
    samples, rate = replay.load_audio(wav(tmp_path / "input.wav"))
    assert rate == 16000 and samples.dtype == np.float32 and samples.shape == (160,)


@pytest.mark.parametrize("options", [{"channels": 2}, {"rate": 8000}, {"width": 1}, {"frames": 0}, {"frames": 16000*61}])
def test_bad_wav_contract_is_rejected(tmp_path, options):
    with pytest.raises(ValueError):
        replay.load_audio(wav(tmp_path / "input.wav", **options))


@pytest.mark.parametrize("model_type", ["sense_voice", "paraformer"])
def test_explicit_cpu_reaches_original_recognizer_factory(monkeypatch, model_type):
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(
        OfflineRecognizer=SimpleNamespace(from_sense_voice=factory, from_paraformer=factory)))
    provider = ASRSherpaProvider({"model_type": model_type, "asr_model": "model.onnx",
                                 "tokens": "tokens.txt", "provider": "cpu"})
    provider.start()
    assert provider.available and captured["provider"] == "cpu"
    provider.stop()


def test_missing_cpu_override_preserves_factory_defaults(monkeypatch):
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(
        OfflineRecognizer=SimpleNamespace(from_sense_voice=factory)))
    provider = ASRSherpaProvider({"asr_model": "model.onnx", "tokens": "tokens.txt"})
    provider.start()
    assert provider.available and "provider" not in captured
    provider.stop()


def test_asr_unavailable_has_no_mock_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(ASRSherpaProvider, "start", lambda self: None)
    with pytest.raises(RuntimeError, match="mock fallback is forbidden"):
        replay.replay(request(tmp_path))


def test_existing_exact_catalog_event_and_text_check():
    lexicon = CommandLexicon(CATALOG)
    sample = {"expected_text": "回家", "expected_event_type": "EVT_VOICE_COMMAND_GO_HOME"}
    errors, event = replay.evaluate({"asr_text": "回家！", "reason": "ok", "language": "zh"}, sample, lexicon)
    assert not errors and event["event_type"] == sample["expected_event_type"]
    errors, _ = replay.evaluate({"asr_text": "坐下", "reason": "ok"}, sample, lexicon)
    assert len(errors) == 2
    errors, _ = replay.evaluate({"asr_text": "回家", "reason": "error"}, sample, lexicon)
    assert errors
    errors, _ = replay.evaluate({"asr_text": "", "reason": "ok"}, {"expected_text": "！"}, lexicon)
    assert errors


def test_segment_replay_calls_provider_and_releases_it(tmp_path, monkeypatch):
    called, stopped = [], []
    monkeypatch.setattr(ASRSherpaProvider, "start", lambda self: setattr(self, "available", True))
    def transcribe(self, audio):
        called.append(audio)
        return {"asr_text": "回家", "language": "zh", "reason": "ok", "confidence": None}
    monkeypatch.setattr(ASRSherpaProvider, "transcribe", transcribe)
    monkeypatch.setattr(ASRSherpaProvider, "stop", lambda self: stopped.append(True))
    report = replay.replay(request(tmp_path))
    assert report["status"] == "PASS" and stopped == [True]
    assert called[0]["sample_rate"] == 16000 and called[0]["audio_samples"].dtype == np.float32
    assert report["cases"][0]["catalog_event"]["event_type"] == "EVT_VOICE_COMMAND_GO_HOME"


def test_cli_failure_is_machine_readable(tmp_path):
    data = request(tmp_path)
    data["model"] = str(tmp_path / "missing.onnx")
    args, output = tmp_path / "request.json", tmp_path / "result.json"
    args.write_text(json.dumps(data))
    assert replay.main(["--request", str(args), "--output", str(output)]) == 1
    assert json.loads(output.read_text())["status"] == "FAIL"
