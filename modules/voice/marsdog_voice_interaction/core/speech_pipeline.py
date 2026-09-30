"""ASR, speaker, intent and KWS orchestration over existing provider/session ports.

Provider algorithms, authorization and event ordering remain unchanged. Callback
factories and protocol helpers are supplied by the shell to retain old entrypoints.
"""
from __future__ import annotations
import re
import time
import uuid
from typing import Any
from .interaction_state_machine import Trigger
from ..messages.voice_event_types import EVT_VOICE_COMMAND_KNOWN


def process_speech(self, audio_data: dict[str, Any], utterance_id: str | None=None, *, ThreadPoolExecutor, logger, speaker_to_voice_event):
    pipeline_started = time.perf_counter()
    utterance_wake_id = getattr(self, "_latest_wake_id", "")
    self._state_machine.trigger(Trigger.SPEECH_START)
    utterance_id = utterance_id or uuid.uuid4().hex
    asr = self._providers.get("asr")
    speaker = self._providers.get("speaker")
    asr_started = time.perf_counter()
    asr_failed = False
    try:
        asr_result = (
            asr.transcribe(audio_data)  # type: ignore[attr-defined]
            if asr is not None else {}
        )
    except Exception as exc:
        logger.error("ASR failed: %s", exc)
        asr_result = {}
        asr_failed = True
    asr_latency_ms = (time.perf_counter() - asr_started) * 1000.0
    raw_text = str(asr_result.get("asr_text") or "")
    if self._wakeup_supersedes_utterance(utterance_wake_id):
        return False
    self._refresh_for_asr_result(raw_text)
    self._trace(
        "stage_complete",
        stage="asr",
        result=("error" if asr_failed else "ok" if raw_text else "empty"),
        interaction_id=self._interaction_id,
        utterance_id=utterance_id,
        latency_ms=round(asr_latency_ms, 2),
        language=str(asr_result.get("language", "")),
        text_length=len(raw_text),
    )

    speaker_started = time.perf_counter()
    speaker_failed = False
    try:
        with self._speaker_operation_lock:
            speaker_result = (
                speaker.verify(audio_data)  # type: ignore[attr-defined]
                if speaker is not None else {}
            )
    except Exception as exc:
        logger.error("Speaker verification failed: %s", exc)
        speaker_result = {}
        speaker_failed = True
    speaker_latency_ms = (time.perf_counter() - speaker_started) * 1000.0
    speaker_id = str(speaker_result.get("speaker_id", "unknown"))
    confidence = float(speaker_result.get("confidence", 0))
    if self._wakeup_supersedes_utterance(utterance_wake_id):
        return False
    self._trace(
        "stage_complete",
        stage="speaker",
        result=(
            "error"
            if speaker_failed
            else "matched" if speaker_id != "unknown" else "unknown"
        ),
        interaction_id=self._interaction_id,
        utterance_id=utterance_id,
        latency_ms=round(speaker_latency_ms, 2),
        speaker_id=speaker_id,
        speaker_confidence=confidence,
        reason=str(speaker_result.get("reason", "")),
        score_margin=speaker_result.get("score_margin"),
    )
    self._publish({
        "event_type": speaker_to_voice_event(speaker_id),
        "utterance_id": utterance_id,
        "speaker_id": speaker_id,
        "speaker_confidence": confidence,
    })

    text = self._clean_text(raw_text)
    if not text:
        arbitration_started = time.perf_counter()
        selected_kws, arbitration_reason = self._select_kws_candidate(
            text="",
            raw_text=raw_text,
            language=str(asr_result.get("language", "")),
        )
        self._trace_recognition_arbitration(
            result=(
                "kws_selected"
                if selected_kws is not None else "none_selected"
            ),
            reason=arbitration_reason,
            text="",
            language=str(asr_result.get("language", "")),
            utterance_id=utterance_id,
            started=arbitration_started,
        )
        if selected_kws is not None:
            return self._publish_selected_kws_candidate(
                selected_kws,
                reason=arbitration_reason,
                text="",
                language=str(asr_result.get("language", "zh")),
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                speaker_confidence=confidence,
                pipeline_started=pipeline_started,
            )
        self._state_machine.trigger(Trigger.SPEECH_END)
        self._trace(
            "utterance_complete",
            result="empty_asr",
            interaction_id=self._interaction_id,
            utterance_id=utterance_id,
            latency_ms=round(
                (time.perf_counter() - pipeline_started) * 1000.0,
                2,
            ),
        )
        return False
    self._publish({
        "event_type": "speech",
        "utterance_id": utterance_id,
        "asr_text": text,
        "speaker_id": speaker_id,
        "speaker_confidence": confidence,
        "language": str(asr_result.get("language", "zh")),
        "latency_ms": float(asr_result.get("latency_ms", 0)),
    })

    lexicon_started = time.perf_counter()
    if self._command_lexicon is None:
        direct_match = None
    elif getattr(self, "_command_fuzzy_matching", True):
        direct_match = self._command_lexicon.match_fuzzy(text)
    else:
        direct_match = self._command_lexicon.match(text)
    lexicon_latency_ms = (
        time.perf_counter() - lexicon_started
    ) * 1000.0
    self._trace(
        "stage_complete",
        stage="command_lexicon",
        result=(
            "matched"
            if direct_match is not None
            else "no_match"
            if self._command_lexicon is not None
            else "unavailable"
        ),
        interaction_id=self._interaction_id,
        utterance_id=utterance_id,
        latency_ms=round(lexicon_latency_ms, 3),
        command_key=(
            direct_match.command_key if direct_match is not None else ""
        ),
        event_type=(
            direct_match.event_type if direct_match is not None else ""
        ),
        catalog_version=(
            direct_match.catalog_version
            if direct_match is not None else ""
        ),
        catalog_phrase=(
            direct_match.catalog_phrase
            if direct_match is not None else ""
        ),
        matched_phrase=(
            direct_match.matched_phrase
            if direct_match is not None else ""
        ),
        match_strategy=(
            direct_match.match_strategy
            if direct_match is not None else ""
        ),
        expansion_profile=(
            direct_match.expansion_profile
            if direct_match is not None else ""
        ),
        expansion_rule=(
            direct_match.expansion_rule
            if direct_match is not None else ""
        ),
        action_name=(
            direct_match.action_name
            if direct_match is not None else ""
        ),
        emotion=(
            direct_match.emotion if direct_match is not None else ""
        ),
        social=(
            direct_match.nlu_social if direct_match is not None else ""
        ),
        intent=(
            direct_match.nlu_intent if direct_match is not None else ""
        ),
        control=(
            direct_match.nlu_control
            if direct_match is not None and direct_match.nlu_control
            else direct_match.control if direct_match is not None else ""
        ),
        source_rows=(
            list(direct_match.source_rows)
            if direct_match is not None else []
        ),
        core=(direct_match.core if direct_match is not None else False),
        emit_known_event=(
            direct_match.emit_known_event
            if direct_match is not None else False
        ),
    )
    arbitration_started = time.perf_counter()
    selected_kws, arbitration_reason = self._select_kws_candidate(
        text=text,
        raw_text=raw_text,
        language=str(asr_result.get("language", "")),
        direct_match=direct_match,
    )
    self._trace_recognition_arbitration(
        result=(
            "kws_selected"
            if selected_kws is not None else "asr_selected"
        ),
        reason=arbitration_reason,
        text=text,
        language=str(asr_result.get("language", "")),
        utterance_id=utterance_id,
        direct_match=direct_match,
        started=arbitration_started,
    )
    if selected_kws is not None:
        return self._publish_selected_kws_candidate(
            selected_kws,
            reason=arbitration_reason,
            text=text,
            language=str(asr_result.get("language", "zh")),
            utterance_id=utterance_id,
            speaker_id=speaker_id,
            speaker_confidence=confidence,
            pipeline_started=pipeline_started,
        )
    if direct_match is not None:
        direct_event = direct_match.to_event(
            asr_text=text,
            language=str(asr_result.get("language", "zh")),
        )
        direct_event.update({
            "utterance_id": utterance_id,
            "speaker_id": speaker_id,
            "speaker_confidence": confidence,
            "latency_ms": round(lexicon_latency_ms, 3),
        })
        final_event_type = direct_match.event_type
        published_event_types: list[str] = []
        if direct_match.emit_known_event:
            known_event = direct_match.to_known_event(
                asr_text=text,
                language=str(asr_result.get("language", "zh")),
                specific_dispatch="published",
            )
            known_event.update({
                "utterance_id": utterance_id,
                "speaker_id": speaker_id,
                "speaker_confidence": confidence,
                "latency_ms": round(lexicon_latency_ms, 3),
            })
            self._publish(known_event)
            published_event_types.append(
                str(known_event["event_type"])
            )
        if direct_event.get("should_trigger_behavior_tree"):
            self._state_machine.trigger(Trigger.INTENT_PARSED)
        else:
            self._state_machine.trigger(Trigger.SPEECH_END)
        self._publish(direct_event)
        published_event_types.append(final_event_type)
        completion_result = (
            "published_known_and_specific"
            if direct_match.emit_known_event
            else "published_social_reaction"
            if direct_event.get("dispatch_role") == "social_reaction"
            else "published_direct_command"
            if direct_event.get("should_trigger_behavior_tree")
            else "published_catalog_event"
        )
        self._trace(
            "utterance_complete",
            result=completion_result,
            interaction_id=self._interaction_id,
            utterance_id=utterance_id,
            event_type=final_event_type,
            published_event_types=published_event_types,
            intent_source="command_lexicon",
            latency_ms=round(
                (time.perf_counter() - pipeline_started) * 1000.0,
                2,
            ),
        )
        return True

    intent_started = time.perf_counter()
    context = dict(text=text, utterance_id=utterance_id,
                   utterance_wake_id=utterance_wake_id, asr_result=asr_result,
                   speaker_id=speaker_id, confidence=confidence,
                   pipeline_started=pipeline_started, intent_started=intent_started)
    provider = self._providers.get("intent_llm")
    if getattr(provider, "background_intent", False) and provider.is_available():
        if getattr(self, "_pending_intent", None) is not None:
            raise RuntimeError("An intent computation is already pending")
        if getattr(self, "_intent_executor", None) is None:
            self._intent_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cpu-intent")
        future = self._intent_executor.submit(self._parse_intent, text, raw_text=raw_text)
        self._pending_intent = (self._interaction_id, context, future)
        return True
    parsed_intent = self._parse_intent(text, raw_text=raw_text)
    return self._complete_intent(parsed_intent, **context)


