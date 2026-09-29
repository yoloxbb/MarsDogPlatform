"""Real offline VAD/speaker/KWS runtime smoke; no microphone, session or ROS."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"status": "FAIL", "device": "cpu", "cases": [],
              "scope": "VAD positive/silence, speaker embedding self-match, KWS loading/stream decode only; no identification accuracy, keyword recall, wakeup hardware, RKLLM, ROS or robot"}
    try:
        from marsdog_voice_interaction.utils.uploaded_audio import UploadedAudioVAD, decode_pcm16_wav, encode_pcm16_wav
        from marsdog_voice_interaction.providers.speaker_sherpa import SpeakerSherpaProvider
        from marsdog_voice_interaction.providers.kws_sherpa import KWSSherpaProvider
        models = args.assets / "archive/models"
        audio = models / "asr/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/test_wavs/zh.wav"
        payload = audio.read_bytes()
        vad = UploadedAudioVAD({"vad_model": str(models / "vad/silero_vad.onnx"), "num_threads": 2})
        positive = vad.analyze_wav(payload)
        negative = vad.analyze_wav(encode_pcm16_wav(np.zeros(32000, np.float32), 16000))
        if positive["segment_count"] < 1 or negative["segment_count"] != 0:
            raise RuntimeError("VAD speech/silence contract failed")
        report["cases"].append({"id": "vad", "status": "PASS", "speech": positive, "silence": negative})
        samples, rate = decode_pcm16_wav(payload)
        speaker = SpeakerSherpaProvider({"speaker_model": str(models / "speaker/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"), "num_threads": 2})
        try:
            speaker.start()
            if not speaker.is_available():
                raise RuntimeError("Speaker model unavailable")
            data = {"audio_samples": samples, "sample_rate": rate}
            enrollment = speaker.enroll(data, speaker_id="ephemeral-upstream-fixture")
            result = speaker.verify_speaker(data, speaker_id="ephemeral-upstream-fixture")
            if not enrollment["success"] or not result["matched"] or result["confidence"] < 0.99:
                raise RuntimeError("Speaker self-match failed")
            report["cases"].append({"id": "speaker", "status": "PASS", "self_match": result,
                                    "assertion": "Same input embedding consistency only; no persisted identity"})
        finally:
            speaker.stop()
        keywords = Path(__file__).resolve().parents[1] / "config/kws_keywords.txt"
        kws = KWSSherpaProvider({"model_dir": str(models / "wakeup/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"),
                                "keywords_file": str(keywords), "num_threads": 2, "provider": "cpu"})
        try:
            kws.start()
            if not kws.is_available():
                raise RuntimeError("KWS model unavailable")
            kws.start_utterance()
            waveform = np.concatenate([samples, np.zeros(16000, np.float32)])
            for start in range(0, len(waveform), 320):
                kws.accept_waveform(waveform[start:start+320], rate)
            # This module-owned probe only asserts actual decode work, not recall.
            if kws._utterance_decodes <= 0:
                raise RuntimeError("KWS performed no decoding")
            report["cases"].append({"id": "kws", "status": "PASS", "decode_steps": kws._utterance_decodes,
                "keyword_hits": kws._utterance_hits, "keyword_file_sha256": hashlib.sha256(keywords.read_bytes()).hexdigest(),
                "assertion": "Model/stream compatibility only; no command detection acceptance"})
            kws.finish_utterance()
        finally:
            kws.stop()
        report.update(status="PASS", versions={k: importlib.metadata.version(k) for k in ("sherpa-onnx", "numpy")})
    except Exception as exc:
        report["error"] = str(exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
