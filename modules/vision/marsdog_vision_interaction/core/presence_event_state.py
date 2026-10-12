"""Reusable timing policy for source-backed visual presence events."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any


def _finite_duration(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


@dataclass(frozen=True)
class PresenceEventConfig:
    enabled: bool = True
    enter_duration_sec: float = 1.0
    exit_duration_sec: float = 2.0
    retrigger_delay_sec: float = 3.0

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        section_name: str,
    ) -> "PresenceEventConfig":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError(f"{section_name} must be a mapping")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"{section_name}.enabled must be boolean")
        return cls(
            enabled=enabled,
            enter_duration_sec=_finite_duration(
                value.get("enter_duration_sec", 1.0),
                name=f"{section_name}.enter_duration_sec",
            ),
            exit_duration_sec=_finite_duration(
                value.get("exit_duration_sec", 2.0),
                name=f"{section_name}.exit_duration_sec",
            ),
            retrigger_delay_sec=_finite_duration(
                value.get("retrigger_delay_sec", 3.0),
                name=f"{section_name}.retrigger_delay_sec",
            ),
        )


@dataclass(frozen=True)
class PresenceEventSnapshot:
    active: bool
    event_id: str = ""
    transition: str = ""


class PresenceEventState:
    """Debounce distinct valid source observations into an active event.

    ``source_target_ids_key`` is private Vision provenance assembled from the
    current inference, never from the tracker cache alone. Category events use
    one instance per event kind, so their active IDs are category scoped.
    """

    def __init__(
        self,
        config: PresenceEventConfig,
        *,
        event_tag: str,
        source_target_ids_key: str,
        identities: set[str],
        identity_state: str,
        source_freshness_sec: float = 0.5,
    ) -> None:
        self.config = config
        self.event_tag = event_tag
        self.source_target_ids_key = source_target_ids_key
        self.identities = frozenset(identities)
        self.identity_state = identity_state
        self.source_freshness_sec = _finite_duration(
            source_freshness_sec,
            name="presence-event source freshness",
        )
        self._vision_epoch = ""
        self._last_source_key: tuple[str, str] | None = None
        self._last_distinct_at: float | None = None
        self._entry_started_at: float | None = None
        self._exit_started_at: float | None = None
        self._active_event_id = ""
        self._cooldown_until = 0.0
        self._cycle = 0

    def reset(self) -> None:
        """Clear timing and cycle state for shutdown or reconfiguration."""
        self._vision_epoch = ""
        self._last_source_key = None
        self._last_distinct_at = None
        self._entry_started_at = None
        self._exit_started_at = None
        self._active_event_id = ""
        self._cooldown_until = 0.0
        self._cycle = 0

    def update(self, observation: dict[str, Any], *, now: float) -> PresenceEventSnapshot:
        """Consume one snapshot; republished source frames do not count."""
        if not self.config.enabled:
            return PresenceEventSnapshot(False)
        if isinstance(now, bool) or not isinstance(now, Real) or not math.isfinite(float(now)):
            raise ValueError("now must be a finite monotonic timestamp")
        now = float(now)
        epoch = str(observation.get("vision_epoch", "") or "").strip()
        if not epoch:
            return self._invalid_observation()

        if epoch != self._vision_epoch:
            # Do not transfer pending evidence or a source key across epochs.
            # An active state is allowed to remain until valid evidence exits.
            self._vision_epoch = epoch
            self._last_source_key = None
            self._last_distinct_at = None
            self._entry_started_at = None
            self._exit_started_at = None

        source_id = str(observation.get("source_observation_id", "") or "").strip()
        source_age = observation.get("_source_observation_age_sec")
        if (
            observation.get("observation_status") != "valid"
            or not source_id
            or not self._source_age_is_fresh(source_age)
            or not isinstance(observation.get(self.source_target_ids_key), list)
        ):
            return self._invalid_observation()

        source_key = (epoch, source_id)
        if source_key == self._last_source_key:
            return self._snapshot()

        if (
            self._last_distinct_at is not None
            and now - self._last_distinct_at > self.source_freshness_sec
        ):
            self._entry_started_at = None
            self._exit_started_at = None
        self._last_source_key = source_key
        self._last_distinct_at = now

        present = self._has_qualified_target(observation)
        if self._active_event_id:
            if present:
                self._exit_started_at = None
                return self._snapshot()
            if self._exit_started_at is None:
                self._exit_started_at = now
            if now - self._exit_started_at >= self.config.exit_duration_sec:
                self._active_event_id = ""
                self._exit_started_at = None
                self._entry_started_at = None
                self._cooldown_until = now + self.config.retrigger_delay_sec
                return PresenceEventSnapshot(False, transition="EXIT")
            return self._snapshot()

        if now < self._cooldown_until:
            self._entry_started_at = None
            return PresenceEventSnapshot(False)
        if not present:
            self._entry_started_at = None
            return PresenceEventSnapshot(False)
        if self._entry_started_at is None:
            self._entry_started_at = now
            return PresenceEventSnapshot(False)
        if now - self._entry_started_at < self.config.enter_duration_sec:
            return PresenceEventSnapshot(False)

        self._cycle += 1
        self._active_event_id = f"{epoch}:{self.event_tag}:{self._cycle}"
        self._entry_started_at = None
        return PresenceEventSnapshot(
            True,
            event_id=self._active_event_id,
            transition="ENTER",
        )

    def _invalid_observation(self) -> PresenceEventSnapshot:
        # Invalid evidence interrupts pending continuity; it cannot prove exit.
        self._entry_started_at = None
        self._exit_started_at = None
        self._last_distinct_at = None
        return self._snapshot()

    def _source_age_is_fresh(self, value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, Real):
            return False
        age = float(value)
        return math.isfinite(age) and 0.0 <= age <= self.source_freshness_sec

    def _has_qualified_target(self, observation: dict[str, Any]) -> bool:
        raw_ids = observation.get(self.source_target_ids_key, [])
        source_ids = {
            value.strip()
            for value in raw_ids
            if isinstance(value, str) and value.strip()
        }
        if not source_ids:
            return False
        epoch = str(observation.get("vision_epoch", "") or "")
        candidates = observation.get("human_candidates")
        if not isinstance(candidates, list):
            return False
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            target_id = candidate.get("target_id")
            track_id = candidate.get("track_id")
            if (
                not isinstance(target_id, str)
                or target_id.strip() not in source_ids
                or not isinstance(candidate.get("identity"), str)
                or candidate.get("identity") not in self.identities
                or candidate.get("identity_state") != self.identity_state
                or candidate.get("tracking_state") != "tracking"
                or str(candidate.get("vision_epoch", "")) != epoch
                or isinstance(track_id, bool)
                or not isinstance(track_id, int)
                or track_id <= 0
            ):
                continue
            return True
        return False

    def _snapshot(self) -> PresenceEventSnapshot:
        return PresenceEventSnapshot(
            bool(self._active_event_id),
            event_id=self._active_event_id,
            transition="HOLD" if self._active_event_id else "",
        )
