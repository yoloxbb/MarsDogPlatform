"""Temporal policy for the confirmed-owner presence Vision event."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

from marsdog_vision_interaction.messages.visual_event_types import (
    EVT_VISION_OWNER_PRESENT,
)


def _finite_duration(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


@dataclass(frozen=True)
class OwnerPresenceEventConfig:
    enabled: bool = True
    enter_duration_sec: float = 1.0
    exit_duration_sec: float = 2.0
    retrigger_delay_sec: float = 3.0

    @classmethod
    def from_mapping(cls, value: Any) -> "OwnerPresenceEventConfig":
        """Read and validate the root-level owner-presence policy."""
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("owner_presence_events must be a mapping")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("owner_presence_events.enabled must be boolean")
        return cls(
            enabled=enabled,
            enter_duration_sec=_finite_duration(
                value.get("enter_duration_sec", 1.0),
                name="owner_presence_events.enter_duration_sec",
            ),
            exit_duration_sec=_finite_duration(
                value.get("exit_duration_sec", 2.0),
                name="owner_presence_events.exit_duration_sec",
            ),
            retrigger_delay_sec=_finite_duration(
                value.get("retrigger_delay_sec", 3.0),
                name="owner_presence_events.retrigger_delay_sec",
            ),
        )


@dataclass(frozen=True)
class OwnerPresenceEventSnapshot:
    active: bool
    event_id: str = ""
    transition: str = ""


class OwnerPresenceEventState:
    """Debounce current, distinct owner observations into an active event.

    Source observation provenance is internal to Vision. The public v1 event
    carries ``observation_status`` and the stable event instance ID, while
    this policy also requires a per-frame owner target association so a
    temporarily retained tracker row is not mistaken for a current detection.
    """

    def __init__(
        self,
        config: OwnerPresenceEventConfig,
        *,
        source_freshness_sec: float = 0.5,
    ) -> None:
        self.config = config
        self.source_freshness_sec = _finite_duration(
            source_freshness_sec,
            name="owner-presence source freshness",
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
        """Clear the complete temporal state, for shutdown or reconfiguration."""
        self._vision_epoch = ""
        self._last_source_key = None
        self._last_distinct_at = None
        self._entry_started_at = None
        self._exit_started_at = None
        self._active_event_id = ""
        self._cooldown_until = 0.0
        self._cycle = 0

    def update(
        self,
        observation: dict[str, Any],
        *,
        now: float,
    ) -> OwnerPresenceEventSnapshot:
        """Consume one published snapshot; repeated source frames do not count."""
        if not self.config.enabled:
            return OwnerPresenceEventSnapshot(False)
        if isinstance(now, bool) or not isinstance(now, Real) or not math.isfinite(float(now)):
            raise ValueError("now must be a finite monotonic timestamp")
        now = float(now)
        epoch = str(observation.get("vision_epoch", "") or "").strip()
        if not epoch:
            return self._invalid_observation()

        if epoch != self._vision_epoch:
            # Keep an active event instance across an epoch boundary, but do
            # not carry timing evidence or old source identity into the epoch.
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
            or not isinstance(observation.get("_source_owner_target_ids"), list)
        ):
            return self._invalid_observation()

        source_key = (epoch, source_id)
        if source_key == self._last_source_key:
            return self._snapshot()

        if (
            self._last_distinct_at is not None
            and now - self._last_distinct_at > self.source_freshness_sec
        ):
            # A gap between successful sources breaks both entry and exit
            # continuity. Active presence remains active through that gap.
            self._entry_started_at = None
            self._exit_started_at = None
        self._last_source_key = source_key
        self._last_distinct_at = now

        owner_present = self._has_current_confirmed_owner(observation)
        if self._active_event_id:
            if owner_present:
                self._exit_started_at = None
                return self._snapshot()
            if self._exit_started_at is None:
                self._exit_started_at = now
            if now - self._exit_started_at >= self.config.exit_duration_sec:
                self._active_event_id = ""
                self._exit_started_at = None
                self._entry_started_at = None
                self._cooldown_until = now + self.config.retrigger_delay_sec
                return OwnerPresenceEventSnapshot(False, transition="EXIT")
            return self._snapshot()

        if now < self._cooldown_until:
            self._entry_started_at = None
            return OwnerPresenceEventSnapshot(False)

        if not owner_present:
            self._entry_started_at = None
            return OwnerPresenceEventSnapshot(False)
        if self._entry_started_at is None:
            self._entry_started_at = now
            return OwnerPresenceEventSnapshot(False)
        if now - self._entry_started_at < self.config.enter_duration_sec:
            return OwnerPresenceEventSnapshot(False)

        self._cycle += 1
        self._active_event_id = f"{epoch}:owner-presence:{self._cycle}"
        self._entry_started_at = None
        return OwnerPresenceEventSnapshot(
            True,
            event_id=self._active_event_id,
            transition="ENTER",
        )

    def _invalid_observation(self) -> OwnerPresenceEventSnapshot:
        # Invalid evidence interrupts pending continuity; it does not mean the
        # owner has left and therefore cannot end an active event.
        self._entry_started_at = None
        self._exit_started_at = None
        self._last_distinct_at = None
        return self._snapshot()

    def _source_age_is_fresh(self, value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, Real):
            return False
        age = float(value)
        return math.isfinite(age) and 0.0 <= age <= self.source_freshness_sec

    @staticmethod
    def _has_current_confirmed_owner(observation: dict[str, Any]) -> bool:
        source_owner_ids = {
            str(value).strip()
            for value in observation.get("_source_owner_target_ids", [])
            if isinstance(value, str) and value.strip()
        }
        if not source_owner_ids:
            return False
        epoch = str(observation.get("vision_epoch", "") or "")
        candidates = observation.get("human_candidates")
        if not isinstance(candidates, list):
            return False
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            target_id = str(candidate.get("target_id", "") or "").strip()
            candidate_epoch = str(candidate.get("vision_epoch", "") or "")
            track_id = candidate.get("track_id")
            if (
                target_id not in source_owner_ids
                or candidate.get("identity") != "owner"
                or candidate.get("identity_state") != "confirmed_known"
                or candidate.get("tracking_state") != "tracking"
                or candidate_epoch != epoch
                or isinstance(track_id, bool)
                or not isinstance(track_id, int)
                or track_id <= 0
            ):
                continue
            return True
        return False

    def _snapshot(self) -> OwnerPresenceEventSnapshot:
        return OwnerPresenceEventSnapshot(
            bool(self._active_event_id),
            event_id=self._active_event_id,
            transition="HOLD" if self._active_event_id else "",
        )
