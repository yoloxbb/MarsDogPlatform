"""Owner beckoning/waving recall gesture visual event state."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from numbers import Real
from typing import Any


OWNER_RECALL_GESTURE_ACTIONS = frozenset({"beckoning", "waving"})


@dataclass(frozen=True)
class OwnerRecallGestureEventConfig:
    enabled: bool = True

    @classmethod
    def from_mapping(cls, value: Any) -> "OwnerRecallGestureEventConfig":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("owner_recall_gesture_events must be a mapping")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("owner_recall_gesture_events.enabled must be boolean")
        return cls(enabled=enabled)


@dataclass(frozen=True)
class OwnerRecallGestureEventSnapshot:
    active: bool
    event_id: str = ""
    transition: str = ""


class OwnerRecallGestureEventState:
    """Emit one instance for a continuous stable owner recall gesture.

    Only exact, temporally stabilized GesturePose ``recognized_actions`` are
    consumed. ``beckoning`` and ``waving`` share one episode; static
    ``arms_raised`` is neither a trigger nor a release blocker. Event state
    uses source-valid current target provenance and does not add a second
    confidence or timing threshold.
    """

    def __init__(
        self,
        config: OwnerRecallGestureEventConfig,
        *,
        source_freshness_sec: float = 0.5,
    ) -> None:
        self.config = config
        if (
            isinstance(source_freshness_sec, bool)
            or not isinstance(source_freshness_sec, Real)
            or not math.isfinite(float(source_freshness_sec))
            or float(source_freshness_sec) <= 0.0
        ):
            raise ValueError("source_freshness_sec must be finite and positive")
        self.source_freshness_sec = float(source_freshness_sec)
        self.reset()

    def reset(self) -> None:
        self._vision_epoch = ""
        self._seen_source_keys: set[tuple[str, str]] = set()
        self._source_key_order: deque[tuple[str, str]] = deque()
        self._active_event_id = ""
        self._active_target_id = ""
        self._active_track_id = 0
        self._active_gesture_sides: dict[str, set[str]] = {}
        self._disarmed = False
        self._disarmed_target_id = ""
        self._disarmed_track_id = 0
        self._disarmed_gesture_sides: dict[str, set[str]] = {}
        self._cycle = 0

    def update(
        self,
        observation: dict[str, Any],
        *,
        now: float,
    ) -> OwnerRecallGestureEventSnapshot:
        """Consume one snapshot, treating invalid/repeated input as no evidence."""
        if not self.config.enabled:
            return OwnerRecallGestureEventSnapshot(False)
        if (
            isinstance(now, bool)
            or not isinstance(now, Real)
            or not math.isfinite(float(now))
        ):
            raise ValueError("now must be a finite monotonic timestamp")
        if not isinstance(observation, dict):
            return self._snapshot()

        epoch_value = observation.get("vision_epoch")
        epoch = epoch_value.strip() if isinstance(epoch_value, str) else ""
        source_value = observation.get("source_observation_id")
        source_id = source_value.strip() if isinstance(source_value, str) else ""
        source_age = observation.get("_source_observation_age_sec")
        if (
            observation.get("observation_status") != "valid"
            or not epoch
            or not source_id
            or not self._source_age_is_fresh(source_age)
            or not isinstance(observation.get("_source_owner_target_ids"), list)
            or not isinstance(observation.get("_source_human_target_ids"), list)
        ):
            return self._snapshot()

        source_key = (epoch, source_id)
        if source_key in self._seen_source_keys:
            return self._snapshot()

        owners = self._qualified_source_owners(observation, epoch)
        gesture = self._stable_gesture_observation(observation)

        if epoch != self._vision_epoch:
            had_bound_cycle = bool(self._active_event_id or self._disarmed)
            if self._active_event_id:
                self._disarmed_gesture_sides = self._copy_gesture_sides(
                    self._active_gesture_sides
                )
            self._clear_active(clear_gesture_sides=True)
            self._vision_epoch = epoch
            self._remember_source_key(source_key)
            if had_bound_cycle:
                self._disarm_for_current_owner(owners)
                return OwnerRecallGestureEventSnapshot(False, transition="EXIT")

        self._remember_source_key(source_key)
        if self._active_event_id:
            same_bound_owner = any(
                owner["target_id"] == self._active_target_id
                and owner["track_id"] == self._active_track_id
                for owner in owners
            )
            if not same_bound_owner and (
                owners or self._bound_target_lost_owner_context(observation, epoch)
            ):
                # Target retirement is independent of gesture availability.
                # Otherwise a missing classifier result could leave an old
                # instance published alongside a new owner's target context.
                target_id = self._active_target_id
                track_id = self._active_track_id
                self._disarmed_gesture_sides = self._copy_gesture_sides(
                    self._active_gesture_sides
                )
                self._clear_active(clear_gesture_sides=True)
                self._disarm_for_current_owner(owners)
                if not owners:
                    self._disarmed_target_id = target_id
                    self._disarmed_track_id = track_id
                return OwnerRecallGestureEventSnapshot(False, transition="EXIT")

        if gesture is None:
            # Missing or malformed internal classifier evidence cannot prove
            # release and cannot start a new event.
            return self._snapshot()

        (
            gesture_target_id,
            gesture_track_id,
            recognized,
            valid_sides,
            release_sides,
            active_sides,
        ) = gesture
        gesture_owner = next(
            (
                owner for owner in owners
                if owner["target_id"] == gesture_target_id
                and owner["track_id"] == gesture_track_id
            ),
            None,
        )
        active_target = observation.get("active_target")
        active_matches_gesture = bool(
            isinstance(active_target, dict)
            and active_target.get("target_id") == gesture_target_id
            and active_target.get("track_id") == gesture_track_id
            and active_target.get("identity") == "owner"
            and active_target.get("identity_state") == "confirmed_known"
            and active_target.get("tracking_state") == "tracking"
            and active_target.get("vision_epoch") == epoch
            and self._candidate_is_fresh(active_target)
        )

        if self._active_event_id:
            same_bound_owner = next(
                (
                    owner for owner in owners
                    if owner["target_id"] == self._active_target_id
                    and owner["track_id"] == self._active_track_id
                ),
                None,
            )
            if same_bound_owner is not None:
                if (
                    gesture_owner is None
                    or gesture_target_id != self._active_target_id
                    or gesture_track_id != self._active_track_id
                    or not active_matches_gesture
                ):
                    # Classifier provenance has moved away from the bound
                    # track. Do not use it to release or replace that cycle.
                    return self._snapshot()
                if recognized:
                    self._remember_gesture_sides(
                        self._active_gesture_sides,
                        recognized,
                        valid_sides,
                        active_sides,
                    )
                    return self._snapshot()
                if not self._gesture_release_is_valid(
                    self._active_gesture_sides, release_sides
                ):
                    # A missing hand, invalid finger geometry, or unavailable
                    # wrist source is not a gesture-clear observation even if
                    # GesturePose temporarily drops its stable action label.
                    return self._snapshot()
                event_id = self._active_event_id
                self._clear_active(clear_gesture_sides=True)
                return OwnerRecallGestureEventSnapshot(
                    False, transition="EXIT", event_id=event_id
                )

            # A missing current source association is not release evidence.
            return self._snapshot()

        if self._disarmed:
            if len(owners) != 1:
                return OwnerRecallGestureEventSnapshot(False)
            owner = owners[0]
            if (
                not self._disarmed_target_id
                or
                owner["target_id"] != self._disarmed_target_id
                or owner["track_id"] != self._disarmed_track_id
            ):
                self._disarmed_target_id = owner["target_id"]
                self._disarmed_track_id = owner["track_id"]
                return OwnerRecallGestureEventSnapshot(False)
            if (
                gesture_owner is not owner
                or not active_matches_gesture
            ):
                return OwnerRecallGestureEventSnapshot(False)
            if recognized:
                self._remember_gesture_sides(
                    self._disarmed_gesture_sides,
                    recognized,
                    valid_sides,
                    active_sides,
                )
                return OwnerRecallGestureEventSnapshot(False)
            if not self._gesture_release_is_valid(
                self._disarmed_gesture_sides, release_sides
            ):
                return OwnerRecallGestureEventSnapshot(False)
            # Only a distinct valid observation of this same current owner
            # with valid source evidence for the prior gesture's same sides
            # and both accepted stable actions absent rearms the next cycle.
            self._disarmed = False
            self._disarmed_target_id = ""
            self._disarmed_track_id = 0
            self._disarmed_gesture_sides.clear()
            return OwnerRecallGestureEventSnapshot(False, transition="REARM")

        if len(owners) != 1:
            return OwnerRecallGestureEventSnapshot(False)
        owner = owners[0]
        if (
            gesture_owner is not owner
            or not active_matches_gesture
            or not recognized
            or any(not valid_sides.get(action) for action in recognized)
        ):
            return OwnerRecallGestureEventSnapshot(False)

        self._cycle += 1
        self._active_event_id = f"{epoch}:owner-recall:{self._cycle}"
        self._active_target_id = owner["target_id"]
        self._active_track_id = owner["track_id"]
        self._active_gesture_sides = {}
        self._remember_gesture_sides(
            self._active_gesture_sides,
            recognized,
            valid_sides,
            active_sides,
        )
        return OwnerRecallGestureEventSnapshot(
            True,
            event_id=self._active_event_id,
            transition="ENTER",
        )

    def _qualified_source_owners(
        self,
        observation: dict[str, Any],
        epoch: str,
    ) -> list[dict[str, Any]]:
        source_ids = {
            item.strip()
            for item in observation.get("_source_owner_target_ids", [])
            if isinstance(item, str) and item.strip()
        }
        candidates = observation.get("human_candidates")
        if not isinstance(candidates, list):
            return []
        owners = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            target_id = candidate.get("target_id")
            track_id = candidate.get("track_id")
            if (
                not isinstance(target_id, str)
                or target_id.strip() not in source_ids
                or candidate.get("target_type", "human") != "human"
                or candidate.get("identity") != "owner"
                or candidate.get("identity_state") != "confirmed_known"
                or candidate.get("tracking_state") != "tracking"
                or candidate.get("vision_epoch") != epoch
                or isinstance(track_id, bool)
                or not isinstance(track_id, int)
                or track_id <= 0
                or not self._candidate_is_fresh(candidate)
            ):
                continue
            owners.append({"target_id": target_id.strip(), "track_id": track_id})
        return owners

    def _stable_gesture_observation(
        self,
        observation: dict[str, Any],
    ) -> tuple[
        str,
        int,
        frozenset[str],
        dict[str, frozenset[str]],
        dict[str, frozenset[str]],
        dict[str, frozenset[str]],
    ] | None:
        diagnostics = observation.get("_gesture_diagnostics")
        if not isinstance(diagnostics, dict):
            return None
        raw_actions = diagnostics.get("recognized_actions")
        if not isinstance(raw_actions, list):
            return None
        target_id_value = observation.get("_gesture_target_id")
        target_id = target_id_value.strip() if isinstance(target_id_value, str) else ""
        track_id = observation.get("_gesture_track_id")
        if (
            not target_id
            or isinstance(track_id, bool)
            or not isinstance(track_id, int)
            or track_id <= 0
        ):
            return None
        names = set()
        for action in raw_actions:
            if not isinstance(action, dict) or not isinstance(action.get("name"), str):
                return None
            names.add(action["name"])
        evidence = diagnostics.get("recall_gesture_evidence")
        if not isinstance(evidence, dict):
            return None
        valid_sides: dict[str, frozenset[str]] = {}
        release_sides: dict[str, frozenset[str]] = {}
        active_sides: dict[str, frozenset[str]] = {}
        for gesture_name in OWNER_RECALL_GESTURE_ACTIONS:
            entry = evidence.get(gesture_name)
            if not isinstance(entry, dict):
                return None
            valid_value = entry.get("valid_sides")
            release_value = entry.get("release_sides")
            active_value = entry.get("active_sides")
            if (
                not isinstance(valid_value, list)
                or not isinstance(release_value, list)
                or not isinstance(active_value, list)
                or any(side not in {"left", "right"} for side in valid_value)
                or any(side not in {"left", "right"} for side in release_value)
                or any(side not in {"left", "right"} for side in active_value)
            ):
                return None
            valid = frozenset(valid_value)
            release = frozenset(release_value)
            active = frozenset(active_value)
            if not release.issubset(valid) or not active.issubset(valid):
                return None
            valid_sides[gesture_name] = valid
            release_sides[gesture_name] = release
            active_sides[gesture_name] = active
        recognized = frozenset(names & OWNER_RECALL_GESTURE_ACTIONS)
        if any(not valid_sides.get(action) for action in recognized):
            # Do not trigger from a classifier's retained label when the
            # current source cannot support that action category. It also
            # cannot prove that all accepted stable labels have cleared.
            return None
        return (
            target_id,
            track_id,
            recognized,
            valid_sides,
            release_sides,
            active_sides,
        )

    @staticmethod
    def _remember_gesture_sides(
        destination: dict[str, set[str]],
        gesture_names: frozenset[str],
        valid_sides: dict[str, frozenset[str]],
        active_sides: dict[str, frozenset[str]],
    ) -> None:
        for name in gesture_names:
            sides = active_sides.get(name) or valid_sides.get(name, frozenset())
            if sides:
                destination.setdefault(name, set()).update(sides)

    @staticmethod
    def _gesture_release_is_valid(
        required_sides: dict[str, set[str]],
        release_sides: dict[str, frozenset[str]],
    ) -> bool:
        return bool(required_sides) and all(
            sides and sides.issubset(release_sides.get(name, frozenset()))
            for name, sides in required_sides.items()
        )

    @staticmethod
    def _copy_gesture_sides(
        values: dict[str, set[str]],
    ) -> dict[str, set[str]]:
        return {name: set(sides) for name, sides in values.items() if sides}

    def _bound_target_lost_owner_context(
        self,
        observation: dict[str, Any],
        epoch: str,
    ) -> bool:
        source_human_ids = observation.get("_source_human_target_ids")
        if not isinstance(source_human_ids, list) or self._active_target_id not in source_human_ids:
            return False
        candidates = observation.get("human_candidates")
        if not isinstance(candidates, list):
            return False
        return any(
            isinstance(candidate, dict)
            and candidate.get("target_id") == self._active_target_id
            and candidate.get("vision_epoch") == epoch
            and self._candidate_is_fresh(candidate)
            and (
                candidate.get("identity") != "owner"
                or candidate.get("identity_state") != "confirmed_known"
                or candidate.get("tracking_state") != "tracking"
                or candidate.get("track_id") != self._active_track_id
            )
            for candidate in candidates
        )

    def _disarm_for_current_owner(self, owners: list[dict[str, Any]]) -> None:
        self._disarmed = True
        if len(owners) == 1:
            self._disarmed_target_id = owners[0]["target_id"]
            self._disarmed_track_id = owners[0]["track_id"]
        else:
            self._disarmed_target_id = ""
            self._disarmed_track_id = 0

    def _remember_source_key(self, source_key: tuple[str, str]) -> None:
        self._seen_source_keys.add(source_key)
        self._source_key_order.append(source_key)
        # Source observations expire after at most 0.5 s. A bounded recent set
        # covers republished frames without retaining a whole session history.
        while len(self._source_key_order) > 64:
            expired = self._source_key_order.popleft()
            self._seen_source_keys.discard(expired)

    def _source_age_is_fresh(self, value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, Real):
            return False
        age = float(value)
        return math.isfinite(age) and 0.0 <= age <= self.source_freshness_sec

    @staticmethod
    def _candidate_is_fresh(candidate: dict[str, Any]) -> bool:
        age_ms = candidate.get("last_seen_age_ms")
        return (
            not isinstance(age_ms, bool)
            and isinstance(age_ms, Real)
            and math.isfinite(float(age_ms))
            and 0.0 <= float(age_ms) < 500.0
        )

    def _clear_active(self, *, clear_gesture_sides: bool = False) -> None:
        self._active_event_id = ""
        self._active_target_id = ""
        self._active_track_id = 0
        if clear_gesture_sides:
            self._active_gesture_sides.clear()

    def _snapshot(self) -> OwnerRecallGestureEventSnapshot:
        return OwnerRecallGestureEventSnapshot(
            bool(self._active_event_id),
            event_id=self._active_event_id,
            transition="HOLD" if self._active_event_id else "",
        )