def complete_intent(self, parsed_intent: dict[str, Any] | None, *, text: str, utterance_id: str, utterance_wake_id: str, asr_result: dict[str, Any], speaker_id: str, confidence: float, pipeline_started: float, intent_started: float, _UNKNOWN_INTENT, object_resolution_slots, route_classification_events):
    if self._wakeup_supersedes_utterance(utterance_wake_id):
        return False
    if parsed_intent is None:
        routed_events = [dict(_UNKNOWN_INTENT)]
        result = "fallback_unknown"
    else:
        parsed_intent_name = str(
            parsed_intent.get("intent", "NONE")
        )
        object_slots: list[dict[str, str]] = []
        if parsed_intent_name in {"FETCH", "FIND_TOY"}:
            object_started = time.perf_counter()
            object_slots, object_supported = object_resolution_slots(
                getattr(self, "_object_target_resolver", None),
                text,
            )
            object_fields = {
                str(slot.get("key", "")): str(
                    slot.get("value", "")
                )
                for slot in object_slots
            }
            self._trace(
                "stage_complete",
                stage="object_target",
                result=(
                    "matched" if object_supported else object_fields.get(
                        "object_match_source", "unsupported"
                    )
                ),
                interaction_id=self._interaction_id,
                utterance_id=utterance_id,
                object_name=object_fields.get("object_name", "NONE"),
                object_mention=object_fields.get("object_mention", ""),
                object_matched_alias=object_fields.get(
                    "object_matched_alias", ""
                ),
                object_catalog_version=object_fields.get(
                    "object_catalog_version", ""
                ),
                latency_ms=round(
                    (time.perf_counter() - object_started) * 1000.0,
                    3,
                ),
            )
        routed_events = route_classification_events(
            str(parsed_intent.get("social", "NONE")),
            parsed_intent_name,
            str(parsed_intent.get("control", "NONE")),
            asr_text=text,
            source=str(
                parsed_intent.get("intent_source", "rkllm")
            ),
            confidence=float(
                parsed_intent.get("intent_confidence", 0.0)
            ),
            language=str(asr_result.get("language", "zh")),
            extra_slots=object_slots,
        )
        result = "parsed"
    if any(
        event.get("should_trigger_behavior_tree")
        for event in routed_events
    ):
        self._state_machine.trigger(Trigger.INTENT_PARSED)
    else:
        self._state_machine.trigger(Trigger.SPEECH_END)
    routed_event_types = [
        str(event.get("event_type", "")) for event in routed_events
    ]
    intent_latency_ms = (
        time.perf_counter() - intent_started
    ) * 1000.0
    self._trace(
        "stage_complete",
        stage="intent",
        result=result,
        interaction_id=self._interaction_id,
        utterance_id=utterance_id,
        event_types=routed_event_types,
        social=str(
            (parsed_intent or _UNKNOWN_INTENT).get("social", "NONE")
        ),
        intent=str(
            (parsed_intent or _UNKNOWN_INTENT).get("intent", "NONE")
        ),
        control=str(
            (parsed_intent or _UNKNOWN_INTENT).get("control", "NONE")
        ),
        intent_source=str(
            (parsed_intent or _UNKNOWN_INTENT).get(
                "intent_source",
                "invalid_protocol_fallback",
            )
        ),
        latency_ms=round(intent_latency_ms, 2),
    )
    for event in routed_events:
        event.update({
            "utterance_id": utterance_id,
            "asr_text": text,
            "speaker_id": speaker_id,
            "speaker_confidence": confidence,
            "latency_ms": round(intent_latency_ms, 2),
        })
        self._publish(event)
    self._trace(
        "utterance_complete",
        result=(
            "published"
            if routed_events
            else "classified_no_business_event"
        ),
        interaction_id=self._interaction_id,
        utterance_id=utterance_id,
        event_types=routed_event_types,
        latency_ms=round(
            (time.perf_counter() - pipeline_started) * 1000.0,
            2,
        ),
    )
    return True


