"""Candidate Pool — thread-safe behavior candidate management.

Collects BehaviorCandidates from upstream subscriptions, deduplicates
by composite key (source, trigger_event, behavior_name, variant, interaction_mode),
and selects the best candidate by priority, sub_priority, and intensity.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

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
            sub_priority: int = 0, dedup_key: tuple = None) -> bool:
        """Add a candidate. Returns True if added, False if duplicate.

        Dedup uses composite key when available, falling back to behavior_name.
        """
        with self._lock:
            # Composite key dedup
            key = dedup_key or (behavior_name,)
            if key in self._seen_keys:
                return False

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
                "created_at": time.time(),
                "dedup_key": key,
            })
            _log.event(LogEvent.CANDIDATE_INJECT,
                       behavior_name=behavior_name,
                       priority_level=priority_level,
                       value=value)
            return True

    def select_best(self, blackboard) -> Optional[dict]:
        """Select the best candidate, respecting cooldowns.

        Sort order:
          1. priority_level ASC
          2. sub_priority ASC
          3. value DESC
          4. created_at DESC (newest first)

        Returns None if pool is empty.
        """
        with self._lock:
            if not self._candidates:
                return None

            self._candidates.sort(key=lambda c: (
                c["priority_level"],
                c.get("sub_priority", 0),
                -c["value"],
                -c["created_at"],
            ))
            best = self._candidates[0]

            # Skip cooldown
            for cand in self._candidates:
                if not blackboard.is_in_cooldown(cand["behavior_name"]):
                    best = cand
                    break

            self._candidates.clear()
            self._seen_keys.clear()

            _log.event(LogEvent.CANDIDATE_SELECT,
                       behavior_name=best["behavior_name"],
                       priority_level=best["priority_level"],
                       value=best["value"])
            return best

    def is_duplicate(self, behavior_name: str, dedup_key: tuple = None) -> bool:
        """Check if a candidate is already in the pool."""
        with self._lock:
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

    def size(self) -> int:
        with self._lock:
            return len(self._candidates)

    @property
    def candidates(self) -> list[dict]:
        with self._lock:
            return list(self._candidates)
