"""Owner-only bend/squat visual event state."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any


OWNER_BEND_SQUAT_POSES = frozenset({"bend_over", "squat_down"})


def _positive_duration(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


@dataclass(frozen=True)
class OwnerPostureEventConfig:
    enabled: bool = True
    enter_duration_sec: float = 1.0

    @classmethod
    def from_mapping(cls, value: Any) -> "OwnerPostureEventConfig":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("owner_posture_events must be a mapping")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("owner_posture_events.enabled must be boolean")
        return cls(
            enabled=enabled,
            enter_duration_sec=_positive_duration(
                value.get("enter_duration_sec", 1.0),
                name="owner_posture_events.enter_duration_sec",
            ),
        )


@dataclass(frozen=True)
class OwnerPostureEventSnapshot:
    active: bool
    event_id: str = ""
    transition: str = ""


class OwnerPostureEventState:
    """Debounce one confirmed owner's public bend/squat pose into a state event.

    The state consumes current source-frame owner associations and the already
    smoothed public pose_action. It does not inspect classifier scores or
    maintain a second release threshold. Repeated snapshots of one source
    observation are idempotent.
    """

    def __init__(
        self,
        config: OwnerPostureEventConfig,
        *,
        source_freshness_sec: float = 0.5,
    ) -> None:
        self.config = config
        self.source_freshness_sec = _positive_duration(
            source_freshness_sec,
            name="owner-posture source freshness",
        )
        self.reset()

    def reset(self) -> None:
        """Clear policy state for shutdown or explicit reconfiguration."""
        self._vision_epoch = ""
        self._last_source_key: tuple[str, str] | None = None
        self._last_distinct_at: float | None = None
        self._entry_started_at: float | None = None
        self._entry_target_id = ""
        self._entry_track_id = 0
        self._active_event_id = ""
        self._active_target_id = ""
        self._active_track_id = 0
        self._disarmed_target_id = ""
        self._disarmed_track_id = 0
        self._cycle = 0

    def update(
        self,
        observation: dict[str, Any],
        *,
        now: float,
    ) -> OwnerPostureEventSnapshot:
        """Consume one snapshot; only distinct valid source frames can advance."""
        if not self.config.enabled:
            return OwnerPostureEventSnapshot(False)
        if (
            isinstance(now, bool)
            or not isinstance(now, Real)
            or not math.isfinite(float(now))
        ):
            raise ValueError("now must be a finite monotonic timestamp")
        now = float(now)
        if not isinstance(observation, dict):
            return self._invalid_observation()

        epoch_value = observation.get("vision_epoch")
        epoch = epoch_value.strip() if isinstance(epoch_value, str) else ""
        if not epoch:
            return self._invalid_observation()

        source_id_value = observation.get("source_observation_id")
        source_id = (
            source_id_value.strip()
            if isinstance(source_id_value, str)
            else ""
        )
        source_age = observation.get("_source_observation_age_sec")
        source_target_ids = observation.get("_source_owner_target_ids")
        source_human_target_ids = observation.get(
            "_source_human_target_ids"
        )
        if (
            observation.get("observation_status") != "valid"
            or not source_id
            or not self._source_age_is_fresh(source_age)
            or not isinstance(source_target_ids, list)
            or not isinstance(source_human_target_ids, list)
        ):
            return self._invalid_observation()

        if epoch != self._vision_epoch:
            # Only a complete fresh source observation can establish an epoch
            # transition. Invalid/stale packets cannot discard an active cycle.
            self._clear_cycle()
            self._reset_disarmed()
            self._vision_epoch = epoch
            self._last_source_key = None
            self._last_distinct_at = None

        source_key = (epoch, source_id)
        if source_key == self._last_source_key:
            return self._snapshot()

        if (
            self._last_distinct_at is not None
            and (
                now < self._last_distinct_at
                or now - self._last_distinct_at > self.source_freshness_sec
            )
        ):
            self._reset_entry()
        self._last_source_key = source_key
        self._last_distinct_at = now

        source_ids = {
            value.strip()
            for value in source_target_ids
            if isinstance(value, str) and value.strip()
        }
        source_human_ids = {
            value.strip()
            for value in source_human_target_ids
            if isinstance(value, str) and value.strip()
        }
        owners = self._qualified_source_owners(observation, source_ids, epoch)

        if self._active_event_id:
            bound = next(
                (
                    item for item in owners
                    if item["target_id"] == self._active_target_id
                    and item["track_id"] == self._active_track_id
                ),
                None,
            )
            if bound is not None:
                if bound["pose_action"] in OWNER_BEND_SQUAT_POSES:
                    return self._snapshot()
                self._clear_cycle()
                return OwnerPostureEventSnapshot(False, transition="EXIT")

            # A current owner target replacing the bound target is a context
            # switch. Drop the previous cycle and require a full entry period.
            if owners:
                self._clear_cycle()
            else:
                # A missing current owner association is not pose-release
                # evidence. Explicit identity/tracking loss on the same target
                # does end its owner-scoped cycle; a retained row alone does not.
                lost_context = self._bound_target_lost_owner_context(
                    observation, epoch, source_human_ids
                )
                if lost_context is not None:
                    lost_target_id = self._active_target_id
                    lost_track_id = self._active_track_id
                    self._clear_cycle()
                    if lost_context.get("pose_action", "") in OWNER_BEND_SQUAT_POSES:
                        self._disarmed_target_id = lost_target_id
                        self._disarmed_track_id = lost_track_id
                    return OwnerPostureEventSnapshot(
                        False, transition="EXIT"
                    )
                return self._snapshot()

        if self._disarmed_target_id:
            disarmed = self._matching_candidate(
                observation,
                target_id=self._disarmed_target_id,
                track_id=self._disarmed_track_id,
                epoch=epoch,
            ) if self._disarmed_target_id in source_human_ids else None
            posture_owners = [
                item for item in owners
                if item["pose_action"] in OWNER_BEND_SQUAT_POSES
            ]
            if posture_owners and any(
                item["target_id"] != self._disarmed_target_id
                or item["track_id"] != self._disarmed_track_id
                for item in posture_owners
            ):
                # A new target owns its own complete entry cycle.
                self._reset_disarmed()
            elif disarmed is not None:
                if disarmed.get("pose_action") in OWNER_BEND_SQUAT_POSES:
                    self._reset_entry()
                    return OwnerPostureEventSnapshot(False)
                # Only a valid observation of this exact target with a cleared
                # public pose rearms it; do not start a new cycle on that frame.
                self._reset_disarmed()
                self._reset_entry()
                return OwnerPostureEventSnapshot(False)
            else:
                self._reset_entry()
                return OwnerPostureEventSnapshot(False)

        posture_owners = [
            item for item in owners
            if item["pose_action"] in OWNER_BEND_SQUAT_POSES
        ]
        if len(posture_owners) != 1:
            self._reset_entry()
            return OwnerPostureEventSnapshot(False)

        target = posture_owners[0]
        target_id = target["target_id"]
        track_id = target["track_id"]
        if (
            target_id != self._entry_target_id
            or track_id != self._entry_track_id
        ):
            self._reset_entry()
            self._entry_target_id = target_id
            self._entry_track_id = track_id
        if self._entry_started_at is None:
            self._entry_started_at = now
            return OwnerPostureEventSnapshot(False)
        if now - self._entry_started_at < self.config.enter_duration_sec:
            return OwnerPostureEventSnapshot(False)

        self._cycle += 1
        self._active_event_id = f"{epoch}:owner-posture:{self._cycle}"
        self._active_target_id = target_id
        self._active_track_id = track_id
        self._reset_entry()
        return OwnerPostureEventSnapshot(
            True,
            event_id=self._active_event_id,
            transition="ENTER",
        )

    def _qualified_source_owners(
        self,
        observation: dict[str, Any],
        source_ids: set[str],
        epoch: str,
    ) -> list[dict[str, Any]]:
        candidates = observation.get("human_candidates")
        if not isinstance(candidates, list):
            return []
        qualified: list[dict[str, Any]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            target_id = candidate.get("target_id")
            track_id = candidate.get("track_id")
            if (
                not isinstance(target_id, str)
                or target_id.strip() not in source_ids
                or candidate.get("identity") != "owner"
                or candidate.get("identity_state") != "confirmed_known"
                or candidate.get("tracking_state") != "tracking"
                or candidate.get("vision_epoch") != epoch
                or isinstance(track_id, bool)
                or not isinstance(track_id, int)
                or track_id <= 0
                or not self._candidate_is_fresh(candidate)
                or not isinstance(candidate.get("pose_action", ""), str)
            ):
                continue
            qualified.append({
                "target_id": target_id.strip(),
                "track_id": track_id,
                "pose_action": candidate.get("pose_action", ""),
            })
        return qualified

    def _bound_target_lost_owner_context(
        self,
        observation: dict[str, Any],
        epoch: str,
        source_human_ids: set[str],
    ) -> dict[str, Any] | None:
        """Return a same-target row after explicit identity/tracking changes."""
        candidates = observation.get("human_candidates")
        if not isinstance(candidates, list):
            return None
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if (
                candidate.get("target_id") == self._active_target_id
                and candidate.get("vision_epoch") == epoch
                and self._active_target_id in source_human_ids
                and self._candidate_is_fresh(candidate)
                and isinstance(candidate.get("pose_action", ""), str)
                and (
                    candidate.get("identity") != "owner"
                    or candidate.get("identity_state") != "confirmed_known"
                    or candidate.get("tracking_state") != "tracking"
                    or candidate.get("track_id") != self._active_track_id
                )
            ):
                return candidate
        return None

    @staticmethod
    def _matching_candidate(
        observation: dict[str, Any],
        *,
        target_id: str,
        track_id: int,
        epoch: str,
    ) -> dict[str, Any] | None:
        candidates = observation.get("human_candidates")
        if not isinstance(candidates, list):
            return None
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if (
                candidate.get("target_id") == target_id
                and candidate.get("track_id") == track_id
                and candidate.get("vision_epoch") == epoch
            ):
                if (
                    not OwnerPostureEventState._candidate_is_fresh(candidate)
                    or not isinstance(candidate.get("pose_action", ""), str)
                ):
                    return None
                return candidate
        return None

    @staticmethod
    def _candidate_is_fresh(candidate: dict[str, Any]) -> bool:
        age_ms = candidate.get("last_seen_age_ms")
        return (
            not isinstance(age_ms, bool)
            and isinstance(age_ms, Real)
            and math.isfinite(float(age_ms))
            and 0.0 <= float(age_ms) < 500.0
        )

    def _source_age_is_fresh(self, value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, Real):
            return False
        age = float(value)
        return math.isfinite(age) and 0.0 <= age <= self.source_freshness_sec

    def _invalid_observation(self) -> OwnerPostureEventSnapshot:
        # Invalid evidence cannot prove release. It interrupts only pending
        # entry continuity and the source-gap clock, preserving an active ID.
        self._reset_entry()
        self._last_distinct_at = None
        return self._snapshot()

    def _clear_cycle(self) -> None:
        self._active_event_id = ""
        self._active_target_id = ""
        self._active_track_id = 0
        self._reset_entry()

    def _reset_disarmed(self) -> None:
        self._disarmed_target_id = ""
        self._disarmed_track_id = 0

    def _reset_entry(self) -> None:
        self._entry_started_at = None
        self._entry_target_id = ""
        self._entry_track_id = 0

    def _snapshot(self) -> OwnerPostureEventSnapshot:
        return OwnerPostureEventSnapshot(
            bool(self._active_event_id),
            event_id=self._active_event_id,
            transition="HOLD" if self._active_event_id else "",
        )
