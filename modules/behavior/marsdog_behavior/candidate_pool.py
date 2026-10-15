"""Candidate Pool — thread-safe behavior candidate management.

Collects BehaviorCandidates from upstream subscriptions, deduplicates
by composite key (source, trigger_event, behavior_name, variant, interaction_mode),
and selects the best candidate by priority, sub_priority, and intensity.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable, Optional

from bionic_dog_bt.logger import get_logger, LogEvent
from bionic_dog_bt.arbitration import priority_key, candidate_priority_key
from bionic_dog_bt.drive_policy import resolve_drive

from .decision_trace import emit
from .lifecycle import discard_unstarted_on_voice_idle

_log = get_logger("candidate_pool")


class CandidatePool:
    """Thread-safe pool of behavior candidates with composite-key dedup."""

    def __init__(self, *, monotonic: Callable[[], float] | None = None,
                 wall_time: Callable[[], float] | None = None):
        self._monotonic = monotonic or time.monotonic
        self._wall_time = wall_time or time.time
        self._candidates: list[dict] = []
        # Sidecar by object identity: callers may supply repeated candidate IDs.
        # This clock-domain detail never enters a returned candidate or payload.
        self._expires_at: dict[int, float] = {}
        self._seen_keys: set[tuple] = set()
        # behavior_name -> candidate/behavior id.  Selection reserves the
        # semantic behavior until its terminal lifecycle event is observed.
        # This prevents a second event source (or allow_repeat) from injecting
        # the same behavior while the first invocation is being dispatched or
        # executed.
        self._inflight: dict[str, str] = {}
        self._lock = threading.Lock()

    def add(self, behavior_name: str, priority_level: int, value: float = 50.0,
            confidence: float = 0.8, need_type: str = "external",
            source_emotion: str = "", params: dict | None = None,
            timeout_sec: float = 30.0, cooldown_sec: float = 0.0,
            sub_priority: int = 0, dedup_key: tuple = None,
            interrupt_policy: str = "immediate", ttl_sec: float = 10.0,
            candidate_id: str = "", created_at: float | None = None,
            allow_repeat: bool = False, emotion_priority: int = 50,
            semantic_rank: int = 3, modality_rank: int = 3) -> bool:
        """Add a candidate. Returns True if added, False if duplicate.

        A behavior name is unique across both the queued and in-flight states.
        The composite key remains useful for diagnostics/source identity, but
        ``allow_repeat`` only permits a new invocation after the previous one
        reaches a terminal state; it never permits concurrent duplicates.
        """
        with self._lock:
            now = self._wall_time()
            monotonic_now = self._monotonic()
            self._discard_expired(monotonic_now)

            if behavior_name in self._inflight:
                return False
            if any(
                item["behavior_name"] == behavior_name
                for item in self._candidates
            ):
                return False

            key = dedup_key or (behavior_name,)
            if key in self._seen_keys:
                return False

            candidate_id = candidate_id or f"cand_{uuid.uuid4().hex[:12]}"
            candidate_params = dict(params or {})
            candidate_params.setdefault("sub_priority", sub_priority)
            candidate_params.setdefault("semantic_rank", semantic_rank)
            candidate_params.setdefault("modality_rank", modality_rank)
            try:
                priority_key(priority_level, candidate_params)
            except ValueError as error:
                emit("candidate_rejected", {"behavior_name": behavior_name},
                     reason="invalid_priority", detail=str(error))
                return False
            self._seen_keys.add(key)
            self._candidates.append({
                "behavior_name": behavior_name,
                "priority_level": priority_level,
                "sub_priority": sub_priority,
                "semantic_rank": semantic_rank,
                "modality_rank": modality_rank,
                "value": value,
                "confidence": confidence,
                "need_type": need_type,
                "source_emotion": source_emotion,
                "params": candidate_params,
                "timeout_sec": timeout_sec,
                "cooldown_sec": cooldown_sec,
                "interrupt_policy": interrupt_policy,
                "ttl_sec": ttl_sec,
                "candidate_id": candidate_id,
                "created_at": created_at if created_at is not None else now,
                "dedup_key": key,
                "allow_repeat": allow_repeat,
                "emotion_priority": emotion_priority,
            })
            candidate = self._candidates[-1]
            if ttl_sec > 0:
                # Honor the existing created_at age at admission, then freeze
                # the elapsed-time budget against later wall-clock changes.
                self._expires_at[id(candidate)] = (
                    monotonic_now + ttl_sec - (now - candidate["created_at"]))
            emit("candidate_queued", self._candidates[-1])
            _log.event(LogEvent.CANDIDATE_INJECT,
                       behavior_name=behavior_name,
                       priority_level=priority_level,
                       value=value)
            return True

    def select_best(
        self,
        blackboard,
        *,
        can_run: Callable[[dict], bool] | None = None,
    ) -> Optional[dict]:
        """Claim and return the best candidate that can run now.

        Sort order:
          1. priority_level ASC
          2. semantic_rank ASC
          3. modality_rank ASC
          4. sub_priority/behavior_rank ASC
          5. emotion_priority ASC (lower = higher priority, 50 default)
          6. value DESC
          7. created_at DESC (newest first)

        Expired candidates are discarded. Candidates in cooldown or rejected
        by ``can_run`` remain queued until they become runnable, are invalidated
        by an authoritative state update, or their positive TTL expires.
        """
        with self._lock:
            now = self._monotonic()
            self._discard_expired(now)
            if not self._candidates:
                return None

            self._candidates.sort(key=candidate_priority_key)
            best_index = None
            for index, candidate in enumerate(self._candidates):
                cooldown_ready = not blackboard.is_in_cooldown(
                    candidate["behavior_name"]
                )
                if not cooldown_ready:
                    emit("candidate_waiting", candidate, reason="cooldown",
                         repeat_key=candidate["candidate_id"])
                    continue
                if can_run is not None and not can_run(candidate):
                    continue
                best_index = index
                break
            if best_index is None:
                return None

            best = self._candidates.pop(best_index)
            self._forget_queued(best)
            self._inflight[best["behavior_name"]] = best["candidate_id"]

            emit("candidate_selected", best, ordering=list(candidate_priority_key(best)))
            _log.event(LogEvent.CANDIDATE_SELECT,
                       behavior_name=best["behavior_name"],
                       priority_level=best["priority_level"],
                       value=best["value"])
            return best

    def _forget_queued(self, candidate: dict) -> None:
        """Release queue-only bookkeeping; caller holds the pool lock."""
        self._seen_keys.discard(candidate["dedup_key"])
        self._expires_at.pop(id(candidate), None)

    def _discard_expired(self, now: float) -> None:
        """Discard candidates whose positive TTL has elapsed.

        Caller must hold ``self._lock``.
        """
        retained = []
        for candidate in self._candidates:
            deadline = self._expires_at.get(id(candidate))
            expired = deadline is not None and now >= deadline
            if expired:
                emit("candidate_expired", candidate, reason="ttl_elapsed")
                self._forget_queued(candidate)
            else:
                retained.append(candidate)
        self._candidates = retained

    def is_duplicate(self, behavior_name: str, dedup_key: tuple = None) -> bool:
        """Check whether a behavior is queued or reserved in-flight."""
        with self._lock:
            self._discard_expired(self._monotonic())
            if behavior_name in self._inflight:
                return True
            if any(
                item["behavior_name"] == behavior_name
                for item in self._candidates
            ):
                return True
            if dedup_key:
                return dedup_key in self._seen_keys
        return False

    def release_inflight(
        self,
        behavior_name: str,
        candidate_id: str | None = None,
    ) -> bool:
        """Release a selected behavior after a terminal or no-dispatch path.

        When *candidate_id* is supplied, a stale terminal callback cannot
        release a newer invocation that happens to use the same behavior name.
        """
        with self._lock:
            reserved_id = self._inflight.get(behavior_name)
            if reserved_id is None:
                return False
            if candidate_id and reserved_id != candidate_id:
                return False
            del self._inflight[behavior_name]
            return True

    def is_inflight(self, behavior_name: str) -> bool:
        """Return whether *behavior_name* is selected/dispatched and active."""
        with self._lock:
            return behavior_name in self._inflight

    @property
    def inflight(self) -> dict[str, str]:
        """Return a snapshot of current behavior-name reservations."""
        with self._lock:
            return dict(self._inflight)

    def clear(self) -> None:
        with self._lock:
            self._candidates.clear()
            self._seen_keys.clear()
            self._inflight.clear()
            self._expires_at.clear()

    def discard_where(self, predicate: Callable[[dict], bool]) -> int:
        """Discard matching queued candidates without touching other work.

        In-flight reservations are lifecycle-owned and are intentionally not
        released here; :class:`BehaviorRuntime` owns cancellation/terminal
        cleanup for an executing goal.
        """
        with self._lock:
            retained: list[dict] = []
            removed = 0
            for candidate in self._candidates:
                if predicate(candidate):
                    self._forget_queued(candidate)
                    removed += 1
                else:
                    retained.append(candidate)
            self._candidates = retained
            return removed

    def discard_session(self, interaction_id: str) -> int:
        """Discard only queued work owned by one voice interaction."""
        interaction_id = str(interaction_id).strip()
        if not interaction_id:
            return 0
        def belongs_to_voice(candidate: dict) -> bool:
            params = candidate.get("params", {})
            return (
                isinstance(params, dict)
                and str(params.get("interaction_id", "")).strip()
                == interaction_id
                and discard_unstarted_on_voice_idle(params)
            )

        return self.discard_where(belongs_to_voice)

    def discard_emotion(self, emotion_name: str) -> int:
        """Discard queued candidates tied to a recovered V2 emotion.

        Running behaviors are intentionally unaffected. Removing queued items
        also releases their dedup keys so a later upward edge can enqueue a
        fresh candidate with a fresh TTL.
        """
        with self._lock:
            retained = []
            removed = 0
            for candidate in self._candidates:
                params = candidate.get("params", {})
                source_emotion = (
                    candidate.get("source_emotion")
                    or params.get("source_emotion")
                )
                if (
                    resolve_drive(params, candidate.get("need_type", "")).state_domain == "emotion"
                    and source_emotion == emotion_name
                ):
                    self._forget_queued(candidate)
                    removed += 1
                else:
                    retained.append(candidate)
            self._candidates = retained
            return removed

    def discard_need_except(
        self,
        need_name: str,
        current_event: str,
    ) -> int:
        """Discard queued candidates that no longer match a V2 need level."""
        with self._lock:
            retained = []
            removed = 0
            for candidate in self._candidates:
                params = candidate.get("params", {})
                is_need_candidate = resolve_drive(
                    params, candidate.get("need_type", "")
                ).state_domain == "need"
                source_need = params.get("source_need")
                trigger_event = params.get("trigger_event", "")
                if (
                    is_need_candidate
                    and source_need == need_name
                    and trigger_event != current_event
                ):
                    self._forget_queued(candidate)
                    removed += 1
                else:
                    retained.append(candidate)
            self._candidates = retained
            return removed

    def size(self) -> int:
        with self._lock:
            self._discard_expired(self._monotonic())
            return len(self._candidates)

    @property
    def candidates(self) -> list[dict]:
        with self._lock:
            self._discard_expired(self._monotonic())
            return list(self._candidates)
