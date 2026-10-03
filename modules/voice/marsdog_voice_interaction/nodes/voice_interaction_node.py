"""Independent ROS2 node for wakeup, ASR, speaker and intent interaction."""

from __future__ import annotations

from marsdog_observability import configure

from marsdog_voice_interaction.messages import task_service

from marsdog_voice_interaction.core import task_router

from marsdog_voice_interaction.core import speech_pipeline

from marsdog_voice_interaction.core import interaction_session

import base64
from concurrent.futures import Future, ThreadPoolExecutor
import json
import math
import re
import threading
import time
import uuid
from typing import Any

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

try:
    from marsdog_voice_interaction.srv import VoiceTask
except ImportError:
    VoiceTask = None  # type: ignore[assignment]

from marsdog_voice_interaction.core.command_lexicon import CommandLexicon
from marsdog_voice_interaction.core.object_target_resolver import (
    ObjectTargetResolver,
    object_resolution_slots,
)
from marsdog_voice_interaction.core.interaction_state_machine import (
    Trigger,
    VoiceInteractionStateMachine,
)
from marsdog_voice_interaction.core.speaker_enrollment_manager import (
    SpeakerEnrollmentManager,
    set_storage_root,
)
from marsdog_voice_interaction.core.utterance_command_tracker import (
    UtteranceCommandTracker,
)
from marsdog_voice_interaction.messages.audio_event import normalize_audio_event
from marsdog_voice_interaction.messages.speaker_identity import speaker_identity_role
from marsdog_voice_interaction.messages.intent_event_router import (
    route_classification_events,
)
from marsdog_voice_interaction.messages.intent_protocol import NLU_PROTOCOL
from marsdog_voice_interaction.messages.voice_event_types import (
    EVT_STATE_CHANGED,
    EVT_VOICE_COMMAND_KNOWN,
    EVT_VOICE_COMMAND_UNKNOWN,
    EVT_VOICE_NEUTRAL,
    EVT_VOICE_WAKEUP,
    EVT_VOICE_WAKE_SPEAKER_RESULT,
    speaker_to_voice_event,
)
from marsdog_voice_interaction.providers.base import BaseProvider
from marsdog_voice_interaction.utils.config_loader import load_config
from marsdog_voice_interaction.utils.logging_utils import (
    get_log_file_path,
    get_logger,
    log_trace,
)
from marsdog_voice_interaction.utils.text_normalization import (
    normalize_chinese_numbers,
)


logger = get_logger(__name__, module="voice")

_AUDIO_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

_UNKNOWN_INTENT = {
    "event_type": EVT_VOICE_COMMAND_UNKNOWN,
    "social": "NONE",
    "intent": "NONE",
    "emotion": "NONE",
    "action": "NONE",
    "control": "NONE",
    "command_id": "CMD_UNKNOWN",
    "intent_category": "diagnostic",
    "intent_source": "invalid_protocol_fallback",
    "intent_confidence": 0.0,
    "nlu_protocol": NLU_PROTOCOL,
    "raw_nlu_tag": "",
    "dispatch_role": "diagnostic",
    "slots": [
        {"key": "reason", "value": "no_valid_rkllm_result"},
    ],
    "is_executable": False,
    "should_trigger_behavior_tree": False,
}


