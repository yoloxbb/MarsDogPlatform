"""Candidate Pool — thread-safe behavior candidate management.

Collects BehaviorCandidates from upstream subscriptions, deduplicates
by composite key (source, trigger_event, behavior_name, variant, interaction_mode),
and selects the best candidate by priority, sub_priority, and intensity.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from bionic_dog_bt.logger import get_logger, LogEvent

_log = get_logger("candidate_pool")


class CandidatePool:
    """Thread-safe pool of behavior candidates with composite-key dedup."""

    def __init__(self):
        self._candidates: list[dict] = []
        self._seen_keys: set[tuple] = set()
        self._lock = threading.Lock()

    def add(self, behavior_name: str, priority_level: int, value: float = 50.0,
            confidence: float = 0.8, need_type: str = "external",
            source_emotion: str = "", params: dict | None = None,
            timeout_sec: float = 30.0, cooldown_sec: float = 0.0,
            sub_priority: int = 0, dedup_key: tuple = None,
            interrupt_policy: str = "immediate", ttl_sec: float = 10.0,
            candidate_id: str = "", created_at: float | None = None,
            allow_repeat: bool = False, emotion_priority: int = 50) -> bool:
        """Add a candidate. Returns True if added, False if duplicate.

        Dedup uses composite key when available, falling back to behavior_name.
        When *allow_repeat* is True the composite-key dedup is skipped so
        every occurrence generates a fresh candidate.
        """
        with self._lock:
            now = time.time()
            self._discard_expired(now)

            # Composite key dedup (skipped for repeatable candidates)
            key = dedup_key or (behavior_name,)
            if not allow_repeat and key in self._seen_keys:
                return False

            if not allow_repeat:
                self._seen_keys.add(key)
            self._candidates.append({
                "behavior_name": behavior_name,
                "priority_level": priority_level,
                "sub_priority": sub_priority,
                "value": value,
                "confidence": confidence,
                "need_type": need_type,
                "source_emotion": source_emotion,
                "params": params or {},
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
          2. sub_priority ASC
          3. emotion_priority ASC (lower = higher priority, 50 default)
          4. value DESC
          5. created_at DESC (newest first)

        Expired candidates are discarded. Candidates in cooldown or rejected
        by ``can_run`` remain queued until they become runnable, are invalidated
        by an authoritative state update, or their positive TTL expires.
        """
        with self._lock:
            now = time.time()
            self._discard_expired(now)
            if not self._candidates:
                return None

            self._candidates.sort(key=lambda c: (
                c["priority_level"],
                c.get("sub_priority", 0),
                c.get("emotion_priority", 50),
                -c["value"],
                -c["created_at"],
            ))
            best_index = None
            for index, candidate in enumerate(self._candidates):
                cooldown_ready = (
                    candidate.get("allow_repeat")
                    or not blackboard.is_in_cooldown(
                        candidate["behavior_name"]
                    )
                )
                if not cooldown_ready:
                    continue
                if can_run is not None and not can_run(candidate):
                    continue
                best_index = index
                break
            if best_index is None:
                return None

            best = self._candidates.pop(best_index)
            self._seen_keys.discard(best["dedup_key"])

            _log.event(LogEvent.CANDIDATE_SELECT,
                       behavior_name=best["behavior_name"],
                       priority_level=best["priority_level"],
                       value=best["value"])
            return best

    def _discard_expired(self, now: float) -> None:
        """Discard candidates whose positive TTL has elapsed.

        Caller must hold ``self._lock``.
        """
        retained = []
        for candidate in self._candidates:
            ttl_sec = float(candidate.get("ttl_sec", 0.0))
            expired = (
                ttl_sec > 0
                and now - float(candidate["created_at"]) >= ttl_sec
            )
            if expired:
                self._seen_keys.discard(candidate["dedup_key"])
            else:
                retained.append(candidate)
        self._candidates = retained

    def is_duplicate(self, behavior_name: str, dedup_key: tuple = None) -> bool:
        """Check if a candidate is already in the pool."""
        with self._lock:
            self._discard_expired(time.time())
            if dedup_key:
                return dedup_key in self._seen_keys
            for existing in self._candidates:
                if existing["behavior_name"] == behavior_name:
                    return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._candidates.clear()
            self._seen_keys.clear()

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
                    candidate.get("need_type") == "emotional"
                    and source_emotion == emotion_name
                ):
                    self._seen_keys.discard(candidate["dedup_key"])
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
                is_need_candidate = params.get("source") == "need"
                source_need = params.get("source_need")
                trigger_event = params.get("trigger_event", "")
                if (
                    is_need_candidate
                    and source_need == need_name
                    and trigger_event != current_event
                ):
                    self._seen_keys.discard(candidate["dedup_key"])
                    removed += 1
                else:
                    retained.append(candidate)
            self._candidates = retained
            return removed

    def size(self) -> int:
        with self._lock:
            self._discard_expired(time.time())
            return len(self._candidates)

    @property
    def candidates(self) -> list[dict]:
        with self._lock:
            self._discard_expired(time.time())
            return list(self._candidates)
