"""Emotion V2 state module.

Aligned with ROS2 /emotion/state and /emotion/signal_event topics.
Emotions: Joy, Excite, Anxiety, Fear, Curious, Calm.

Flow:
1. /emotion/state mirrors value, threshold metadata, and ``triggered``.
2. /emotion/signal_event creates a one-shot behavior candidate on an upward edge.
3. Before execution, the tree checks the authoritative ``triggered`` boolean.
4. A later state with ``triggered=false`` invalidates a queued candidate.
"""

from __future__ import annotations

import time
from typing import Optional

from .datatypes import EmotionState
from .constants import DEFAULT_EMOTION_CONFIG


class EmotionModule:
    """Mirrors the authoritative V2 emotion state.

    Production relevance never derives a level from the numeric value. The
    upstream ``triggered`` field is the source of truth. Local decay remains
    available only for standalone visualisation and does not alter that flag.
    """

    def __init__(self):
        self._emotions: dict[str, EmotionState] = {}

    def _ensure_emotion(self, name: str) -> EmotionState:
        """Get or create an emotion state with default config."""
        if name not in self._emotions:
            config = DEFAULT_EMOTION_CONFIG.get(name, {})
            self._emotions[name] = EmotionState(
                name=name,
                current_value=0.0,
                trigger_threshold=config.get("trigger_threshold", 70.0),
                decay_rate=config.get("decay_rate", 5.0),
            )
        return self._emotions[name]

    def set_emotion(self, name: str, value: float) -> None:
        """Set an emotion's current value from the authoritative state message.

        The emotion_engine is the single source of truth — always accept its value.
        Decay is handled by the engine; we just mirror its published state.
        """
        state = self._ensure_emotion(name)
        state.current_value = max(0.0, min(value, 100.0))
        state.last_update = time.time()

    def set_triggered(self, name: str, triggered: bool) -> None:
        """Mirror ``/emotion/state.emotions.<name>.triggered``."""
        self._ensure_emotion(name).triggered = bool(triggered)

    def update_state(
        self,
        name: str,
        value: float,
        triggered: bool,
        trigger_threshold: float | None = None,
        trigger_operator: str | None = None,
    ) -> None:
        """Atomically apply one V2 emotion state object."""
        normalized_value = max(0.0, min(float(value), 100.0))
        normalized_threshold = (
            float(trigger_threshold)
            if trigger_threshold is not None
            else None
        )
        normalized_operator = (
            str(trigger_operator)
            if trigger_operator is not None
            else None
        )

        state = self._ensure_emotion(name)
        state.current_value = normalized_value
        state.triggered = bool(triggered)
        if normalized_threshold is not None:
            state.trigger_threshold = normalized_threshold
        if normalized_operator is not None:
            state.trigger_operator = normalized_operator
        state.last_update = time.time()

    def tick(self) -> None:
        """Apply decay to all emotions based on elapsed time since last tick."""
        now = time.time()
        for state in self._emotions.values():
            elapsed = now - state.last_update
            if elapsed > 0 and state.decay_rate > 0:
                state.current_value = max(0.0, state.current_value - state.decay_rate * elapsed)
            state.last_update = now

    def is_triggered(self, name: str) -> bool:
        """Return the latest authoritative V2 trigger state."""
        state = self._emotions.get(name)
        return bool(state and state.triggered)

    def is_overflowing(self, name: str) -> bool:
        """Deprecated compatibility alias for :meth:`is_triggered`."""
        return self.is_triggered(name)

    def get_emotion(self, name: str) -> Optional[EmotionState]:
        """Get the current state of an emotion channel, or None if never set."""
        return self._emotions.get(name)

    def get_all_emotions(self) -> dict[str, EmotionState]:
        """Get all tracked emotion states."""
        return dict(self._emotions)

    def get_value(self, name: str) -> float:
        """Get current value of an emotion (0.0 if never set)."""
        state = self._emotions.get(name)
        return state.current_value if state else 0.0

    def get_dominant_emotion(self) -> Optional[tuple[str, float]]:
        """Find the dominant (highest value) emotion. Returns (name, value) or None."""
        if not self._emotions:
            return None
        # Find max by value, break ties with priority: Fear > Anxiety > Excite > Joy > Curious > Calm
        max_val = max(s.current_value for s in self._emotions.values())
        candidates = [(n, s) for n, s in self._emotions.items()
                      if s.current_value == max_val]
        priority = {"Fear": 0, "Anxiety": 1, "Excite": 2, "Joy": 3, "Curious": 4, "Calm": 5}
        candidates.sort(key=lambda x: priority.get(x[0], 99))
        best = candidates[0]
        return best[0], best[1].current_value

    def reset(self) -> None:
        """Reset all emotion states."""
        self._emotions.clear()
