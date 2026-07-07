"""Internal need state module: tracks need levels with trigger/overflow logic.

Aligned with ROS2 /internal_need/state and /internal_need/signal_event topics.
Needs: Hunger, Bladder, Sleepiness, Cleanliness, Energy, Social, Exploration.

Each need has three levels:
  - NORMAL: below trigger threshold
  - TRIGGERED: crossed trigger threshold → generates behavior candidate
  - OVERFLOW: crossed overflow threshold → generates urgent behavior candidate

Needs do NOT decay naturally (unlike emotions). They are driven by
upstream logic (time-based accumulation, external events, behavior results).
"""

from __future__ import annotations

import time
from typing import Optional

from .datatypes import NeedState
from .constants import (
    DEFAULT_NEED_CONFIG,
    NEED_LEVEL_NORMAL,
    NEED_LEVEL_TRIGGERED,
    NEED_LEVEL_OVERFLOW,
)


def _check_threshold(value: float, threshold: float, operator: str) -> bool:
    """Check if value crosses threshold according to operator."""
    if operator == "gt":
        return value > threshold
    elif operator == "lt":
        return value < threshold
    elif operator == "gte":
        return value >= threshold
    elif operator == "lte":
        return value <= threshold
    return False


def _compute_level(value: float, config: dict) -> str:
    """Compute NORMAL/TRIGGERED/OVERFLOW level from value and config."""
    trigger_th = config.get("trigger_threshold", 70)
    trigger_op = config.get("trigger_op", "gt")
    overflow_th = config.get("overflow_threshold", 90)
    overflow_op = config.get("overflow_op", "gt")

    if _check_threshold(value, overflow_th, overflow_op):
        return NEED_LEVEL_OVERFLOW
    elif _check_threshold(value, trigger_th, trigger_op):
        return NEED_LEVEL_TRIGGERED
    return NEED_LEVEL_NORMAL


class NeedModule:
    """Manages 7 internal needs with trigger/overflow level tracking.

    Each need tracks its current value and automatically computes
    its level (NORMAL/TRIGGERED/OVERFLOW) based on configured thresholds.
    Level changes can be queried to detect signal events.
    """

    def __init__(self):
        self._needs: dict[str, NeedState] = {}
        self.level_events: dict[str, Optional[str]] = {}  # need_name → "NEED_HUNGER_TRIGGERED" or "NEED_HUNGER_RECOVERED"

    def set_level_events(self, events: dict[str, Optional[str]]) -> None:
        """Store the current levelEvents from /internal_need/state.

        Used by BehaviorRelevanceCondition: compares with trigger_event from
        signal_event to determine if need is still at the same level.
        """
        self.level_events = dict(events)

    def _ensure_need(self, name: str) -> NeedState:
        """Get or create a need state with default config."""
        if name not in self._needs:
            config = DEFAULT_NEED_CONFIG.get(name, {})
            self._needs[name] = NeedState(
                name=name,
                current_value=0.0,
                trigger_threshold=config.get("trigger_threshold", 70.0),
                trigger_operator=config.get("trigger_op", "gt"),
                overflow_threshold=config.get("overflow_threshold", 90.0),
                overflow_operator=config.get("overflow_op", "gt"),
            )
        return self._needs[name]

    def set_need(self, name: str, value: float) -> Optional[str]:
        """Set a need's current value. Returns the new level, or None if unchanged.

        Clamps value to 0-100 and recomputes the level.
        Tracks previous_level so callers can detect level changes.
        """
        state = self._ensure_need(name)
        state.current_value = max(0.0, min(100.0, value))
        state.previous_level = state.level

        config = DEFAULT_NEED_CONFIG.get(name, {})
        new_level = _compute_level(state.current_value, config)
        state.level = new_level
        state.last_update = time.time()

        if new_level != state.previous_level:
            return new_level
        return None

    def tick(self) -> None:
        """Called each tick cycle. Needs don't decay naturally,
        but this recomputes levels in case config changed."""
        for name, state in self._needs.items():
            config = DEFAULT_NEED_CONFIG.get(name, {})
            state.previous_level = state.level
            state.level = _compute_level(state.current_value, config)

    def get_level(self, name: str) -> str:
        """Get current level of a need: NORMAL, TRIGGERED, or OVERFLOW."""
        state = self._needs.get(name)
        if state is None:
            return NEED_LEVEL_NORMAL
        return state.level

    def is_triggered(self, name: str) -> bool:
        """Check if a need is at TRIGGERED or OVERFLOW level."""
        return self.get_level(name) in (NEED_LEVEL_TRIGGERED, NEED_LEVEL_OVERFLOW)

    def is_overflowing(self, name: str) -> bool:
        """Check if a need is at OVERFLOW level."""
        return self.get_level(name) == NEED_LEVEL_OVERFLOW

    def get_need(self, name: str) -> Optional[NeedState]:
        """Get the current state of a need channel, or None if never set."""
        return self._needs.get(name)

    def get_all_needs(self) -> dict[str, NeedState]:
        """Get all tracked need states."""
        return dict(self._needs)

    def get_value(self, name: str) -> float:
        """Get current value of a need (0.0 if never set)."""
        state = self._needs.get(name)
        return state.current_value if state else 0.0

    def reset(self) -> None:
        """Reset all need states."""
        self._needs.clear()
        self.level_events.clear()
