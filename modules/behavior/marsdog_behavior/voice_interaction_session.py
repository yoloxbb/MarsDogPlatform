"""State carried across wake orientation, visual acquire and approach."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ORIENTING = "ORIENTING"
AWAITING_IDENTITY = "AWAITING_IDENTITY"
ACQUIRING_TARGET = "ACQUIRING_TARGET"
APPROACHING = "APPROACHING"
WAITING = "WAITING"
CLOSED = "CLOSED"


@dataclass
class VoiceInteractionSession:
    """One wake-to-idle interaction, independent from attention control."""

    interaction_id: str
    generation: int
    phase: str = ORIENTING
    wake_event_stamp: float = 0.0
    wake_angle_deg: float = 0.0
    wake_frame_id: str = ""
    wake_confidence: float = 0.0
    selected_target: dict[str, Any] | None = None
    hold_token: str = ""
    hold_active: bool = False
    hold_request_pending: bool = False
    last_hold_attempted_at: float = 0.0
    last_hold_renewed_at: float = 0.0
    command_received: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.phase != CLOSED

    def matches(self, interaction_id: str, generation: int | None = None) -> bool:
        return bool(
            self.active
            and interaction_id
            and interaction_id == self.interaction_id
            and (generation is None or generation == self.generation)
        )

    def consume_turn(self, kind: str) -> None:
        """Mark one accepted command/reaction as owning the current turn.

        ``command_received`` remains as the compatibility gate used by the
        existing wake lifecycle.  ``accepted_turn_kind`` preserves whether the
        turn was an executable command or a non-command social reaction.
        """
        normalized = str(kind).strip()
        if not normalized:
            raise ValueError("accepted turn kind must be non-empty")
        self.command_received = True
        self.metadata["accepted_turn_kind"] = normalized
