"""Scene-level, source-backed state for visible supported toys."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

from marsdog_vision_interaction.core.held_object_pose import TOY_LABELS
from marsdog_vision_interaction.messages.visual_event_types import EVT_VISION_TOY


def _duration(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


def _finite_timestamp(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0.0 else None


@dataclass(frozen=True, slots=True)
class ToyPresenceEventConfig:
    enabled: bool = True
    enter_duration_sec: float = 1.0
    exit_duration_sec: float = 2.0
    retrigger_delay_sec: float = 3.0

    @classmethod
    def from_mapping(cls, value: Any) -> "ToyPresenceEventConfig":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("toy_presence_events must be a mapping")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("toy_presence_events.enabled must be boolean")
        return cls(
            enabled=enabled,
            enter_duration_sec=_duration(
                value.get("enter_duration_sec", 1.0),
                name="toy_presence_events.enter_duration_sec",
            ),
            exit_duration_sec=_duration(
                value.get("exit_duration_sec", 2.0),
                name="toy_presence_events.exit_duration_sec",
            ),
            retrigger_delay_sec=_duration(
                value.get("retrigger_delay_sec", 3.0),
                name="toy_presence_events.retrigger_delay_sec",
            ),
        )


@dataclass(frozen=True, slots=True)
class ToyPresenceEventSnapshot:
    active: bool
    event_id: str = ""
    transition: str = ""


class ToyPresenceEventState:
    """Debounce one aggregate "one or more toys visible" state.

    Evidence is one completed object-detector result, not a track or a 10 Hz
    visual snapshot. The detector remains responsible for its own confidence
    threshold. An empty result is negative only when its label scope includes
    every label in the existing toy set.
    """

    def __init__(
        self,
        config: ToyPresenceEventConfig,
        *,
        source_freshness_sec: float = 0.5,
        result_max_age_sec: float = 2.0,
    ) -> None:
        self.config = config
        self.source_freshness_sec = _duration(
            source_freshness_sec,
            name="toy-event source freshness",
        )
        self.result_max_age_sec = _duration(
            result_max_age_sec,
            name="toy-event result max age",
        )
        self.reset()

    def reset(self) -> None:
        self._vision_epoch = ""
        self._last_source_id = ""
        self._last_observation_at: float | None = None
        self._last_distinct_at: float | None = None
        self._entry_started_at: float | None = None
        self._exit_started_at: float | None = None
        self._active_event_id = ""
        self._cooldown_until = 0.0
        self._cycle = 0

    def update(
        self,
        observation: dict[str, Any],
        *,
        now: float,
    ) -> ToyPresenceEventSnapshot:
        """Consume one result callback using monotonic receipt time ``now``."""
        if not self.config.enabled:
            return ToyPresenceEventSnapshot(False)
        received_at = _finite_timestamp(now)
        if received_at is None:
            raise ValueError("now must be a finite monotonic timestamp")

        epoch = observation.get("vision_epoch")
        source_id = observation.get("source_observation_id")
        source_at = _finite_timestamp(
            observation.get("source_observation_monotonic")
        )
        epoch = epoch.strip() if isinstance(epoch, str) else ""
        source_id = source_id.strip() if isinstance(source_id, str) else ""
        if not epoch or not source_id or source_at is None:
            return self._unknown()

        if epoch != self._vision_epoch:
            # Pending evidence belongs to the old camera epoch. Preserve an
            # active cycle, but require fresh evidence in the new epoch to exit.
            self._vision_epoch = epoch
            self._last_source_id = ""
            self._last_observation_at = None
            self._last_distinct_at = None
            self._entry_started_at = None
            self._exit_started_at = None

        if source_id == self._last_source_id:
            return self.snapshot()
        if (
            self._last_observation_at is not None
            and source_at <= self._last_observation_at
        ):
            # Delayed results from an earlier camera frame cannot roll time
            # backwards or count as evidence.
            return self.snapshot()

        self._last_source_id = source_id
        self._last_observation_at = source_at

        if not self._result_is_valid(observation, received_at, source_at):
            return self._unknown()

        if (
            self._last_distinct_at is not None
            and source_at - self._last_distinct_at > self.source_freshness_sec
        ):
            self._entry_started_at = None
            self._exit_started_at = None
        self._last_distinct_at = source_at

        present = self._has_supported_toy(observation.get("objects"))
        if self._active_event_id:
            if present:
                self._exit_started_at = None
                return self.snapshot()
            if self._exit_started_at is None:
                self._exit_started_at = source_at
            if source_at - self._exit_started_at >= self.config.exit_duration_sec:
                self._active_event_id = ""
                self._entry_started_at = None
                self._exit_started_at = None
                self._cooldown_until = source_at + self.config.retrigger_delay_sec
                return ToyPresenceEventSnapshot(False, transition="EXIT")
            return self.snapshot()

        if source_at < self._cooldown_until:
            self._entry_started_at = None
            return ToyPresenceEventSnapshot(False)
        if not present:
            self._entry_started_at = None
            return ToyPresenceEventSnapshot(False)
        if self._entry_started_at is None:
            self._entry_started_at = source_at
            return ToyPresenceEventSnapshot(False)
        if source_at - self._entry_started_at < self.config.enter_duration_sec:
            return ToyPresenceEventSnapshot(False)

        self._cycle += 1
        self._active_event_id = f"{epoch}:toy-presence:{self._cycle}"
        self._entry_started_at = None
        return ToyPresenceEventSnapshot(
            True,
            event_id=self._active_event_id,
            transition="ENTER",
        )

    def snapshot(self) -> ToyPresenceEventSnapshot:
        if self._active_event_id:
            return ToyPresenceEventSnapshot(
                True,
                event_id=self._active_event_id,
                transition="HOLD",
            )
        return ToyPresenceEventSnapshot(False)

    def _result_is_valid(
        self,
        observation: dict[str, Any],
        received_at: float,
        source_at: float,
    ) -> bool:
        if observation.get("status") != "ok":
            return False
        age = received_at - source_at
        if age < 0.0 or age > self.result_max_age_sec:
            return False
        objects = observation.get("objects")
        if not isinstance(objects, list):
            return False
        if self._has_supported_toy(objects):
            return True
        # Invalid rows cannot prove that the scene contains no toy. A valid
        # positive row is sufficient above, but negative evidence requires a
        # structurally valid detector result, including every returned row.
        if any(not self._is_valid_object(item) for item in objects):
            return False
        if observation.get("target_labels_valid") is not True:
            return False
        labels = observation.get("target_labels")
        if not isinstance(labels, list):
            return False
        normalized = {
            label.strip().casefold()
            for label in labels
            if isinstance(label, str) and label.strip()
        }
        return not normalized or {
            label.casefold() for label in TOY_LABELS
        }.issubset(normalized)

    @staticmethod
    def _has_supported_toy(objects: Any) -> bool:
        if not isinstance(objects, list):
            return False
        for item in objects:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            if not isinstance(label, str):
                continue
            normalized = " ".join(label.strip().casefold().split())
            if normalized not in TOY_LABELS:
                continue
            if ToyPresenceEventState._is_valid_object(item):
                return True
        return False

    @staticmethod
    def _is_valid_object(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            return False
        # The detector already applied its task threshold. Check only that
        # the recognized result has structurally valid box/confidence data.
        try:
            confidence = float(item.get("confidence"))
            x = float(item.get("x"))
            y = float(item.get("y"))
            w = float(item.get("w"))
            h = float(item.get("h"))
        except (TypeError, ValueError):
            return False
        return (
            all(math.isfinite(value) for value in (confidence, x, y, w, h))
            and 0.0 <= confidence <= 1.0
            and w > 0.0
            and h > 0.0
        )

    def _unknown(self) -> ToyPresenceEventSnapshot:
        # Unknown results interrupt pending durations but cannot end an active
        # cycle or replace its stable ID.
        self._entry_started_at = None
        self._exit_started_at = None
        self._last_distinct_at = None
        return self.snapshot()
