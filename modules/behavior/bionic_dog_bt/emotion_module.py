"""Emotion state module: tracks emotion levels with decay over time.

Aligned with ROS2 /emotion/state and /emotion/signal_event topics.
Emotions: Joy, Excite, Anxiety, Fear, Curious, Calm.

Decay rates match emotion_engine_node natural decay (per second):
  Joy: -2/s, Excite: -3/s, Anxiety: -1.5/s, Fear: -4/s,
  Curious: -2/s, Calm: 0/s (no natural decay)

Flow:
1. Upstream sets emotion value (e.g., Joy=85 > overflow_threshold 70)
2. Behavior candidate is generated (express_happy)
3. If higher-priority behaviors run first, emotion decays
4. Before executing express_happy, check: is Joy still overflowing?
5. If decayed below threshold → skip express_happy
"""

from __future__ import annotations

import time
from typing import Optional

from .datatypes import EmotionState
from .constants import DEFAULT_EMOTION_CONFIG


class EmotionModule:
    """Manages a set of emotion channels with value tracking and decay.

    Each emotion has:
    - current_value: the current intensity (0-100)
    - overflow_threshold: above this, the emotion "overflows" and generates behaviors
    - decay_rate: how fast the value decays per second

    set_emotion() only increases the value (emotions accumulate, don't decrease
    from set operations). Decay is handled by tick(), which decreases values
    based on elapsed wall-clock time.
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
                overflow_threshold=config.get("overflow_threshold", 70.0),
                decay_rate=config.get("decay_rate", 5.0),
            )
        return self._emotions[name]

    def set_emotion(self, name: str, value: float) -> None:
        """Set an emotion's current value. Only increases (emotions accumulate).

        After setting, the last_update timestamp is reset so decay starts fresh.
        """
        state = self._ensure_emotion(name)
        if value > state.current_value:
            state.current_value = min(value, 100.0)
        state.last_update = time.time()

    def tick(self) -> None:
        """Apply decay to all emotions based on elapsed time since last tick."""
        now = time.time()
        for state in self._emotions.values():
            elapsed = now - state.last_update
            if elapsed > 0 and state.decay_rate > 0:
                state.current_value = max(0.0, state.current_value - state.decay_rate * elapsed)
            state.last_update = now

    def is_overflowing(self, name: str) -> bool:
        """Check if an emotion is currently above its overflow threshold."""
        state = self._emotions.get(name)
        if state is None:
            return False
        return state.current_value >= state.overflow_threshold

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

    def reset(self) -> None:
        """Reset all emotion states."""
        self._emotions.clear()
