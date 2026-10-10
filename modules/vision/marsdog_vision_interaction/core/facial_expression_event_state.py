"""Temporal policy for owner facial-expression Vision events."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

from marsdog_vision_interaction.messages.facial_expression import (
    normalize_facial_expression,
)


HAPPY_EVENT = "EVT_VISION_MASTER_HAPPY"
SAD_EVENT = "EVT_VISION_MASTER_SAD"
_EXPRESSION_EVENTS = {"happy": HAPPY_EVENT, "sad": SAD_EVENT}


def _finite_number(value: Any, *, name: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        qualifier = "finite and > 0" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")
    return result


@dataclass(frozen=True)
class FacialExpressionEventConfig:
    enabled: bool = False
    minimum_confidence: float = 0.70
    stable_duration_sec: float = 1.0
    release_duration_sec: float = 0.5

    @classmethod
    def from_mapping(cls, value: Any) -> "FacialExpressionEventConfig":
        """Validate the optional root-level event policy configuration."""
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("facial_expression_events must be a mapping")
        enabled = value.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("facial_expression_events.enabled must be boolean")
        confidence = _finite_number(
            value.get("minimum_confidence", 0.70),
            name="facial_expression_events.minimum_confidence",
        )
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                "facial_expression_events.minimum_confidence must be in [0, 1]"
            )
        stable = _finite_number(
            value.get("stable_duration_sec", 1.0),
            name="facial_expression_events.stable_duration_sec",
            positive=True,
        )
        release = _finite_number(
            value.get("release_duration_sec", 0.5),
            name="facial_expression_events.release_duration_sec",
            positive=True,
        )
        return cls(enabled, confidence, stable, release)


class FacialExpressionEventState:
    """Debounce owner expression evidence without counting cached frames twice.

    ``facial_expression_valid_for_sec`` is the provider's remaining
    source-frame lifetime. The visual publisher can repeat the same source
    observation; these repeats may keep an active expression alive while the
    source remains fresh, but only a distinct source key advances entry.
    """

    def __init__(
        self,
        config: FacialExpressionEventConfig,
        *,
        source_freshness_sec: float = 0.5,
    ) -> None:
        self.config = config
        self.source_freshness_sec = _finite_number(
            source_freshness_sec,
            name="facial_expression source freshness",
            positive=True,
        )
        self._vision_epoch: str | None = None
        self._last_source_key: tuple[str, float, str, int] | None = None
        self._candidate: str | None = None
        self._candidate_started_at: float | None = None
        self._candidate_last_frame_at: float | None = None
        self._candidate_last_key: tuple[str, float, str, int] | None = None
        self._active: str | None = None
        self._release_started_at: float | None = None

    def reset(self) -> None:
        """Clear pending and active evidence, for epoch changes or shutdown."""
        self._last_source_key = None
        self._candidate = None
        self._candidate_started_at = None
        self._candidate_last_frame_at = None
        self._candidate_last_key = None
        self._active = None
        self._release_started_at = None

    def update(self, observation: dict[str, Any], *, now: float) -> list[str]:
        """Return event names currently supported by facial expression."""
        now = _finite_number(now, name="now")
        if not self.config.enabled:
            self.reset()
            return []

        event = observation if isinstance(observation, dict) else {}
        epoch = str(event.get("vision_epoch", ""))
        if self._vision_epoch is None:
            self._vision_epoch = epoch
        elif epoch != self._vision_epoch:
            self.reset()
            self._vision_epoch = epoch

        active_target = event.get("active_target", {})
        if not isinstance(active_target, dict):
            active_target = {}
        face_track_id = self._positive_track_id(active_target.get("face_track_id"))
        source_key = self._source_key(event, face_track_id)
        new_source = source_key is not None and source_key != self._last_source_key
        if source_key is not None:
            self._last_source_key = source_key

        expression = self._qualified_expression(
            event,
            active_target,
            face_track_id=face_track_id,
        )
        if source_key is None:
            expression = None

        if expression is None:
            self._clear_candidate()
        else:
            self._observe_candidate(expression, source_key, new_source, now)

        if self._active is not None:
            if expression == self._active:
                self._release_started_at = None
            else:
                if self._release_started_at is None:
                    self._release_started_at = now
                elif now - self._release_started_at >= self.config.release_duration_sec:
                    self._active = None
                    self._release_started_at = None

        # Entry can only occur on a new qualifying source frame, never on a
        # timer tick that repeats the last cached observation.
        if (
            self._active is None
            and expression is not None
            and new_source
            and self._candidate == expression
            and self._candidate_started_at is not None
            and self._candidate_last_frame_at is not None
            and now - self._candidate_started_at >= self.config.stable_duration_sec
            and now - self._candidate_last_frame_at <= self.source_freshness_sec
        ):
            self._active = expression
            self._release_started_at = None

        event_name = _EXPRESSION_EVENTS.get(self._active or "")
        return [event_name] if event_name else []

    def _observe_candidate(
        self,
        expression: str,
        source_key: tuple[str, float, str, int],
        new_source: bool,
        now: float,
    ) -> None:
        if self._candidate != expression or self._candidate_started_at is None:
            self._candidate = expression
            self._candidate_started_at = now
            self._candidate_last_frame_at = now
            self._candidate_last_key = source_key
            return

        if not new_source or source_key == self._candidate_last_key:
            if (
                self._candidate_last_frame_at is not None
                and now - self._candidate_last_frame_at > self.source_freshness_sec
            ):
                self._clear_candidate()
            return

        if (
            self._candidate_last_frame_at is None
            or now - self._candidate_last_frame_at > self.source_freshness_sec
        ):
            self._candidate_started_at = now
        self._candidate_last_frame_at = now
        self._candidate_last_key = source_key

    def _qualified_expression(
        self,
        event: dict[str, Any],
        active_target: dict[str, Any],
        *,
        face_track_id: int | None,
    ) -> str | None:
        if (
            str(active_target.get("identity", "")) != "owner"
            or str(active_target.get("identity_state", "")) != "confirmed_known"
            or str(active_target.get("tracking_state", "")) != "tracking"
            or face_track_id is None
        ):
            return None
        target_epoch = active_target.get("vision_epoch")
        if target_epoch not in (None, "") and str(target_epoch) != str(
            event.get("vision_epoch", "")
        ):
            return None

        remaining = event.get("facial_expression_valid_for_sec")
        try:
            remaining = _finite_number(
                remaining,
                name="facial_expression_valid_for_sec",
            )
        except ValueError:
            return None
        if remaining <= 0.0:
            return None

        faces = event.get("faces", [])
        if not isinstance(faces, list):
            return None
        face = next(
            (
                item
                for item in faces
                if isinstance(item, dict)
                and self._positive_track_id(item.get("track_id")) == face_track_id
            ),
            None,
        )
        if face is None:
            return None
        normalized = normalize_facial_expression(face.get("facial_expression"))
        if normalized is None or normalized["expression"] not in _EXPRESSION_EVENTS:
            return None
        if normalized["confidence"] < self.config.minimum_confidence:
            return None
        return str(normalized["expression"])

    @staticmethod
    def _source_key(
        event: dict[str, Any], face_track_id: int | None
    ) -> tuple[str, float, str, int] | None:
        if face_track_id is None:
            return None
        header = event.get("header", {})
        if not isinstance(header, dict):
            return None
        try:
            stamp = _finite_number(header.get("stamp"), name="source stamp")
        except ValueError:
            return None
        frame_id = str(header.get("frame_id", "")).strip()
        if stamp <= 0.0 or not frame_id:
            return None
        return (str(event.get("vision_epoch", "")), stamp, frame_id, face_track_id)

    @staticmethod
    def _positive_track_id(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if result > 0 else None

    def _clear_candidate(self) -> None:
        self._candidate = None
        self._candidate_started_at = None
        self._candidate_last_frame_at = None
        self._candidate_last_key = None
