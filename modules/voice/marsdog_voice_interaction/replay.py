"""Offline segmented-WAV ASR replay; no microphone, serial wakeup or mock fallback."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
from pathlib import Path
import time
import wave


def load_audio(path: Path):
    from marsdog_voice_interaction.utils.uploaded_audio import decode_pcm16_wav
    if path.stat().st_size > 2 * 16000 * 60 + 4096:
        raise ValueError("Replay accepts at most 60 seconds of PCM16 mono audio")
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("Replay requires PCM16 mono 16000 Hz WAV; no implicit resampling")
        if not 0 < source.getnframes() <= 16000 * 60:
            raise ValueError("Replay audio must contain 0..60 seconds of nonempty samples")
    return decode_pcm16_wav(path.read_bytes())


def evaluate(result: dict, sample: dict, lexicon):
    from marsdog_voice_interaction.core.command_lexicon import normalize_command_phrase
    errors = []
    if result.get("reason") != "ok":
        errors.append("ASR outcome: " + str(result.get("reason")))
    text = str(result.get("asr_text", ""))
    if not normalize_command_phrase(sample["expected_text"]):
        errors.append("Expected transcript must contain words")
    elif normalize_command_phrase(text) != normalize_command_phrase(sample["expected_text"]):
        errors.append("Transcript differs after existing catalog normalization")
    match = lexicon.match(text)
    event = match.to_event(asr_text=text, language=result.get("language", "zh")) if match else None
    if "expected_event_type" in sample and (event or {}).get("event_type") != sample["expected_event_type"]:
        errors.append("Exact catalog event differs")
    return errors, event


def replay(request: dict) -> dict:
    from marsdog_voice_interaction.providers.asr_sherpa import ASRSherpaProvider
    from marsdog_voice_interaction.core.command_lexicon import CommandLexicon
    if not Path(request["model"]).is_file() or not Path(request["tokens"]).is_file():
        raise ValueError("Local ASR ONNX model and tokens are required")
    lexicon = CommandLexicon(request["command_catalog"])
    provider = ASRSherpaProvider({
        "asr_model": request["model"], "tokens": request["tokens"], "provider": "cpu",
        "model_type": request["model_type"], "language": request["language"],
        "sample_rate": 16000, "num_threads": request["num_threads"], "use_itn": True,
        "audio_debug": {"enabled": False},
    })
    cases = []
    try:
        provider.start()
        if not provider.is_available():
            raise RuntimeError("ASR failed to initialize; mock fallback is forbidden in replay")
        for sample in request["samples"]:
            samples, rate = load_audio(Path(sample["audio"]))
            started = time.perf_counter()
            result = provider.transcribe({"audio_samples": samples, "sample_rate": rate, "has_voice": True})
            errors, event = evaluate(result, sample, lexicon)
            cases.append({"id": sample["id"], "status": "FAIL" if errors else "PASS",
                          "asr": result, "catalog_event": event, "errors": errors,
                          "elapsed_ms": round((time.perf_counter()-started)*1000, 3)})
    finally:
        provider.stop()
    return {"status": "PASS" if cases and all(c["status"] == "PASS" for c in cases) else "FAIL",
            "device": "cpu", "real_model_inference": bool(cases), "cases": cases,
            "module_file": __file__,
            "versions": {k: importlib.metadata.version(k) for k in ("sherpa-onnx", "numpy")},
            "scope": "Presegmented WAV ASR and existing exact command catalog payload only; no VAD/wakeup/speaker/LLM/ROS/session acceptance"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = replay(json.loads(args.request.read_text()))
    except Exception as exc:
        report = {"status": "FAIL", "device": "cpu", "real_model_inference": False, "cases": [], "error": str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
