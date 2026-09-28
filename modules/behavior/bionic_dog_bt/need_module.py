"""Internal need V2 state module.

Aligned with ROS2 /internal_need/state and /internal_need/signal_event topics.
Needs: Hunger, Bladder, Sleepiness, Cleanliness, Energy, Social, Exploration.

The protocol has four possible levels:
  - NORMAL: below trigger threshold
  - TRIGGERED: crossed trigger threshold → generates behavior candidate
  - URGENT: optional intermediate line (currently Social only)
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
    NEED_LEVEL_URGENT,
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


def _configured_threshold_crossed(
    value: float,
    threshold: float | None,
    operator: str | None,
) -> bool:
    return (
        threshold is not None
        and operator is not None
        and _check_threshold(value, threshold, operator)
    )


def _compute_level(value: float, config: dict) -> str:
    """Compute the V2 level from a local/mock value and config."""
    trigger_th = config.get("trigger_threshold", 70)
    trigger_op = config.get("trigger_op", "gt")
    urgent_th = config.get("urgent_threshold")
    urgent_op = config.get("urgent_op")
    overflow_th = config.get("overflow_threshold")
    overflow_op = config.get("overflow_op")

    if _configured_threshold_crossed(value, overflow_th, overflow_op):
        return NEED_LEVEL_OVERFLOW
    elif _configured_threshold_crossed(value, urgent_th, urgent_op):
        return NEED_LEVEL_URGENT
    elif _check_threshold(value, trigger_th, trigger_op):
        return NEED_LEVEL_TRIGGERED
    return NEED_LEVEL_NORMAL


class NeedModule:
    """Manages seven internal needs with V2 level tracking.

    Each need tracks its current value and automatically computes
    its level for standalone use. ROS2 callbacks use :meth:`update_state`
    so upstream booleans and levels remain authoritative.
    """

    def __init__(self):
        self._needs: dict[str, NeedState] = {}
        self.level_events: dict[str, Optional[str]] = {}  # need_name → "NEED_HUNGER_TRIGGERED" or "NEED_HUNGER_RECOVERED"

    def set_level_events(self, events: dict[str, Optional[str]]) -> None:
        """Update levelEvents from /internal_need/state (merge, don't replace).

        Only updates keys where the value is not None — prevents a state
        message from wiping out previously-set level events from signal_event.
        """
        for key, value in events.items():
            if value is not None:
                self.level_events[key] = value
                if key in self._needs:
                    self._needs[key].level_event = value

    def _ensure_need(self, name: str) -> NeedState:
        """Get or create a need state with default config."""
        if name not in self._needs:
            config = DEFAULT_NEED_CONFIG.get(name, {})
            self._needs[name] = NeedState(
                name=name,
                current_value=0.0,
                trigger_threshold=config.get("trigger_threshold", 70.0),
                trigger_operator=config.get("trigger_op", "gt"),
                urgent_threshold=config.get("urgent_threshold"),
                urgent_operator=config.get("urgent_op"),
                overflow_threshold=config.get("overflow_threshold"),
                overflow_operator=config.get("overflow_op"),
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
        state.trigger_threshold = config.get("trigger_threshold", 70.0)
        state.trigger_operator = config.get("trigger_op", "gt")
        state.urgent_threshold = config.get("urgent_threshold")
        state.urgent_operator = config.get("urgent_op")
        state.overflow_threshold = config.get("overflow_threshold")
        state.overflow_operator = config.get("overflow_op")
        new_level = _compute_level(state.current_value, config)
        state.level = new_level
        state.triggered = new_level != NEED_LEVEL_NORMAL
        state.urgent = new_level in (NEED_LEVEL_URGENT, NEED_LEVEL_OVERFLOW)
        state.overflow = new_level == NEED_LEVEL_OVERFLOW
        state.level_active = state.triggered
        suffix = (
            "RECOVERED"
            if new_level == NEED_LEVEL_NORMAL
            else new_level
        )
        state.level_event = f"NEED_{name.upper()}_{suffix}"
        self.level_events[name] = state.level_event
        state.last_update = time.time()

        if new_level != state.previous_level:
            return new_level
        return None

    def update_state(
        self,
        name: str,
        *,
        value: float,
        trigger_threshold: float,
        trigger_operator: str,
        urgent_threshold: float | None,
        urgent_operator: str | None,
        overflow_threshold: float | None,
        overflow_operator: str | None,
        triggered: bool,
        urgent: bool,
        overflow: bool,
        level: str,
        level_event: str,
        level_active: bool,
        previous_level: str | None = None,
    ) -> None:
        """Atomically mirror one V2 demand state or signal."""
        normalized = {
            "value": max(0.0, min(float(value), 100.0)),
            "trigger_threshold": float(trigger_threshold),
            "trigger_operator": str(trigger_operator),
            "urgent_threshold": (
                float(urgent_threshold)
                if urgent_threshold is not None
                else None
            ),
            "urgent_operator": (
                str(urgent_operator)
                if urgent_operator is not None
                else None
            ),
            "overflow_threshold": (
                float(overflow_threshold)
                if overflow_threshold is not None
                else None
            ),
            "overflow_operator": (
                str(overflow_operator)
                if overflow_operator is not None
                else None
            ),
        }

        state = self._ensure_need(name)
        state.previous_level = (
            previous_level if previous_level is not None else state.level
        )
        state.current_value = normalized["value"]
        state.trigger_threshold = normalized["trigger_threshold"]
        state.trigger_operator = normalized["trigger_operator"]
        state.urgent_threshold = normalized["urgent_threshold"]
        state.urgent_operator = normalized["urgent_operator"]
        state.overflow_threshold = normalized["overflow_threshold"]
        state.overflow_operator = normalized["overflow_operator"]
        state.triggered = bool(triggered)
        state.urgent = bool(urgent)
        state.overflow = bool(overflow)
        state.level = level
        state.level_event = level_event
        state.level_active = bool(level_active)
        state.last_update = time.time()
        self.level_events[name] = level_event

    def tick(self) -> None:
        """Called each tick cycle. Needs don't decay naturally,
        but this recomputes levels in case config changed."""
        for name, state in self._needs.items():
            config = DEFAULT_NEED_CONFIG.get(name, {})
            state.previous_level = state.level
            state.level = _compute_level(state.current_value, config)
            state.triggered = state.level != NEED_LEVEL_NORMAL
            state.urgent = state.level in (
                NEED_LEVEL_URGENT,
                NEED_LEVEL_OVERFLOW,
            )
            state.overflow = state.level == NEED_LEVEL_OVERFLOW
            state.level_active = state.triggered

    def get_level(self, name: str) -> str:
        """Get current V2 level of a need."""
        state = self._needs.get(name)
        if state is None:
            return NEED_LEVEL_NORMAL
        return state.level

    def is_triggered(self, name: str) -> bool:
        """Return whether the first trigger line is currently crossed."""
        state = self._needs.get(name)
        return bool(state and state.triggered)

    def is_urgent(self, name: str) -> bool:
        """Return whether the optional intermediate urgent line is crossed."""
        state = self._needs.get(name)
        return bool(state and state.urgent)

    def is_overflowing(self, name: str) -> bool:
        """Check if a need is at OVERFLOW level."""
        state = self._needs.get(name)
        return bool(state and state.overflow)

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
