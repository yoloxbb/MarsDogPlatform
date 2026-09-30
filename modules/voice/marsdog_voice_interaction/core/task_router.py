"""Voice task dispatch through existing session, enrollment and provider ports."""
from __future__ import annotations
from typing import Any


def run_task(self, task_type: str, params: dict[str, Any]):
    if task_type == "start_speaker_enrollment":
        with self._speaker_operation_lock:
            speaker = self._providers.get("speaker")
            if (
                speaker is None or not speaker.is_available()
                or getattr(speaker, "_extractor", None) is None
            ):
                return {"ok": False, "error": "speaker extractor unavailable"}
            try:
                self._get_speaker_audio_vad()
            except Exception as exc:
                return {"ok": False, "error": f"speaker VAD unavailable: {exc}"}
            result = self._enrollment.start_speaker(
                str(params.get("name", "")),
                int(params.get("required_shots", 3)),
            )
        if result.get("ok"):
            audio = self._providers.get("audio")
            if audio is not None and hasattr(audio, "start_capture"):
                audio.start_capture()  # type: ignore[attr-defined]
        return result
    if task_type == "cancel_speaker_enrollment":
        with self._speaker_operation_lock:
            return self._enrollment.cancel_speaker()
    if task_type == "verify_speaker":
        speaker = self._providers.get("speaker")
        if speaker is None:
            return {"ok": False, "error": "speaker or audio unavailable"}
        with self._speaker_operation_lock:
            if "audio_base64" in params:
                try:
                    audio_data = self._decode_audio_params(params)
                    if audio_data is None:
                        raise ValueError("audio_base64 is empty")
                    from marsdog_voice_interaction.utils.uploaded_audio import encode_pcm16_wav
                    trimmed = self._get_speaker_audio_vad().trim_wav(
                        encode_pcm16_wav(
                            audio_data["audio_samples"], audio_data["sample_rate"],
                        )
                    )
                    audio_data = {
                        "audio_samples": trimmed.samples,
                        "sample_rate": trimmed.sample_rate, "has_voice": True,
                    }
                except (ValueError, RuntimeError) as exc:
                    return {"ok": False, "code": "invalid_audio", "error": str(exc)}
            else:
                audio_data = self._latest_audio
            if audio_data is None:
                return {"ok": False, "error": "speaker or audio unavailable"}
            result = speaker.verify(audio_data)  # type: ignore[attr-defined]
        return {"ok": True, **result}
    if task_type == "hold_interaction":
        return self._hold_interaction(params)
    if task_type == "release_interaction_hold":
        return self._release_interaction_hold(params)
    if task_type == "get_interaction_state":
        return self._interaction_state()
    if task_type == "start_listening":
        expected_id = str(
            params.get("expected_interaction_id", "")
        ).strip()
        with self._interaction_lock:
            if self._interaction_active:
                if expected_id and expected_id != self._interaction_id:
                    return {
                        "ok": False,
                        "error": "expected_interaction_id mismatch",
                    }
                interaction_id = self._interaction_id
                self._refresh_interaction_activity(
                    reason="start_listening"
                )
            else:
                if expected_id:
                    return {
                        "ok": False,
                        "error": "expected interaction is no longer active",
                    }
                interaction_id = self._begin_interaction(source="service")
        audio = self._providers.get("audio")
        if audio is not None and hasattr(audio, "start_capture"):
            is_capturing = getattr(audio, "is_capturing", None)
            if not callable(is_capturing) or not is_capturing():
                self._start_interaction_capture(audio)
        return {
            "ok": True,
            "listening": True,
            "interaction_id": interaction_id,
        }
    if task_type == "stop_listening":
        ended = self._end_interaction("stop_listening")
        return {"ok": True, "listening": False, "ended": ended}
    return {"ok": False, "error": f"unsupported task_type: {task_type}"}
