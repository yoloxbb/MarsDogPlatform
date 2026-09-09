"""Fresh emotion-state context used to refine stranger visual events."""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Iterable


STRANGER_EMOTION_ALERT = "alert"
STRANGER_EMOTION_FRIEND = "friend"


class StrangerEmotionContext:
    """Cache authoritative ``/emotion/state`` threshold flags.

    The emotion engine owns threshold/operator semantics, including the Calm
    fallback. Vision consumes each emotion's boolean ``triggered`` field
    instead of duplicating that policy.
    """

    def __init__(
        self,
        *,
        timeout_sec: float = 2.5,
        alert_emotions: Iterable[str] = ("Anxiety", "Fear"),
        friend_emotions: Iterable[str] = ("Joy", "Excite", "Calm"),
    ) -> None:
        self._timeout_sec = max(0.1, float(timeout_sec))
        self._alert_emotions = self._normalize_names(alert_emotions)
        self._friend_emotions = self._normalize_names(friend_emotions)
        self._required_emotions = (
            self._alert_emotions | self._friend_emotions
        )
        self._lock = threading.Lock()
        self._triggered_emotions: frozenset[str] = frozenset()
        self._received_monotonic = 0.0
        self._source_timestamp: float | None = None

    @staticmethod
    def _normalize_names(values: Iterable[str]) -> frozenset[str]:
        if isinstance(values, str):
            values = (values,)
        try:
            return frozenset(
                name
                for value in values
                if (name := str(value).strip())
            )
        except TypeError:
            return frozenset()

    def update(
        self,
        payload: Any,
        *,
        received_monotonic: float | None = None,
    ) -> bool:
        """Accept one complete v2 emotion snapshot.

        Malformed or partial payloads do not replace the last valid state.
        """
        if not isinstance(payload, dict):
            return False
        schema_version = payload.get("schema_version")
        if schema_version is not None and str(schema_version) != "2.0":
            return False
        emotions = payload.get("emotions")
        if not isinstance(emotions, dict):
            return False

        triggered: set[str] = set()
        for name in self._required_emotions:
            state = emotions.get(name)
            if not isinstance(state, dict):
                return False
            flag = state.get("triggered")
            if not isinstance(flag, bool):
                return False
            if flag:
                triggered.add(name)

        source_timestamp: float | None = None
        try:
            value = float(payload.get("timestamp"))
            if math.isfinite(value):
                source_timestamp = value
        except (TypeError, ValueError):
            pass

        received_at = (
            time.monotonic()
            if received_monotonic is None
            else float(received_monotonic)
        )
        if not math.isfinite(received_at):
            return False
        with self._lock:
            self._triggered_emotions = frozenset(triggered)
            self._received_monotonic = received_at
            self._source_timestamp = source_timestamp
        return True

    def classify(self, *, now: float | None = None) -> str:
        """Return ``alert``, ``friend`` or an empty fallback classification."""
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            received_at = self._received_monotonic
            triggered = self._triggered_emotions
        if received_at <= 0.0 or timestamp - received_at > self._timeout_sec:
            return ""
        if triggered & self._alert_emotions:
            return STRANGER_EMOTION_ALERT
        if triggered & self._friend_emotions:
            return STRANGER_EMOTION_FRIEND
        return ""

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        """Return diagnostics without exposing mutable internal state."""
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            received_at = self._received_monotonic
            triggered = sorted(self._triggered_emotions)
            source_timestamp = self._source_timestamp
        age_sec = (
            max(0.0, timestamp - received_at)
            if received_at > 0.0
            else None
        )
        return {
            "fresh": age_sec is not None and age_sec <= self._timeout_sec,
            "age_sec": round(age_sec, 3) if age_sec is not None else None,
            "source_timestamp": source_timestamp,
            "triggered_emotions": triggered,
            "classification": self.classify(now=timestamp),
        }