def select_kws_candidate(self, *, text: str, raw_text: str, language: str, direct_match: Any=None):
    """Select one deferred KWS result or explain why ASR owns the turn.

    Division of labor: long ASR text owns the turn.  A short KWS candidate
    needs an agreeing catalog event, except for exact configured ASR-error
    aliases.
    """

    candidates = [
        dict(event) for event in self._command_tracker.kws_candidates
    ]
    if not candidates:
        return None, "no_kws_candidate"
    if len(candidates) != 1:
        return None, "multiple_kws_candidates"
    candidate = candidates[0]
    policy = self._effective_kws_arbitration()
    if not text:
        if policy["kws_fallback_on_asr_empty"]:
            return candidate, "empty_asr_single_candidate"
        return None, "empty_asr_fallback_disabled"

    candidate_event_type = str(candidate.get("event_type", ""))
    candidate_command_key = str(candidate.get("action", "")).strip().upper()
    priority_aliases = policy.get("priority_asr_aliases", {})
    allowed_aliases = priority_aliases.get(candidate_command_key, ())
    if (
        candidate_command_key in policy.get("priority_command_keys", ())
        and text in allowed_aliases
    ):
        return candidate, "configured_kws_priority_alias"
    if (
        policy["asr_long_text_wins"]
        and not self._is_short_asr_text(raw_text, language)
    ):
        return None, "long_asr_text"
    if (
        direct_match is not None
        and direct_match.event_type != candidate_event_type
    ):
        return None, "short_asr_catalog_conflict"
    if direct_match is not None:
        return candidate, "short_asr_catalog_agrees"
    if policy.get("short_requires_asr_agreement", True):
        return None, "short_asr_unconfirmed_kws"
    return candidate, "short_asr_kws_preferred"


