"""Explicit dependencies for the transport-independent orchestration.

Mutable state has one owner. Adapters provide live views; policy never receives
a ROS node or a generic attribute forwarding facade.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Protocol


class SpeechState(Protocol):
    interaction_id: str
    latest_wake_id: str
    pending_intent: tuple | None
    intent_executor: Any


@dataclass
class MemorySpeechState:
    interaction_id: str = ''
    latest_wake_id: str = ''
    pending_intent: tuple | None = None
    intent_executor: Any = None


@dataclass(frozen=True)
class SpeechPorts:
    perf_counter: Callable[[], float]
    new_utterance_id: Callable[[], str]
    clean_text: Callable[..., Any]
    command_fuzzy_matching: Any
    command_lexicon: Any
    command_tracker: Any
    complete_intent: Callable[..., Any]
    effective_kws_arbitration: Callable[..., Any]
    is_short_asr_text: Callable[..., Any]
    object_target_resolver: Any
    parse_intent: Callable[..., Any]
    providers: Any
    publish: Callable[..., Any]
    publish_selected_kws_candidate: Callable[..., Any]
    refresh_for_asr_result: Callable[..., Any]
    select_kws_candidate: Callable[..., Any]
    speaker_operation_lock: Any
    state_machine: Any
    trace: Callable[..., Any]
    trace_recognition_arbitration: Callable[..., Any]
    wakeup_supersedes_utterance: Callable[..., Any]


@dataclass(frozen=True)
class SpeechRuntime:
    state: SpeechState
    ports: SpeechPorts
