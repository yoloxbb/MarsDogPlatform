"""Compatibility API for the confirmed-owner presence Vision event."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from marsdog_vision_interaction.core.presence_event_state import (
    PresenceEventConfig,
    PresenceEventState,
)


@dataclass(frozen=True)
class OwnerPresenceEventConfig:
    enabled: bool = True
    enter_duration_sec: float = 1.0
    exit_duration_sec: float = 2.0
    retrigger_delay_sec: float = 3.0

    @classmethod
    def from_mapping(cls, value: Any) -> "OwnerPresenceEventConfig":
        parsed = PresenceEventConfig.from_mapping(
            value,
            section_name="owner_presence_events",
        )
        return cls(
            enabled=parsed.enabled,
            enter_duration_sec=parsed.enter_duration_sec,
            exit_duration_sec=parsed.exit_duration_sec,
            retrigger_delay_sec=parsed.retrigger_delay_sec,
        )


@dataclass(frozen=True)
class OwnerPresenceEventSnapshot:
    active: bool
    event_id: str = ""
    transition: str = ""


class OwnerPresenceEventState:
    """Debounce current, distinct owner observations into an active event.

    This public owner-specific class retains its existing constructor and
    update API. Timing lives in :class:`PresenceEventState`, which also backs
    the separately configured family and stranger state events.
    """

    def __init__(
        self,
        config: OwnerPresenceEventConfig,
        *,
        source_freshness_sec: float = 0.5,
    ) -> None:
        self.config = config
        self._state = PresenceEventState(
            PresenceEventConfig(
                enabled=config.enabled,
                enter_duration_sec=config.enter_duration_sec,
                exit_duration_sec=config.exit_duration_sec,
                retrigger_delay_sec=config.retrigger_delay_sec,
            ),
            event_tag="owner-presence",
            source_target_ids_key="_source_owner_target_ids",
            identities={"owner"},
            identity_state="confirmed_known",
            source_freshness_sec=source_freshness_sec,
        )
        self.source_freshness_sec = self._state.source_freshness_sec

    def reset(self) -> None:
        self._state.reset()

    def update(
        self,
        observation: dict[str, Any],
        *,
        now: float,
    ) -> OwnerPresenceEventSnapshot:
        snapshot = self._state.update(observation, now=now)
        return OwnerPresenceEventSnapshot(
            snapshot.active,
            event_id=snapshot.event_id,
            transition=snapshot.transition,
        )

    @staticmethod
    def _has_current_confirmed_owner(observation: dict[str, Any]) -> bool:
        """Retain the former owner-specific predicate for local callers."""
        return PresenceEventState(
            PresenceEventConfig(),
            event_tag="owner-presence",
            source_target_ids_key="_source_owner_target_ids",
            identities={"owner"},
            identity_state="confirmed_known",
        )._has_qualified_target(observation)