def is_short_asr_text(self, raw_text: str, language: str):
    """Classify ASR text for KWS preference without changing semantics."""

    policy = self._effective_kws_arbitration()
    value = str(raw_text).strip()
    language = str(language).strip().lower()
    ascii_words = re.findall(r"[A-Za-z0-9]+", value)
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", value))
    if language.startswith("en") or (ascii_words and not has_cjk):
        return (
            0 < len(ascii_words)
            <= int(policy["short_max_words_en"])
        )
    return (
        0 < len(self._clean_text(value))
        <= int(policy["short_max_chars_zh"])
    )


def publish_selected_kws_candidate(self, candidate: dict[str, Any], *, reason: str, text: str, language: str, utterance_id: str, speaker_id: str, speaker_confidence: float, pipeline_started: float):
    """Publish one KWS-selected result group after final arbitration."""

    event = dict(candidate)
    command_key = str(event.get("action", "")).strip().upper()
    event_type = str(event.get("event_type", ""))
    catalog_command = (
        self._command_lexicon.get_command(command_key)
        if self._command_lexicon is not None and command_key else None
    )
    candidate_latency_ms = float(event.get("latency_ms", 0.0))
    decision_latency_ms = (
        time.perf_counter() - pipeline_started
    ) * 1000.0
    audit_slots = [
        {"key": "recognition_strategy", "value": "kws_candidate"},
        {"key": "arbitration_reason", "value": reason},
        {
            "key": "kws_candidate_latency_ms",
            "value": f"{candidate_latency_ms:.2f}",
        },
    ]
    existing_slots = [
        dict(slot) for slot in event.get("slots", [])
        if isinstance(slot, dict)
    ]
    event.update({
        "utterance_id": utterance_id,
        "asr_text": text,
        "language": language or "zh",
        "speaker_id": speaker_id,
        "speaker_confidence": speaker_confidence,
        "intent_source": "kws",
        "latency_ms": round(decision_latency_ms, 2),
        "slots": existing_slots + audit_slots,
    })
    published_event_types: list[str] = []
    if catalog_command is not None and catalog_command.emit_known_event:
        known_event = catalog_command.to_known_event(
            asr_text=text,
            language=language or "zh",
            specific_dispatch="published",
            source="kws",
            confidence=float(event.get("intent_confidence", 0.0)),
            matched_phrase=str(
                next(
                    (
                        slot.get("value", command_key)
                        for slot in existing_slots
                        if slot.get("key") == "kws_keyword"
                    ),
                    command_key,
                )
            ),
            extra_slots=audit_slots,
        )
        known_slots = [
            dict(slot) for slot in known_event.get("slots", [])
            if isinstance(slot, dict)
        ]
        for slot in known_slots:
            if slot.get("key") == "match_strategy":
                slot["value"] = "kws_candidate"
        known_event.update({
            "utterance_id": utterance_id,
            "speaker_id": speaker_id,
            "speaker_confidence": speaker_confidence,
            "latency_ms": round(decision_latency_ms, 2),
            "slots": known_slots,
        })
        self._publish(known_event)
        published_event_types.append(EVT_VOICE_COMMAND_KNOWN)

    if event.get("should_trigger_behavior_tree"):
        self._state_machine.trigger(Trigger.INTENT_PARSED)
    else:
        self._state_machine.trigger(Trigger.SPEECH_END)
    self._publish(event)
    published_event_types.append(event_type)
    self._trace(
        "utterance_complete",
        result="published_kws_selected",
        interaction_id=self._interaction_id,
        utterance_id=utterance_id,
        event_type=event_type,
        published_event_types=published_event_types,
        selected_source="kws",
        arbitration_reason=reason,
        latency_ms=round(decision_latency_ms, 2),
    )
    return True


def parse_intent(self, text: str, *, raw_text: str | None=None, logger):
    for name in ("intent_llm", "intent_rule"):
        provider = self._providers.get(name)
        if provider is None or not provider.is_available():
            continue
        try:
            # Only an opted-in provider sees the unmodified ASR utterance.
            # Legacy RKLLM and rule fallback keep their normalized input.
            provider_text = (
                raw_text if raw_text is not None
                and getattr(provider, "preserve_asr_text", False) else text
            )
            result = provider.parse_intent(provider_text)  # type: ignore[attr-defined]
            if result is not None:
                return result
            if getattr(provider, "input_rejected", False):
                # CPU chat-control/length rejection must not become a rule command.
                return None
        except Exception as exc:
            logger.warning("%s intent failed: %s", name, exc)
    return None