class VoiceInteractionNode(Node):
    """Own voice hardware, voice-print data and the voice ROS APIs."""

    def __init__(self) -> None:
        super().__init__("voice_interaction")
        self.declare_parameter("config_path", "config/voice.yaml")
        self.declare_parameter("log_level", "")
        self.declare_parameter("log_dir", "")
        config_path = str(self.get_parameter("config_path").value)
        try:
            self._config = load_config(config_path)
        except Exception as exc:
            configure("voice", log_dir="log", level="INFO")
            logger.error("Cannot load voice config %s: %s", config_path, exc)
            self._config = {}

        logging_config = self._config.get("logging", {})
        log_level_override = str(self.get_parameter("log_level").value).strip()
        log_dir_override = str(self.get_parameter("log_dir").value).strip()
        log_level = log_level_override or str(
            logging_config.get("level", "INFO")
        )
        log_dir = log_dir_override or str(logging_config.get("dir", "log"))
        configure("voice", log_dir=log_dir, level=log_level)
        self._event_trace_enabled = bool(
            logging_config.get("event_trace", True)
        )
        self._command_lexicon: CommandLexicon | None = None
        self._command_lexicon_status: dict[str, Any] = {
            "enabled": False,
            "ready": False,
        }
        self._init_command_lexicon()
        self._object_target_resolver: ObjectTargetResolver | None = None
        self._object_target_status: dict[str, Any] = {
            "enabled": False,
            "ready": False,
        }
        self._init_object_target_resolver()

        set_storage_root(
            self._config.get("storage", {}).get("root", "data")
        )
        speaker_api_config = self._config.get("speaker_api", {})
        self._enrollment = SpeakerEnrollmentManager(
            cross_identity_similarity_threshold=speaker_api_config.get(
                "cross_identity_similarity_threshold",
                0.75,
            ),
            same_identity_similarity_threshold=speaker_api_config.get(
                "same_identity_similarity_threshold", 0.5,
            ),
        )
        self._state_machine = VoiceInteractionStateMachine()
        self._providers: dict[str, BaseProvider | None] = {}
        self._speaker_operation_lock = threading.RLock()
        self._speaker_api: Any = None
        self._speaker_api_status: dict[str, Any] = {
            "enabled": False,
            "ready": False,
        }
        self._upload_vad: Any = None
        self._interaction_lock = threading.RLock()
        self._interaction_active = False
        self._interaction_id = ""
        self._interaction_started_time = 0.0
        self._last_interaction_time = 0.0
        self._last_interaction_activity_reason = ""
        self._interaction_holds: dict[str, dict[str, Any]] = {}
        self._latest_audio: dict[str, Any] | None = None
        self._command_tracker = UtteranceCommandTracker()
        self._utterance_started_monotonic = 0.0
        self._kws_arbitration = self._load_kws_arbitration_config()

        interaction = self._config.get("interaction", {})
        self._idle_timeout = float(interaction.get("idle_timeout_sec", 10))
        self._refresh_on_any_speech = bool(
            interaction.get("refresh_on_any_speech", False)
        )
        self._wake_speaker_enabled = bool(interaction.get("wake_speaker_enabled", False))
        self._wake_audio_window_sec = max(
            0.5, float(interaction.get("wake_audio_window_sec", 2.5))
        )
        self._wake_event_max_age_sec = max(
            0.1, float(interaction.get("wake_event_max_age_sec", 8.0))
        )
        self._wake_debounce_sec = max(
            0.0, float(interaction.get("wake_debounce_sec", 0.8))
        )
        self._last_wake_received = 0.0
        self._last_wake_word = ""
        self._latest_wake_id = ""
        self._wake_identity_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="wake-speaker"
        )
        self._pending_wake_identity: tuple[str, str, Future[dict[str, Any]]] | None = None
        self._intent_executor: ThreadPoolExecutor | None = None
        self._pending_intent: tuple[str, dict[str, Any], Future] | None = None
        self._last_capture_retry = 0.0
        self._max_interaction_duration = self._resolve_max_interaction_duration(
            self._idle_timeout,
            interaction.get("max_duration_sec", 120.0),
        )
        self._hold_max_lease_sec = max(
            0.1,
            float(interaction.get("hold_max_lease_sec", 30.0)),
        )
        # Test-mode settings widen the session lifetime, so make them loud in
        # the logs: they must never reach a production run unnoticed.
        if self._refresh_on_any_speech:
            logger.warning(
                "interaction.refresh_on_any_speech is ON (test mode): any "
                "VAD-confirmed speech refreshes the idle timer, even without "
                "a non-empty ASR result. Production must keep it false."
            )
        if self._max_interaction_duration <= 0.0:
            logger.info(
                "Interaction absolute timeout disabled; idle_timeout_sec=%.1f "
                "(<=0 disables idle timeout too). stop_listening remains available.",
                self._idle_timeout,
            )
        self._init_providers()
        self._wire_speaker_enrollment()
        self._sync_speaker_registry()

        topics = self._config.get("topics", {})
        audio_topic = str(
            topics.get("audio_event", "/perception/audio_event")
        )
        enrollment_topic = str(
            topics.get(
                "enrollment_event",
                "/perception/voice/enrollment_event",
            )
        )
        self._audio_pub = self.create_publisher(
            String, audio_topic, _AUDIO_QOS
        )
        self._enrollment_pub = self.create_publisher(
            String, enrollment_topic, _AUDIO_QOS
        )
        self._timer = self.create_timer(0.05, self._poll)

        service_name = str(
            topics.get("voice_task", "/perception/voice/task")
        )
        self._service = (
            self.create_service(VoiceTask, service_name, self._handle_task)
            if VoiceTask is not None else None
        )
        logger.info(
            "Voice node ready: audio=%s service=%s",
            audio_topic,
            service_name if self._service is not None else "unavailable",
        )
        self._init_speaker_api()
        self._trace(
            "runtime_start",
            result="ready",
            runtime_mode=self._runtime_mode(),
            config_path=config_path,
            log_level=log_level.upper(),
            log_file=get_log_file_path(),
            audio_topic=audio_topic,
            enrollment_topic=enrollment_topic,
            service=service_name if self._service is not None else "unavailable",
            idle_timeout_sec=self._idle_timeout,
            max_duration_sec=self._max_interaction_duration,
            refresh_on_any_speech=self._refresh_on_any_speech,
            speaker_api=self._speaker_api_status,
            command_lexicon=self._command_lexicon_status,
            object_target_routing=self._object_target_status,
            kws_arbitration=self._kws_arbitration,
            audio_debug=dict(self._config.get("audio_debug", {})),
            providers={
                name: {
                    "class": type(provider).__name__,
                    "available": bool(provider and provider.is_available()),
                }
                for name, provider in sorted(self._providers.items())
            },
        )

    def _runtime_mode(self) -> str:
        mock = self._config.get("mock", {})
        if not mock.get("enabled", False):
            return "production"
        return f"mock_{mock.get('mode', 'pipeline')}"

    def _load_kws_arbitration_config(self) -> dict[str, Any]:
        """Load the safety-critical KWS/ASR exclusive arbitration policy."""

        providers = self._config.get("providers", {})
        kws = providers.get("kws", {}) if isinstance(providers, dict) else {}
        config = kws.get("config", {}) if isinstance(kws, dict) else {}
        if not isinstance(config, dict):
            config = {}
        priority_command_keys = config.get("priority_command_keys", [])
        if not isinstance(priority_command_keys, list):
            raise ValueError(
                "providers.kws.config.priority_command_keys must be a list"
            )
        priority_asr_aliases = config.get("priority_asr_aliases", {})
        if not isinstance(priority_asr_aliases, dict):
            raise ValueError(
                "providers.kws.config.priority_asr_aliases must be a mapping"
            )
        normalized_priority_aliases: dict[str, tuple[str, ...]] = {}
        for raw_key, raw_aliases in priority_asr_aliases.items():
            if not isinstance(raw_aliases, list):
                raise ValueError(
                    "providers.kws.config.priority_asr_aliases values "
                    "must be lists"
                )
            key = str(raw_key).strip().upper()
            if not key:
                continue
            normalized_priority_aliases[key] = tuple(dict.fromkeys(
                self._clean_text(str(alias))
                for alias in raw_aliases
                if self._clean_text(str(alias))
            ))
        policy = {
            "publish_mode": str(
                config.get("publish_mode", "deferred")
            ).strip().lower(),
            "arbitration_mode": str(
                config.get("arbitration_mode", "exclusive")
            ).strip().lower(),
            "asr_long_text_wins": bool(
                config.get("asr_long_text_wins", True)
            ),
            "kws_fallback_on_asr_empty": bool(
                config.get("kws_fallback_on_asr_empty", False)
            ),
            "short_requires_asr_agreement": bool(
                config.get("short_requires_asr_agreement", True)
            ),
            "short_max_chars_zh": max(
                1, int(config.get("short_max_chars_zh", 2))
            ),
            "short_max_words_en": max(
                1, int(config.get("short_max_words_en", 2))
            ),
            "priority_command_keys": tuple(dict.fromkeys(
                str(value).strip().upper()
                for value in priority_command_keys
                if str(value).strip()
            )),
            "priority_asr_aliases": normalized_priority_aliases,
        }
        if policy["publish_mode"] != "deferred":
            raise ValueError(
                "providers.kws.config.publish_mode must be 'deferred'"
            )
        if policy["arbitration_mode"] != "exclusive":
            raise ValueError(
                "providers.kws.config.arbitration_mode must be 'exclusive'"
            )
        return policy

    def _init_command_lexicon(self) -> None:
        config = self._config.get("command_lexicon", {})
        enabled = bool(config.get("enabled", False))
        # Homophone-tolerant fallback for ASR near-miss characters.  Defaults
        # to on, but stays switchable because a wrong fuzzy match executes a
        # wrong action on the robot.
        self._command_fuzzy_matching = bool(
            config.get("fuzzy_matching", True)
        )
        self._command_lexicon_status = {
            "enabled": enabled,
            "ready": False,
            "fuzzy_matching": self._command_fuzzy_matching,
        }
        if not enabled:
            return
        catalog_path = str(config.get("catalog", "")).strip()
        try:
            if not catalog_path:
                raise ValueError("command_lexicon.catalog is required")
            lexicon = CommandLexicon(catalog_path)
            self._command_lexicon = lexicon
            self._command_lexicon_status.update({
                "ready": True,
                "catalog": str(lexicon.catalog_path),
                "version": lexicon.version,
                "command_count": lexicon.command_count,
                "core_command_count": lexicon.core_command_count,
                "phrase_count": lexicon.phrase_count,
                "expansion_enabled": lexicon.expansion_enabled,
                "variants_per_phrase": lexicon.variants_per_phrase,
                "expanded_phrase_count": lexicon.expanded_phrase_count,
                "variant_phrase_count": lexicon.variant_phrase_count,
                "total_match_phrase_count": lexicon.total_match_phrase_count,
                "expansion_profile_count": lexicon.expansion_profile_count,
                "reference_phrase_count": lexicon.reference_phrase_count,
                "source_name": lexicon.source_name,
                "source_row_count": lexicon.source_row_count,
                "covered_source_row_count": lexicon.covered_source_row_count,
            })
            logger.info(
                "Command lexicon ready: version=%s commands=%d core=%d "
                "phrases=%d expanded=%d variants=%d total=%d fuzzy=%s",
                lexicon.version,
                lexicon.command_count,
                lexicon.core_command_count,
                lexicon.phrase_count,
                lexicon.expanded_phrase_count,
                lexicon.variant_phrase_count,
                lexicon.total_match_phrase_count,
                self._command_fuzzy_matching,
            )
        except Exception as exc:
            self._command_lexicon = None
            self._command_lexicon_status["error"] = str(exc)
            logger.error("Command lexicon unavailable: %s", exc)

    def _init_object_target_resolver(self) -> None:
        config = self._config.get("object_target_routing", {})
        enabled = bool(config.get("enabled", True))
        self._object_target_status = {
            "enabled": enabled,
            "ready": False,
        }
        if not enabled:
            return
        try:
            catalog_path = str(config.get("catalog", "")).strip()
            if not catalog_path:
                raise ValueError("object_target_routing.catalog is required")
            resolver = ObjectTargetResolver(catalog_path)
            self._object_target_resolver = resolver
            self._object_target_status.update({
                "ready": True,
                "catalog": str(resolver.catalog_path),
                "version": resolver.version,
                "target_count": resolver.target_count,
                "alias_count": resolver.alias_count,
            })
            logger.info(
                "Object target catalog loaded: version=%s targets=%d "
                "aliases=%d",
                resolver.version,
                resolver.target_count,
                resolver.alias_count,
            )
        except Exception as exc:
            self._object_target_resolver = None
            self._object_target_status["error"] = str(exc)
            logger.error("Object target catalog unavailable: %s", exc)

    def _trace(self, record: str, **fields: Any) -> None:
        if getattr(self, "_event_trace_enabled", True):
            log_trace(logger, record, **fields)

    def _init_speaker_api(self) -> None:
        config = self._config.get("speaker_api", {})
        enabled = bool(config.get("enabled", False))
        self._speaker_api_status = {"enabled": enabled, "ready": False}
        if not enabled:
            return
        try:
            from marsdog_voice_interaction.api import SpeakerApiServer
            self._get_speaker_audio_vad()
            self._speaker_api = SpeakerApiServer(
                config,
                self._enroll_uploaded_speaker,
                list_handler=self._list_speakers_for_api,
                sample_list_handler=self._list_speaker_samples_for_api,
                sample_get_handler=self._get_speaker_sample_for_api,
                sample_replace_handler=(
                    self._replace_speaker_sample_for_api
                ),
                sample_delete_handler=self._delete_speaker_sample_for_api,
                batch_upload_handler=self._enroll_uploaded_speaker_batch,
                speaker_delete_handler=self._delete_speaker_for_api,
                delete_all_handler=self._delete_all_speakers_for_api,
                vad_handler=self._analyze_speaker_recording_for_api,
            )
            ready = self._speaker_api.start()
            self._speaker_api_status = {
                "enabled": True,
                "ready": ready,
                "address": self._speaker_api.address,
                "docs": f"{self._speaker_api.address}/docs",
                "enrollment_page": (
                    f"{self._speaker_api.address}/speaker-enrollment"
                ),
                "max_batch_files": int(config.get("max_batch_files", 5)),
                "cross_identity_similarity_threshold": config.get(
                    "cross_identity_similarity_threshold",
                    0.75,
                ),
            }
        except Exception as exc:
            self._speaker_api = None
            self._upload_vad = None
            self._speaker_api_status = {
                "enabled": True,
                "ready": False,
                "error": str(exc),
            }
            logger.error("Speaker FastAPI unavailable: %s", exc, exc_info=True)

    def _get_speaker_audio_vad(self) -> Any:
        """Share speaker audio validation even when HTTP is disabled."""
        if self._upload_vad is None:
            from marsdog_voice_interaction.utils.uploaded_audio import UploadedAudioVAD
            audio_config = (
                self._config.get("providers", {}).get("audio", {}).get("config", {})
            )
            self._upload_vad = UploadedAudioVAD(audio_config)
        return self._upload_vad

    def _analyze_speaker_recording_for_api(
        self, audio_bytes: bytes
    ) -> dict[str, Any]:
        try:
            return self._get_speaker_audio_vad().analyze_wav(audio_bytes)
        except ValueError as exc:
            return {"ok": False, "status": 422, "error": str(exc)}
        except Exception as exc:
            logger.error("Speaker recording VAD failed: %s", exc, exc_info=True)
            return {"ok": False, "status": 503, "error": "录音 VAD 不可用"}

    def _enroll_uploaded_speaker(
        self,
        name: str,
        audio_bytes: bytes,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        if self._upload_vad is None:
            result = {"ok": False, "error": "上传音频 VAD 不可用"}
        else:
            with self._speaker_operation_lock:
                result = self._enrollment.enroll_speaker_from_audio(
                    name,
                    audio_bytes,
                    vad=self._upload_vad,
                )
                if result.get("ok"):
                    self._sync_speaker_registry()
        self._trace(
            "speaker_api_upload",
            result="success" if result.get("ok") else "failure",
            speaker_name=str(result.get("name", name)),
            shots=int(result.get("shots", 0)),
            sample_id=int(result.get("sample_id", 0)),
            sample_key=str(result.get("sample_key", "")),
            code=str(result.get("code", "")),
            source_sample_rate=int(result.get("source_sample_rate", 0)),
            stored_sample_rate=int(result.get("stored_sample_rate", 0)),
            source_duration_ms=float(result.get("source_duration_ms", 0.0)),
            speech_duration_ms=float(result.get("speech_duration_ms", 0.0)),
            segment_count=int(result.get("segment_count", 0)),
            audio_valid=bool(result.get("audio_valid", False)),
            has_effective_speech=bool(
                result.get("has_effective_speech", False)
            ),
            conflicting_speaker=str(
                result.get("conflicting_speaker", "")
            ),
            similarity=float(result.get("similarity", 0.0)),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            error=str(result.get("error", "")),
        )
        return result

    def _enroll_uploaded_speaker_batch(
        self,
        name: str,
        audio_items: list[bytes],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        if self._upload_vad is None:
            result = {"ok": False, "error": "上传音频 VAD 不可用"}
        else:
            with self._speaker_operation_lock:
                result = self._enrollment.enroll_speaker_batch_from_audio(
                    name,
                    audio_items,
                    vad=self._upload_vad,
                )
                if result.get("ok"):
                    self._sync_speaker_registry()
        self._trace(
            "speaker_api_upload",
            operation="batch_add",
            result="success" if result.get("ok") else "failure",
            speaker_name=str(result.get("name", name)),
            requested_count=len(audio_items),
            added_count=int(result.get("added_count", 0)),
            shots=int(result.get("shots", 0)),
            sample_ids=list(result.get("sample_ids", [])),
            code=str(result.get("code", "")),
            conflicting_speaker=str(
                result.get("conflicting_speaker", "")
            ),
            similarity=float(result.get("similarity", 0.0)),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            error=str(result.get("error", "")),
        )
        return result

    def _list_speakers_for_api(self) -> dict[str, Any]:
        started = time.perf_counter()
        with self._speaker_operation_lock:
            result = self._enrollment.list_speaker_records()
        self._trace(
            "speaker_management",
            operation="list",
            result="success",
            speaker_count=int(result.get("count", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
        )
        return result

    def _list_speaker_samples_for_api(self, name: str) -> dict[str, Any]:
        started = time.perf_counter()
        with self._speaker_operation_lock:
            result = self._enrollment.list_speaker_samples(name)
        self._trace(
            "speaker_management",
            operation="sample_list",
            result="success" if result.get("ok") else "failure",
            speaker_name=str(result.get("name", name)),
            shots=int(result.get("shots", 0)),
            sample_ids=list(result.get("sample_ids", [])),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            error=str(result.get("error", "")),
        )
        return result

    def _get_speaker_sample_for_api(
        self,
        name: str,
        sample_id: int,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        with self._speaker_operation_lock:
            result = self._enrollment.get_speaker_sample(name, sample_id)
        self._trace(
            "speaker_management",
            operation="sample_get",
            result="success" if result.get("ok") else "failure",
            speaker_name=str(result.get("name", name)),
            sample_id=int(result.get("sample_id", sample_id)),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            error=str(result.get("error", "")),
        )
        return result

    def _replace_speaker_sample_for_api(
        self,
        name: str,
        sample_id: int,
        audio_bytes: bytes,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        if self._upload_vad is None:
            result = {"ok": False, "error": "上传音频 VAD 不可用"}
        else:
            with self._speaker_operation_lock:
                result = self._enrollment.replace_speaker_sample(
                    name,
                    sample_id,
                    audio_bytes,
                    vad=self._upload_vad,
                )
                if result.get("ok"):
                    self._sync_speaker_registry()
        self._trace(
            "speaker_management",
            operation="sample_replace",
            result="success" if result.get("ok") else "failure",
            speaker_name=str(result.get("name", name)),
            sample_id=int(result.get("sample_id", sample_id)),
            shots=int(result.get("shots", 0)),
            code=str(result.get("code", "")),
            source_sample_rate=int(result.get("source_sample_rate", 0)),
            stored_sample_rate=int(result.get("stored_sample_rate", 0)),
            source_duration_ms=float(result.get("source_duration_ms", 0.0)),
            speech_duration_ms=float(result.get("speech_duration_ms", 0.0)),
            segment_count=int(result.get("segment_count", 0)),
            audio_valid=bool(result.get("audio_valid", False)),
            has_effective_speech=bool(
                result.get("has_effective_speech", False)
            ),
            conflicting_speaker=str(
                result.get("conflicting_speaker", "")
            ),
            similarity=float(result.get("similarity", 0.0)),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            error=str(result.get("error", "")),
        )
        return result

    def _delete_speaker_sample_for_api(
        self,
        name: str,
        sample_id: int,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        with self._speaker_operation_lock:
            result = self._enrollment.delete_speaker_sample(name, sample_id)
            if result.get("ok"):
                self._sync_speaker_registry()
        self._trace(
            "speaker_management",
            operation="sample_delete",
            result="success" if result.get("ok") else "failure",
            speaker_name=str(result.get("name", name)),
            sample_id=int(result.get("deleted_sample_id", sample_id)),
            shots=int(result.get("shots", 0)),
            speaker_removed=bool(result.get("speaker_removed", False)),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            error=str(result.get("error", "")),
        )
        return result

    def _delete_speaker_for_api(self, name: str) -> dict[str, Any]:
        started = time.perf_counter()
        with self._speaker_operation_lock:
            result = self._enrollment.delete_speaker(name)
            if result.get("ok"):
                self._sync_speaker_registry()
        self._trace(
            "speaker_management",
            operation="speaker_delete_all_samples",
            result="success" if result.get("ok") else "failure",
            speaker_name=str(result.get("name", name)),
            deleted_count=int(result.get("deleted_count", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            error=str(result.get("error", "")),
        )
        return result

    def _delete_all_speakers_for_api(self) -> dict[str, Any]:
        started = time.perf_counter()
        with self._speaker_operation_lock:
            result = self._enrollment.delete_all_speakers()
            if result.get("ok"):
                self._sync_speaker_registry()
        self._trace(
            "speaker_management",
            operation="delete_all_speakers",
            result="success" if result.get("ok") else "failure",
            deleted_speaker_count=int(
                result.get("deleted_speaker_count", 0)
            ),
            deleted_sample_count=int(result.get("deleted_sample_count", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            error=str(result.get("error", "")),
        )
        return result

    def _init_providers(self) -> None:
        providers = self._config.get("providers", {})
        mock = self._config.get("mock", {})
        if mock.get("enabled") and mock.get("mode") == "event":
            from marsdog_voice_interaction.providers.mock_event import (
                MockEventProvider,
            )
            provider = MockEventProvider(mock)
            provider.start()
            self._providers["mock_event"] = provider
            return

        self._providers["wakeup"] = self._build_wakeup(
            providers.get("wakeup", {})
        )
        self._providers["audio"] = self._build_audio(
            providers.get("audio", {})
        )
        self._providers["kws"] = self._build_kws(
            providers.get("kws", {})
        )
        audio = self._providers.get("audio")
        kws = self._providers.get("kws")
        if (
            audio is not None
            and kws is not None
            and kws.is_available()
            and hasattr(audio, "set_chunk_callback")
        ):
            audio.set_chunk_callback(  # type: ignore[attr-defined]
                kws.accept_waveform,  # type: ignore[attr-defined]
            )
        self._providers["asr"] = self._build_asr(providers.get("asr", {}))
        self._providers["speaker"] = self._build_speaker(
            providers.get("speaker", {})
        )

        rule_config = providers.get("intent_rule", {})
        if rule_config.get("enabled", True):
            from marsdog_voice_interaction.providers.rule_intent import (
                RuleIntentProvider,
            )
            rule = RuleIntentProvider(rule_config.get("config", {}))
            rule.start()
            self._providers["intent_rule"] = rule

        from marsdog_voice_interaction.providers.intent_factory import create_intent_provider
        llm = create_intent_provider(providers.get("intent_llm", {}))
        if llm is not None:
            llm.start()
            self._providers["intent_llm"] = llm

    def _build_wakeup(self, section: dict[str, Any]) -> BaseProvider | None:
        if not section.get("enabled", True):
            return None
        config = section.get("config", {})
        if section.get("type", "xfyun_serial") == "xfyun_serial":
            from marsdog_voice_interaction.providers.wakeup_xfyun_serial import (
                WakeupXFYunSerialProvider,
            )
            provider: BaseProvider = WakeupXFYunSerialProvider(config)
            provider.start()
            if provider.is_available():
                return provider
            if not self._config.get("mock", {}).get("enabled", False):
                # Keep the real provider in production mode. It owns the
                # reconnect policy and may recover when the USB device returns.
                return provider
        from marsdog_voice_interaction.providers.mock_wakeup import (
            MockWakeupProvider,
        )
        fallback_config = dict(config)
        fallback_config.update({
            "enable_mock_interaction": True,
            "mock_enabled": True,
            "mock_interaction_interval_sec": float(
                self._config.get("mock", {}).get("event_interval_sec", 5)
            ),
        })
        provider = MockWakeupProvider(fallback_config)
        provider.start()
        return provider

    def _build_audio(self, section: dict[str, Any]) -> BaseProvider | None:
        if not section.get("enabled", True):
            return None
        config = dict(section.get("config", {}))
        config["audio_debug"] = dict(self._config.get("audio_debug", {}))
        if section.get("type", "sherpa") == "sherpa":
            from marsdog_voice_interaction.providers.audio_sherpa import (
                AudioSherpaProvider,
            )
            provider: BaseProvider = AudioSherpaProvider(config)
            provider.start()
            if provider.is_available():
                return provider
        from marsdog_voice_interaction.providers.mock_audio import MockAudioProvider
        config["mock_event_interval_sec"] = float(
            self._config.get("mock", {}).get("event_interval_sec", 5)
        )
        provider = MockAudioProvider(config)
        provider.start()
        return provider

    @staticmethod
    def _build_kws(section: dict[str, Any]) -> BaseProvider | None:
        if not section.get("enabled", False):
            return None
        if section.get("type", "sherpa") != "sherpa":
            logger.warning("Unsupported KWS provider type: %s", section.get("type"))
            return None
        from marsdog_voice_interaction.providers.kws_sherpa import (
            KWSSherpaProvider,
        )
        provider: BaseProvider = KWSSherpaProvider(section.get("config", {}))
        provider.start()
        return provider

    def _build_asr(self, section: dict[str, Any]) -> BaseProvider | None:
        if not section.get("enabled", True):
            return None
        config = dict(section.get("config", {}))
        config["audio_debug"] = dict(self._config.get("audio_debug", {}))
        if section.get("type", "sherpa") == "sherpa":
            from marsdog_voice_interaction.providers.asr_sherpa import (
                ASRSherpaProvider,
            )
            provider: BaseProvider = ASRSherpaProvider(config)
            provider.start()
            if provider.is_available():
                return provider
        from marsdog_voice_interaction.providers.mock_asr import MockASRProvider
        provider = MockASRProvider(config)
        provider.start()
        return provider

    @staticmethod
    def _build_speaker(section: dict[str, Any]) -> BaseProvider | None:
        if not section.get("enabled", True):
            return None
        config = section.get("config", {})
        if section.get("type", "sherpa") == "sherpa":
            from marsdog_voice_interaction.providers.speaker_sherpa import (
                SpeakerSherpaProvider,
            )
            provider: BaseProvider = SpeakerSherpaProvider(config)
            provider.start()
            return provider
        if section.get("type", "sherpa") != "mock":
            raise ValueError("Unsupported speaker provider type")
        from marsdog_voice_interaction.providers.mock_speaker import (
            MockSpeakerProvider,
        )
        provider = MockSpeakerProvider(config)
        provider.start()
        return provider

    def _begin_interaction(
        self,
        interaction_id: str | None = None,
        *,
        source: str = "unknown",
    ) -> str:
        return interaction_session.begin_interaction(self, interaction_id, source=source)

    def _refresh_interaction_activity(
        self,
        now: float | None = None,
        *,
        reason: str = "activity",
    ) -> None:
        return interaction_session.refresh_interaction_activity(self, now, reason=reason)

    def _is_interaction_active(self) -> bool:
        return interaction_session.is_interaction_active(self)

    def _prune_interaction_holds_locked(self, now: float) -> None:
        return interaction_session.prune_interaction_holds_locked(self, now, logger=logger)

    def _timeout_interaction_id(self, now: float) -> str:
        return interaction_session.timeout_interaction_id(self, now)

    def _poll_direct_mock(self, direct_mock: BaseProvider) -> None:
        """Run event mock through the same bounded session lifecycle."""
        event = direct_mock.poll_event()  # type: ignore[attr-defined]
        if event is not None:
            event_type = str(event.get("event_type", ""))
            if event_type == EVT_VOICE_WAKEUP:
                was_active = self._is_interaction_active()
                self._begin_interaction(source="mock_event")
                if was_active:
                    self._state_machine.trigger(Trigger.WAKEUP)
                    self._refresh_interaction_activity(reason="wakeup")
                self._latest_wake_id = uuid.uuid4().hex
                event["wake_id"] = self._latest_wake_id
                event["speaker_status"] = (
                    "pending" if self._wake_speaker_enabled else "unavailable"
                )
                event["speaker_role"] = "undetermined"
                self._publish(event)
                if self._wake_speaker_enabled:
                    self._publish_wake_identity_result(
                        self._interaction_id, self._latest_wake_id,
                        {"speaker_id": "unknown", "confidence": 0.0,
                         "speaker_status": "unavailable", "speaker_role": "undetermined",
                         "reason": "mock_has_no_wake_audio"},
                    )
            elif not self._is_interaction_active():
                logger.debug(
                    "Ignoring direct mock event outside an interaction: %s",
                    event_type,
                )
                complete = getattr(direct_mock, "complete_interaction", None)
                if callable(complete):
                    complete()
            else:
                self._state_machine.trigger(Trigger.SPEECH_START)
                should_execute = bool(
                    event.get("should_trigger_behavior_tree")
                )
                if should_execute:
                    self._state_machine.trigger(Trigger.INTENT_PARSED)
                else:
                    self._state_machine.trigger(Trigger.SPEECH_END)
                event["state"] = self._state_machine.state.value
                event["previous_state"] = (
                    self._state_machine.previous_state.value
                )
                event.setdefault("utterance_id", uuid.uuid4().hex)
                self._publish(event)
                if getattr(self, "_refresh_on_any_speech", False):
                    # Test mode: every mock interaction event counts as
                    # activity, even without ASR text.
                    self._refresh_interaction_activity(reason="mock_event")
                else:
                    self._refresh_for_asr_result(event.get("asr_text"))

        timed_out_id = self._timeout_interaction_id(time.monotonic())
        if timed_out_id:
            self._end_interaction(
                "interaction_timeout",
                expected_interaction_id=timed_out_id,
            )

    def _poll(self) -> None:
        direct_mock = self._providers.get("mock_event")
        if direct_mock is not None:
            self._poll_direct_mock(direct_mock)
            return

        audio = self._providers.get("audio")
        wakeup = self._providers.get("wakeup")
        if wakeup is not None:
            wake_event = wakeup.poll_event()  # type: ignore[attr-defined]
            if wake_event is not None and self._handle_wakeup(wake_event, audio):
                return
        self._poll_wake_identity_result()
        if self._poll_pending_intent(audio):
            return
        if audio is not None and hasattr(audio, "poll_result"):
            if audio.is_capturing():  # type: ignore[attr-defined]
                session = self._enrollment.speaker_session
                enrollment_active = (
                    session is not None and not session.done
                )
                if not self._is_interaction_active() and not enrollment_active:
                    # A timeout or stop request must not leave a stale capture
                    # starving the wakeup provider at the end of this method.
                    self._cancel_audio_capture(
                        audio, preserve_microphone=self._wake_speaker_enabled
                    )
                else:
                    self._poll_kws_events()
                    result = audio.poll_result()  # type: ignore[attr-defined]
                    if result is not None:
                        self._poll_kws_events()
                        self._finish_kws_utterance()
                        if not result.get("utterance_id"):
                            # A provider that reports its own utterance ID is
                            # authoritative. A refused start advances the
                            # tracker while the previous worker keeps
                            # capturing; relabelling that audio with the new
                            # ID would misattribute it in traces, debug audio
                            # and downstream events.
                            tracker_id = self._command_tracker.utterance_id
                            if tracker_id:
                                result["utterance_id"] = tracker_id
                        utterance_id = (
                            str(result.get("utterance_id") or "") or None
                        )
                        self._latest_audio = result
                        has_voice = bool(result.get("has_voice", True))
                        capture_started = getattr(
                            self,
                            "_utterance_started_monotonic",
                            0.0,
                        )
                        capture_latency_ms = (
                            (time.perf_counter() - capture_started) * 1000.0
                            if capture_started else 0.0
                        )
                        self._trace(
                            "stage_complete",
                            stage="vad_capture",
                            result="voice" if has_voice else "silence",
                            capture_end_reason=str(result.get("capture_end_reason", "")),
                            interaction_id=self._interaction_id,
                            utterance_id=utterance_id,
                            latency_ms=round(capture_latency_ms, 2),
                            audio_duration_ms=round(
                                float(result.get("duration_ms", 0.0)),
                                2,
                            ),
                        )
                        if enrollment_active:
                            self._process_enrollment_audio(result)
                        elif has_voice:
                            wake_before_speech = self._latest_wake_id
                            if getattr(self, "_refresh_on_any_speech", False):
                                # Test mode: any VAD-confirmed speech keeps the
                                # session alive, even when ASR yields nothing.
                                # A later non-empty ASR result overwrites the reason
                                # with a more precise one.
                                self._refresh_interaction_activity(
                                    reason="vad_speech"
                                )
                            self._process_speech(
                                result,
                                utterance_id,
                            )
                            if getattr(self, "_pending_intent", None) is not None:
                                return
                            if self._latest_wake_id != wake_before_speech:
                                # A hardware wake arrived during ASR/speaker
                                # processing and already started a new turn.
                                return
                        else:
                            logger.debug(
                                "VAD silence result; idle timer remains at %.3f",
                                self._last_interaction_time,
                            )
                        self._finish_speech_capture(audio)
                        return
                    if enrollment_active:
                        return

            session = self._enrollment.speaker_session
            if session is not None and not session.done:
                audio.start_capture()  # type: ignore[attr-defined]
                return

        timed_out_id = self._timeout_interaction_id(time.monotonic())
        if timed_out_id and not self._audio_speech_active(audio):
            self._end_interaction(
                "interaction_timeout",
                expected_interaction_id=timed_out_id,
            )
            return

        if (
            audio is not None and hasattr(audio, "start_capture")
            and self._is_interaction_active()
            and not audio.is_capturing()  # type: ignore[attr-defined]
        ):
            now = time.monotonic()
            if now - self._last_capture_retry >= 0.5:
                self._last_capture_retry = now
                self._start_interaction_capture(audio)

    def _finish_speech_capture(self, audio: BaseProvider | None) -> None:
        self._command_tracker.finish()
        timed_out_id = self._timeout_interaction_id(
            time.monotonic()
        )
        if timed_out_id:
            self._end_interaction(
                "interaction_timeout",
                expected_interaction_id=timed_out_id,
            )
        elif audio is not None and self._is_interaction_active():
            self._start_interaction_capture(audio)
        elif not (self._enrollment.speaker_session is not None
                  and not self._enrollment.speaker_session.done):
            self._cancel_audio_capture(
                audio, preserve_microphone=self._wake_speaker_enabled
            )

    def _poll_pending_intent(self, audio: BaseProvider | None) -> bool:
        """Only model computation runs off-thread; completion stays on ROS."""
        pending = getattr(self, "_pending_intent", None)
        if pending is None:
            return False
        interaction_id, context, future = pending
        timed_out_id = self._timeout_interaction_id(time.monotonic())
        if timed_out_id:
            self._end_interaction("interaction_timeout", expected_interaction_id=timed_out_id)
        if not future.done():
            # Keep one task in flight even after stop. Never queue another model
            # call or capture a new utterance against shared provider state.
            return True
        self._pending_intent = None
        with self._interaction_lock:
            current = (self._interaction_active and self._interaction_id == interaction_id
                       and self._latest_wake_id == context["utterance_wake_id"])
        if not current:
            self._trace("intent_discard", interaction_id=interaction_id,
                        utterance_id=context["utterance_id"], reason="session_or_wake_changed")
            return False
        try:
            parsed_intent = future.result()
        except Exception as exc:
            logger.error("Background intent failed: %s", exc)
            parsed_intent = None
        self._complete_intent(parsed_intent, **context)
        if self._latest_wake_id == context["utterance_wake_id"]:
            self._finish_speech_capture(audio)
        return True

    def _handle_wakeup(self, event: dict[str, Any], audio: BaseProvider | None) -> bool:
        """Accept one fresh hardware wake, including during an active VAD turn."""
        now = time.monotonic()
        try:
            received = float(event.get("received_monotonic", now))
        except (TypeError, ValueError):
            return False
        if not math.isfinite(received) or received > now + 0.2:
            return False
        if now - received > self._wake_event_max_age_sec:
            self._trace("wakeup_ignored", result="stale", age_sec=now - received)
            return False
        session = self._enrollment.speaker_session
        if session is not None and not session.done:
            self._trace("wakeup_ignored", result="speaker_enrollment_active")
            return False
        wake_word = str(event.get("wake_word", ""))
        if (wake_word == self._last_wake_word
                and received - self._last_wake_received < self._wake_debounce_sec):
            self._trace("wakeup_ignored", result="debounced")
            return False
        self._last_wake_received = received
        self._last_wake_word = wake_word
        was_active = self._is_interaction_active()
        interaction_id = self._begin_interaction(source="wakeup")
        if was_active:
            self._state_machine.trigger(Trigger.WAKEUP)
            self._refresh_interaction_activity(now=now, reason="wakeup")
        wake_id = uuid.uuid4().hex
        self._latest_wake_id = wake_id
        self._latest_audio = None
        if self._pending_wake_identity is not None:
            self._pending_wake_identity[2].cancel()
            self._pending_wake_identity = None
        event = dict(event)
        event.update({
            "event_type": EVT_VOICE_WAKEUP, "wake_id": wake_id,
            "speaker_id": "unknown", "speaker_role": "undetermined",
            "speaker_status": (
                "pending" if self._wake_speaker_enabled else "unavailable"
            ),
        })
        self._publish(event)
        wake_audio: dict[str, Any] | None = None
        if self._wake_speaker_enabled and audio is not None:
            snapshot = getattr(audio, "wake_audio_snapshot", None)
            if callable(snapshot):
                try:
                    duration = float(event.get("wake_duration_sec", 0.0) or 0.0)
                    if not math.isfinite(duration) or duration < 0.0:
                        duration = 0.0
                    window = min(self._wake_audio_window_sec,
                                 max(1.5, duration + 0.35))
                    wake_audio = snapshot(received, window)
                except Exception as exc:
                    logger.warning("Wake audio snapshot unavailable: %s", exc)
        if audio is not None and hasattr(audio, "start_capture"):
            if audio.is_capturing():  # type: ignore[attr-defined]
                self._cancel_audio_capture(audio, preserve_microphone=True)
            self._finish_kws_utterance()
            self._command_tracker.finish()
            prepare = getattr(audio, "prepare_for_wakeup", None)
            if callable(prepare):
                try:
                    prepare(received)
                except Exception as exc:
                    logger.warning("Wake audio handoff failed: %s", exc)
            self._start_interaction_capture(audio)
        if self._wake_speaker_enabled and wake_audio is not None:
            future = self._wake_identity_executor.submit(
                self._identify_wake_speaker, wake_audio
            )
            self._pending_wake_identity = (interaction_id, wake_id, future)
        elif self._wake_speaker_enabled:
            self._publish_wake_identity_result(
                interaction_id, wake_id,
                {"speaker_id": "unknown", "confidence": 0.0,
                 "speaker_role": "undetermined", "speaker_status": "unavailable",
                 "reason": "wake_audio_unavailable"},
            )
        self._trace(
            "wakeup_accepted", result="refreshed" if was_active else "started",
            interaction_id=interaction_id, wake_id=wake_id,
        )
        return True

    def _wakeup_supersedes_utterance(self, wake_id: str) -> bool:
        """Check serial wake notifications before publishing an old turn."""
        if getattr(self, "_latest_wake_id", "") != wake_id:
            return True
        wakeup = self._providers.get("wakeup")
        if wakeup is None:
            return False
        event = wakeup.poll_event()  # type: ignore[attr-defined]
        if event is None:
            return False
        return self._handle_wakeup(event, self._providers.get("audio"))

    def _identify_wake_speaker(self, audio_data: dict[str, Any]) -> dict[str, Any]:
        samples = audio_data.get("audio_samples")
        if samples is None or len(samples) == 0:
            return {"speaker_id": "unknown", "confidence": 0.0,
                    "speaker_role": "undetermined", "speaker_status": "insufficient_audio",
                    "reason": "no_wake_audio"}
        speaker = self._providers.get("speaker")
        if speaker is None or not speaker.is_available():
            return {"speaker_id": "unknown", "confidence": 0.0,
                    "speaker_role": "undetermined", "speaker_status": "unavailable",
                    "reason": "speaker_unavailable"}
        try:
            from marsdog_voice_interaction.utils.uploaded_audio import encode_pcm16_wav
            trimmed = self._get_speaker_audio_vad().trim_wav(
                encode_pcm16_wav(samples, int(audio_data.get("sample_rate", 16000)))
            )
            if trimmed.segment_count != 1:
                return {"speaker_id": "unknown", "confidence": 0.0,
                        "speaker_role": "undetermined", "speaker_status": "ambiguous",
                        "reason": "multiple_wake_speech_segments"}
        except ValueError as exc:
            return {"speaker_id": "unknown", "confidence": 0.0,
                    "speaker_role": "undetermined", "speaker_status": "insufficient_audio",
                    "reason": str(exc)}
        except Exception as exc:
            logger.warning("Wake speaker VAD unavailable: %s", exc)
            return {"speaker_id": "unknown", "confidence": 0.0,
                    "speaker_role": "undetermined", "speaker_status": "unavailable",
                    "reason": "wake_vad_unavailable"}
        try:
            with self._speaker_operation_lock:
                result = speaker.verify({
                    "audio_samples": trimmed.samples,
                    "sample_rate": trimmed.sample_rate,
                    "has_voice": True,
                })  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Wake speaker verification failed: %s", exc)
            result = {"speaker_id": "unknown", "confidence": 0.0,
                      "reason": "speaker_error"}
        speaker_id = str(result.get("speaker_id", "unknown"))
        reason = str(result.get("reason", ""))
        role = speaker_identity_role(speaker_id)
        if role in {"owner", "family"} and bool(result.get("matched")):
            speaker_role, status = role, "matched"
        elif reason == "below_threshold":
            speaker_role, status = "stranger", "no_match"
        else:
            speaker_role = "undetermined"
            status = "ambiguous" if reason == "ambiguous_identity" else "unavailable"
            speaker_id = "unknown"
        return {
            "speaker_id": speaker_id,
            "confidence": float(result.get("confidence", 0.0)),
            "speaker_role": speaker_role,
            "speaker_status": status,
            "reason": reason,
        }

    def _poll_wake_identity_result(self) -> None:
        pending = self._pending_wake_identity
        if pending is None or not pending[2].done():
            return
        self._pending_wake_identity = None
        interaction_id, wake_id, future = pending
        try:
            result = future.result()
        except Exception as exc:
            logger.warning("Wake identity worker failed: %s", exc)
            result = {"speaker_id": "unknown", "confidence": 0.0,
                      "speaker_role": "undetermined", "speaker_status": "unavailable",
                      "reason": "wake_identity_error"}
        self._publish_wake_identity_result(interaction_id, wake_id, result)

    def _publish_wake_identity_result(
        self, interaction_id: str, wake_id: str, result: dict[str, Any],
    ) -> None:
        if (not self._is_interaction_active()
                or interaction_id != self._interaction_id
                or wake_id != self._latest_wake_id):
            return
        self._publish({
            "event_type": EVT_VOICE_WAKE_SPEAKER_RESULT,
            "interaction_id": interaction_id, "wake_id": wake_id,
            "speaker_id": result.get("speaker_id", "unknown"),
            "speaker_confidence": result.get("confidence", 0.0),
            "speaker_role": result.get("speaker_role", "undetermined"),
            "speaker_status": result.get("speaker_status", "unavailable"),
            "speaker_reason": result.get("reason", ""),
        })

    @staticmethod
    def _resolve_max_interaction_duration(
        idle_timeout: float,
        raw: Any,
    ) -> float:
        """Return the absolute session cap in seconds; 0 disables it.

        A non-positive configured value means "no absolute cap" and stays 0.0
        so the truthiness check in _timeout_interaction_id skips it. Any
        positive value is clamped to at least the idle timeout, so the hard
        deadline can never fire before the idle deadline would. Unparsable or
        non-finite values fall back to the production default — a bad value
        must not silently disable the cap.
        """
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 120.0
        if not math.isfinite(value):
            value = 120.0
        if value <= 0.0:
            return 0.0
        return max(idle_timeout, value)

    @staticmethod
    def _audio_speech_active(audio: BaseProvider | None) -> bool:
        """Avoid ending a session in the middle of an unfinished utterance."""
        is_speech_active = getattr(audio, "is_speech_active", None)
        return bool(is_speech_active()) if callable(is_speech_active) else False

    def _effective_kws_arbitration(self) -> dict[str, Any]:
        """Return policy defaults for lightweight test harnesses as well."""

        return dict(
            getattr(
                self,
                "_kws_arbitration",
                {
                    "publish_mode": "deferred",
                    "arbitration_mode": "exclusive",
                    "asr_long_text_wins": True,
                    "kws_fallback_on_asr_empty": False,
                    "short_requires_asr_agreement": True,
                    "short_max_chars_zh": 2,
                    "short_max_words_en": 2,
                    "priority_command_keys": (),
                    "priority_asr_aliases": {},
                },
            )
        )

    def _is_short_asr_text(self, raw_text: str, language: str) -> bool:
        return speech_pipeline.is_short_asr_text(self, raw_text, language)

    def _select_kws_candidate(
        self,
        *,
        text: str,
        raw_text: str,
        language: str,
        direct_match: Any = None,
    ) -> tuple[dict[str, Any] | None, str]:
        return speech_pipeline.select_kws_candidate(self, text=text, raw_text=raw_text, language=language, direct_match=direct_match)

    def _refresh_for_asr_result(self, text: Any) -> bool:
        """Refresh on non-blank ASR text, before semantic routing or rejection."""
        if not isinstance(text, str) or not text.strip():
            return False
        self._refresh_interaction_activity(reason="asr_result")
        return True

    def _trace_recognition_arbitration(
        self,
        *,
        result: str,
        reason: str,
        text: str,
        language: str,
        utterance_id: str,
        direct_match: Any = None,
        started: float,
    ) -> None:
        candidates = self._command_tracker.kws_candidates
        self._trace(
            "stage_complete",
            stage="recognition_arbitration",
            result=result,
            interaction_id=self._interaction_id,
            utterance_id=utterance_id,
            selected_source=(
                "kws" if result == "kws_selected"
                else "asr_pipeline" if result == "asr_selected"
                else "none"
            ),
            reason=reason,
            asr_text=text,
            language=language,
            asr_text_length=len(text),
            asr_is_short=(
                self._is_short_asr_text(text, language) if text else False
            ),
            kws_candidate_count=len(candidates),
            kws_candidate_keys=[
                str(event.get("action", "")) for event in candidates
            ],
            kws_candidate_event_types=[
                str(event.get("event_type", "")) for event in candidates
            ],
            catalog_event_type=(
                direct_match.event_type if direct_match is not None else ""
            ),
            latency_ms=round(
                (time.perf_counter() - started) * 1000.0,
                3,
            ),
        )

    def _publish_selected_kws_candidate(
        self,
        candidate: dict[str, Any],
        *,
        reason: str,
        text: str,
        language: str,
        utterance_id: str,
        speaker_id: str,
        speaker_confidence: float,
        pipeline_started: float,
    ) -> bool:
        return speech_pipeline.publish_selected_kws_candidate(self, candidate, reason=reason, text=text, language=language, utterance_id=utterance_id, speaker_id=speaker_id, speaker_confidence=speaker_confidence, pipeline_started=pipeline_started)

    def _process_speech(
        self,
        audio_data: dict[str, Any],
        utterance_id: str | None = None,
    ) -> bool:
        return speech_pipeline.process_speech(self, audio_data, utterance_id, ThreadPoolExecutor=ThreadPoolExecutor, logger=logger, speaker_to_voice_event=speaker_to_voice_event)

    def _complete_intent(
        self, parsed_intent: dict[str, Any] | None, *, text: str,
        utterance_id: str, utterance_wake_id: str, asr_result: dict[str, Any],
        speaker_id: str, confidence: float, pipeline_started: float, intent_started: float,
    ) -> bool:
        return speech_pipeline.complete_intent(self, parsed_intent, text=text, utterance_id=utterance_id, utterance_wake_id=utterance_wake_id, asr_result=asr_result, speaker_id=speaker_id, confidence=confidence, pipeline_started=pipeline_started, intent_started=intent_started, _UNKNOWN_INTENT=_UNKNOWN_INTENT, object_resolution_slots=object_resolution_slots, route_classification_events=route_classification_events)

    def _start_interaction_capture(self, audio: BaseProvider) -> None:
        if getattr(self, "_pending_intent", None) is not None:
            return
        """Allocate an utterance ID, reset KWS, then start microphone capture."""
        utterance_id = uuid.uuid4().hex
        self._command_tracker.begin(utterance_id)
        self._utterance_started_monotonic = time.perf_counter()
        kws = self._providers.get("kws")
        if kws is not None and kws.is_available():
            kws.start_utterance()  # type: ignore[attr-defined]
        set_utterance_id = getattr(audio, "set_utterance_id", None)
        if callable(set_utterance_id):
            set_utterance_id(utterance_id)
        started = audio.start_capture()  # type: ignore[attr-defined]
        if started is False:
            logger.error(
                "VAD capture refused to start; the microphone stays closed "
                "for utterance_id=%s",
                utterance_id,
            )
            # This utterance never opened a capture, so drop its ID rather
            # than leave it claiming the audio of whichever worker still
            # holds the device. poll_result() now reports that worker's own
            # utterance ID, and an empty tracker keeps this refused attempt
            # from being treated as the active utterance.
            self._command_tracker.finish()
            self._utterance_started_monotonic = 0.0
        self._trace(
            "stage_start",
            stage="vad_capture",
            result="ignored" if started is False else "started",
            interaction_id=self._interaction_id,
            utterance_id=utterance_id,
        )

    def _cancel_audio_capture(
        self, audio: BaseProvider | None = None, *, preserve_microphone: bool = False,
    ) -> None:
        """Stop an in-flight capture without shutting down the provider."""
        audio = audio or self._providers.get("audio")
        if audio is None:
            return
        cancel_capture = getattr(audio, "cancel_capture", None)
        if callable(cancel_capture):
            try:
                try:
                    stopped = cancel_capture(preserve_microphone=preserve_microphone)
                except TypeError:
                    stopped = cancel_capture()
                if stopped is False:
                    logger.error(
                        "Audio capture cancellation timed out; the worker "
                        "was detached and is still shutting down"
                    )
            except Exception as exc:
                logger.error("Audio capture cancellation failed: %s", exc)
            return
        if (
            hasattr(audio, "is_capturing")
            and audio.is_capturing()  # type: ignore[attr-defined]
        ):
            logger.error(
                "Audio provider has no cancel_capture(); "
                "wakeup remains blocked until capture exits"
            )

    def _end_interaction(
        self,
        reason: str,
        *,
        expected_interaction_id: str = "",
    ) -> bool:
        """Atomically end listening and restore the wakeup polling path."""
        with self._interaction_lock:
            if (
                expected_interaction_id
                and expected_interaction_id != self._interaction_id
            ):
                return False
            if not self._interaction_active:
                self._interaction_holds.clear()
                return False
            interaction_id = self._interaction_id
            idle_elapsed_sec = max(
                0.0,
                time.monotonic() - self._last_interaction_time,
            )
            last_activity_reason = getattr(
                self,
                "_last_interaction_activity_reason",
                "",
            )
            self._interaction_active = False
            self._interaction_started_time = 0.0
            self._latest_wake_id = ""
            if self._pending_wake_identity is not None:
                self._pending_wake_identity[2].cancel()
                self._pending_wake_identity = None
            self._interaction_holds.clear()
            self._finish_kws_utterance()
            self._command_tracker.finish()
            self._state_machine.trigger(Trigger.TIMEOUT)
            self._publish({
                "event_type": EVT_STATE_CHANGED,
                "interaction_id": interaction_id,
                "state": "idle",
                "state_reason": reason,
            })
            # Cancel after the idle state is out: teardown can wait on the
            # worker's join budget, and nothing should delay wakeup recovery.
            self._cancel_audio_capture(
                preserve_microphone=self._wake_speaker_enabled
            )
            self._interaction_id = ""
        direct_mock = self._providers.get("mock_event")
        complete = getattr(direct_mock, "complete_interaction", None)
        if callable(complete):
            complete()
        logger.info(
            "Interaction ended: reason=%s; wakeup polling resumed",
            reason,
        )
        self._trace(
            "interaction_end",
            result="ended",
            interaction_id=interaction_id,
            reason=reason,
            state="idle",
            idle_elapsed_sec=round(idle_elapsed_sec, 3),
            idle_timeout_sec=self._idle_timeout,
            last_activity_reason=last_activity_reason,
        )
        return True

    def _finish_kws_utterance(self) -> None:
        kws = self._providers.get("kws")
        if kws is not None and kws.is_available():
            kws.finish_utterance()  # type: ignore[attr-defined]

    def _poll_kws_events(self) -> None:
        """Cache KWS candidates; executable events wait for ASR arbitration."""
        kws = self._providers.get("kws")
        if (
            kws is None
            or not kws.is_available()
            or not self._command_tracker.is_active
        ):
            return
        while True:
            event = kws.poll_event()  # type: ignore[attr-defined]
            if event is None:
                return
            event_type = str(event.get("event_type", ""))
            command_key = str(event.get("action", "")).strip().upper()
            command_lexicon = getattr(self, "_command_lexicon", None)
            catalog_command = (
                command_lexicon.get_command(command_key)
                if command_lexicon is not None and command_key
                else None
            )
            if (
                catalog_command is not None
                and catalog_command.event_type != event_type
            ):
                logger.warning(
                    "KWS/catalog event mismatch for %s: kws=%s catalog=%s",
                    command_key,
                    event_type,
                    catalog_command.event_type,
                )
                self._trace(
                    "stage_complete",
                    stage="kws",
                    result="rejected_catalog_mismatch",
                    interaction_id=self._interaction_id,
                    utterance_id=self._command_tracker.utterance_id,
                    event_type=event_type,
                    command_key=command_key,
                    catalog_event_type=catalog_command.event_type,
                )
                continue
            self._state_machine.trigger(Trigger.SPEECH_START)
            event["utterance_id"] = self._command_tracker.utterance_id
            utterance_started = getattr(
                self,
                "_utterance_started_monotonic",
                0.0,
            )
            kws_latency_ms = (
                (time.perf_counter() - utterance_started) * 1000.0
                if utterance_started else 0.0
            )
            event["latency_ms"] = round(kws_latency_ms, 2)
            if catalog_command is not None:
                event["command_id"] = catalog_command.command_id
            if not self._command_tracker.record_kws_candidate(event):
                continue
            self._trace(
                "stage_complete",
                stage="kws",
                result="candidate",
                interaction_id=self._interaction_id,
                utterance_id=self._command_tracker.utterance_id,
                event_type=event_type,
                command_key=command_key,
                candidate_count=self._command_tracker.kws_candidate_count,
                published_event_types=[],
                latency_ms=round(kws_latency_ms, 2),
            )

    def _parse_intent(
        self, text: str, *, raw_text: str | None = None,
    ) -> dict[str, Any] | None:
        return speech_pipeline.parse_intent(self, text, raw_text=raw_text, logger=logger)

    @staticmethod
    def _clean_text(text: str) -> str:
        cleaned = re.sub(
            r"""[，。！？、；：“”"'（）【】《》…—～,.!?;:()\[\]<>/\s]+""",
            "",
            text,
        ).strip()
        return normalize_chinese_numbers(cleaned)

    def _publish(self, partial: dict[str, Any]) -> None:
        value = dict(partial)
        with self._interaction_lock:
            value.setdefault("interaction_id", self._interaction_id)
            value.setdefault("wake_id", getattr(self, "_latest_wake_id", ""))
        value.setdefault("state", self._state_machine.state.value)
        value.setdefault(
            "previous_state", self._state_machine.previous_state.value
        )
        event = normalize_audio_event(value)
        message = String()
        message.data = json.dumps(event, ensure_ascii=False)
        self._audio_pub.publish(message)
        self._trace(
            "event_publish",
            result="published",
            topic=str(
                self._config.get("topics", {}).get(
                    "audio_event",
                    "/perception/audio_event",
                )
            ),
            event_type=str(event.get("event_type", "")),
            interaction_id=str(event.get("interaction_id", "")),
            utterance_id=str(event.get("utterance_id", "")),
            wake_id=str(event.get("wake_id", "")),
            state=str(event.get("state", "")),
            previous_state=str(event.get("previous_state", "")),
            state_reason=str(event.get("state_reason", "")),
            wake_word=str(event.get("wake_word", "")),
            wake_angle=round(float(event.get("wake_angle", 0.0)), 2),
            wake_confidence=round(
                float(event.get("wake_confidence", 0.0)),
                3,
            ),
            speaker_id=str(event.get("speaker_id", "")),
            speaker_role=str(event.get("speaker_role", "")),
            speaker_status=str(event.get("speaker_status", "")),
            speaker_confidence=round(
                float(event.get("speaker_confidence", 0.0)),
                3,
            ),
            social=str(event.get("social", "")),
            intent=str(event.get("intent", "")),
            action=str(event.get("action", "")),
            control=str(event.get("control", "")),
            intent_source=str(event.get("intent_source", "")),
            should_trigger_behavior_tree=bool(
                event.get("should_trigger_behavior_tree", False)
            ),
            latency_ms=round(float(event.get("latency_ms", 0.0)), 2),
            asr_text=str(event.get("asr_text", "")),
            emotion=str(event.get("emotion", "")),
            command_id=str(event.get("command_id", "")),
            intent_category=str(event.get("intent_category", "")),
            intent_confidence=round(
                float(event.get("intent_confidence", 0.0)),
                3,
            ),
            nlu_protocol=str(event.get("nlu_protocol", "")),
            raw_nlu_tag=str(event.get("raw_nlu_tag", "")),
            specific_event_type=str(
                event.get("specific_event_type", "")
            ),
            dispatch_role=str(event.get("dispatch_role", "")),
            language=str(event.get("language", "")),
            slots=event.get("slots", []),
            payload=event,
        )

    def _process_enrollment_audio(self, audio_data: dict[str, Any]) -> None:
        started = time.perf_counter()
        with self._speaker_operation_lock:
            result = self._enrollment.process_speaker_audio(
                np.asarray(
                    audio_data.get("audio_samples", []),
                    dtype=np.float32,
                ),
                int(audio_data.get("sample_rate", 16000)),
                vad=self._get_speaker_audio_vad(),
            )
            if result.get("done"):
                self._sync_speaker_registry()
        message = String()
        message.data = json.dumps(result, ensure_ascii=False)
        self._enrollment_pub.publish(message)
        self._trace(
            "enrollment_publish",
            result="complete" if result.get("done") else "progress",
            topic=str(
                self._config.get("topics", {}).get(
                    "enrollment_event",
                    "/perception/voice/enrollment_event",
                )
            ),
            interaction_id=self._interaction_id,
            speaker_id=str(result.get("speaker_id", result.get("name", ""))),
            latency_ms=round(
                (time.perf_counter() - started) * 1000.0,
                2,
            ),
            payload=result,
        )

    def _handle_task(self, request: Any, response: Any) -> Any:
        return task_service.handle_task(self, request, response, clock=time.perf_counter)

    def _hold_interaction(self, params: dict[str, Any]) -> dict[str, Any]:
        return interaction_session.hold_interaction(self, params)

    def _release_interaction_hold(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return interaction_session.release_interaction_hold(self, params)

    def _interaction_state(self) -> dict[str, Any]:
        return interaction_session.interaction_state(self)

    def _run_task(self, task_type: str, params: dict[str, Any]) -> dict[str, Any]:
        return task_router.run_task(self, task_type, params)

    @staticmethod
    def _decode_audio_params(
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        encoded = str(params.get("audio_base64", ""))
        if not encoded:
            return None
        payload = base64.b64decode(encoded, validate=True)
        from marsdog_voice_interaction.utils.uploaded_audio import normalize_pcm16_wav
        samples, sample_rate, _ = normalize_pcm16_wav(payload)
        return {
            "audio_samples": samples,
            "sample_rate": sample_rate,
            "has_voice": True,  # The caller applies VAD before verification.
        }

    def _wire_speaker_enrollment(self) -> None:
        speaker = self._providers.get("speaker")
        extractor = getattr(speaker, "_extractor", None)
        if extractor is not None:
            self._enrollment.set_speaker_extractor(extractor)

    def _sync_speaker_registry(self) -> None:
        speaker = self._providers.get("speaker")
        if speaker is not None:
            self._enrollment.sync_to_provider(speaker)

    def destroy_node(self) -> None:
        pending = getattr(self, "_pending_intent", None)
        self._pending_intent = None
        if pending is not None:
            pending[2].cancel()
        self._wake_identity_executor.shutdown(wait=True, cancel_futures=True)
        if self._speaker_api is not None:
            self._speaker_api.stop()
            self._speaker_api = None
        with self._speaker_operation_lock:
            for provider in self._providers.values():
                if provider is not None:
                    provider.stop()
        executor = getattr(self, "_intent_executor", None)
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = VoiceInteractionNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass
