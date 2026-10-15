"""Visual subscription policy and cache updates, independent of ROS construction.

The adapter remains the cache/lock owner. Consumers run after that lock is released.
"""
from __future__ import annotations
import json
import time

from .visual_presence_contract import (
    OWNER_PRESENCE_EVENT,
    OWNER_RECALL_GESTURE_EVENT,
    STRANGER_PRESENCE_EVENT,
    VISUAL_POSTURE_ACTIONS,
    VISUAL_POSTURE_EVENT_NAMES,
    VISUAL_OBJECT_EVENT_NAMES,
    VISUAL_PRESENCE_EVENT_NAMES,
)


def _presence_instance_id(self, event_name: str) -> str:
    return self._cached_visual_event_instances.get(event_name, "")


def _consumed_presence_instance_id(self, event_name: str) -> str:
    if event_name == OWNER_PRESENCE_EVENT:
        return self._consumed_owner_presence_instance_id
    return getattr(
        self, "_consumed_visual_presence_instance_ids", {}
    ).get(event_name, "")


def _pending_presence_instance_id(self, event_name: str) -> str:
    if event_name == OWNER_PRESENCE_EVENT:
        return self._pending_owner_presence_instance_id
    return getattr(
        self, "_pending_visual_presence_instance_ids", {}
    ).get(event_name, "")


def _set_pending_presence_instance_id(
    self,
    event_name: str,
    event_id: str,
) -> None:
    if event_name == OWNER_PRESENCE_EVENT:
        self._pending_owner_presence_instance_id = event_id
    else:
        values = getattr(self, "_pending_visual_presence_instance_ids", None)
        if not isinstance(values, dict):
            values = {}
            self._pending_visual_presence_instance_ids = values
        if event_id:
            values[event_name] = event_id
        else:
            values.pop(event_name, None)


def _set_consumed_presence_instance_id(
    self,
    event_name: str,
    event_id: str,
) -> None:
    if event_name == OWNER_PRESENCE_EVENT:
        self._consumed_owner_presence_instance_id = event_id
    elif event_id:
        values = getattr(self, "_consumed_visual_presence_instance_ids", None)
        if not isinstance(values, dict):
            values = {}
            self._consumed_visual_presence_instance_ids = values
        values[event_name] = event_id


def _advance_owner_posture_snapshot(self, data) -> None:
    """Track valid producer order for the posture event without changing presence."""
    epoch = data.get("vision_epoch")
    sequence = data.get("sequence")
    snapshot_id = data.get("snapshot_id")
    source_id = data.get("source_observation_id")
    if (
        data.get("observation_status") != "valid"
        or not isinstance(epoch, str) or not epoch.strip()
        or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0
        or not isinstance(snapshot_id, str) or not snapshot_id.strip()
        or not isinstance(source_id, str) or not source_id.strip()
    ):
        return
    epoch = epoch.strip()
    retired = getattr(self, "_owner_posture_retired_epochs", set())
    if epoch in retired:
        return
    current_epoch = getattr(self, "_owner_posture_snapshot_epoch", "")
    if epoch != current_epoch:
        if current_epoch:
            retired.add(current_epoch)
        self._owner_posture_retired_epochs = retired
    elif sequence <= getattr(self, "_owner_posture_snapshot_sequence", 0):
        return
    self._owner_posture_snapshot_epoch = epoch
    self._owner_posture_snapshot_sequence = sequence
    self._owner_posture_snapshot_id = snapshot_id.strip()


def _advance_owner_recall_snapshot(self, data) -> None:
    """Track accepted source order for owner-recall candidate provenance."""
    epoch = data.get("vision_epoch")
    sequence = data.get("sequence")
    snapshot_id = data.get("snapshot_id")
    source_id = data.get("source_observation_id")
    if (
        data.get("observation_status") != "valid"
        or not isinstance(epoch, str) or not epoch.strip()
        or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0
        or not isinstance(snapshot_id, str) or not snapshot_id.strip()
        or not isinstance(source_id, str) or not source_id.strip()
    ):
        return
    epoch = epoch.strip()
    retired = getattr(self, "_owner_recall_retired_epochs", set())
    if epoch in retired:
        return
    current_epoch = getattr(self, "_owner_recall_snapshot_epoch", "")
    if epoch != current_epoch:
        if current_epoch:
            retired.add(current_epoch)
        self._owner_recall_retired_epochs = retired
    elif sequence <= getattr(self, "_owner_recall_snapshot_sequence", 0):
        return
    self._owner_recall_snapshot_epoch = epoch
    self._owner_recall_snapshot_sequence = sequence
    self._owner_recall_snapshot_id = snapshot_id.strip()


def _advance_visual_object_snapshot(self, data) -> None:
    """Remember the newest ordered v1 snapshot for object-event dispatch."""
    epoch = data.get("vision_epoch")
    sequence = data.get("sequence")
    snapshot_id = data.get("snapshot_id")
    if (
        not isinstance(epoch, str) or not epoch.strip()
        or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0
        or not isinstance(snapshot_id, str) or not snapshot_id.strip()
    ):
        return
    epoch = epoch.strip()
    retired = getattr(self, "_visual_object_retired_epochs", set())
    if epoch in retired:
        return
    current_epoch = getattr(self, "_visual_object_snapshot_epoch", "")
    if epoch != current_epoch:
        if current_epoch:
            retired.add(current_epoch)
        self._visual_object_retired_epochs = retired
    elif sequence <= getattr(self, "_visual_object_snapshot_sequence", 0):
        return
    self._visual_object_snapshot_epoch = epoch
    self._visual_object_snapshot_sequence = sequence
    self._visual_object_snapshot_id = snapshot_id.strip()


def visual_object_snapshot_is_current(self) -> bool:
    """Reject delayed or retired packets before dispatching object candidates."""
    epoch = getattr(self, "_visual_object_snapshot_epoch", "")
    return bool(
        epoch
        and self._cached_vision_epoch == epoch
        and self._cached_visual_sequence
        == getattr(self, "_visual_object_snapshot_sequence", None)
        and self._cached_visual_snapshot_id
        == getattr(self, "_visual_object_snapshot_id", "")
    )


def owner_recall_snapshot_is_current(self) -> bool:
    """Reject delayed or retired snapshots for recall candidates."""
    epoch = getattr(self, "_owner_recall_snapshot_epoch", "")
    return bool(
        epoch
        and self._cached_observation_status == "valid"
        and self._cached_vision_epoch == epoch
        and self._cached_visual_sequence
        == getattr(self, "_owner_recall_snapshot_sequence", None)
        and self._cached_visual_snapshot_id
        == getattr(self, "_owner_recall_snapshot_id", "")
    )


def owner_posture_snapshot_is_current(self) -> bool:
    """Reject cached posture context overwritten by delayed or retired packets."""
    epoch = getattr(self, "_owner_posture_snapshot_epoch", "")
    return bool(
        epoch
        and self._cached_vision_epoch == epoch
        and self._cached_visual_sequence == getattr(self, "_owner_posture_snapshot_sequence", None)
        and self._cached_visual_snapshot_id == getattr(self, "_owner_posture_snapshot_id", "")
    )


def consume_visual_event(self, msg, *, direct_events):
    """Handle /perception/visual_event messages.

    Caches visual targets and tracked_objects as a visual-service fallback.
    FALL and STOP_GESTURE are forwarded on their appearance edge.
    Presence events are active states with instance IDs: retry while active
    until a candidate is accepted, then retain each dedup ID across cache
    timeouts and repeated HOLD snapshots.
    """
    try:
        data = json.loads(msg.data if hasattr(msg, 'data') else str(msg))
    except (json.JSONDecodeError, TypeError):
        return
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
    ):
        self._logger.debug(
            "visual_event ignored: expected object with schema_version=1"
        )
        return
    events = data.get("events")
    if (
        not isinstance(events, list)
        or any(not isinstance(item, str) for item in events)
    ):
        self._logger.debug(
            "visual_event ignored: events must be a string array"
        )
        return

    dispatch_events: list[tuple[str, str]] = []
    with self._lock:
        _advance_owner_posture_snapshot(self, data)
        _advance_owner_recall_snapshot(self, data)
        _advance_visual_object_snapshot(self, data)
        received_at = time.monotonic()
        previous_received_at = self._visual_cache_updated_at
        self._visual_cache_updated_at = received_at
        self._cached_humans = [
            dict(item)
            for item in data.get("humans", [])
            if isinstance(item, dict)
        ]
        self._cached_vision_epoch = str(data.get("vision_epoch", "")).strip()
        self._cached_visual_header = (
            dict(data.get("header", {}))
            if isinstance(data.get("header"), dict)
            else {}
        )
        self._cached_visual_snapshot_id = str(data.get("snapshot_id", "")).strip()
        sequence = data.get("sequence")
        self._cached_visual_sequence = (
            sequence
            if isinstance(sequence, int) and not isinstance(sequence, bool)
            else None
        )
        raw_source_observation_id = data.get("source_observation_id")
        self._cached_source_observation_id = (
            raw_source_observation_id.strip()
            if isinstance(raw_source_observation_id, str)
            else ""
        )
        self._cached_visual_events = {
            item.strip() for item in events if item.strip()
        }
        status = data.get("observation_status")
        self._cached_observation_status = (
            status if status in {"valid", "invalid"} else ""
        )
        raw_event_instances = data.get("event_instances")
        cached_presence_ids = {}
        if isinstance(raw_event_instances, dict):
            for event_name in (
                VISUAL_PRESENCE_EVENT_NAMES | VISUAL_OBJECT_EVENT_NAMES
            ):
                instance = raw_event_instances.get(event_name)
                raw_event_id = (
                    instance.get("event_id")
                    if isinstance(instance, dict)
                    else None
                )
                if isinstance(raw_event_id, str) and raw_event_id.strip():
                    cached_presence_ids[event_name] = raw_event_id.strip()
        self._cached_visual_event_instances = cached_presence_ids
        raw_candidates = data.get("human_candidates", [])
        self._cached_human_candidates = [
            dict(item)
            for item in raw_candidates
            if isinstance(item, dict)
        ] if isinstance(raw_candidates, list) else []
        snapshot_id = self._cached_visual_snapshot_id
        snapshot_sequence = self._cached_visual_sequence
        for candidate in self._cached_human_candidates:
            if self._cached_vision_epoch:
                candidate.setdefault(
                    "vision_epoch", self._cached_vision_epoch
                )
            if snapshot_id:
                candidate.setdefault("snapshot_id", snapshot_id)
            if isinstance(snapshot_sequence, int) and not isinstance(
                snapshot_sequence, bool
            ):
                candidate.setdefault(
                    "snapshot_sequence", snapshot_sequence
                )
            candidate.setdefault(
                "source_stamp", self._cached_visual_header.get("stamp")
            )
            candidate.setdefault(
                "frame_id", self._cached_visual_header.get("frame_id")
            )
            if self._cached_source_observation_id:
                candidate.setdefault(
                    "source_observation_id",
                    self._cached_source_observation_id,
                )

        # Compatibility with a visual-event producer that has not yet
        # gained ``human_candidates``.  Only construct a strict target
        # reference when the producer already supplies an epoch and a
        # positive track id; identity is never used as the target id.
        if not self._cached_human_candidates:
            active_candidate = data.get("active_target")
            if isinstance(active_candidate, dict):
                try:
                    active_track_id = int(active_candidate.get("track_id", 0))
                except (TypeError, ValueError):
                    active_track_id = 0
                if self._cached_vision_epoch and active_track_id > 0:
                    candidate = dict(active_candidate)
                    candidate.setdefault("target_type", "human")
                    candidate.setdefault("vision_epoch", self._cached_vision_epoch)
                    candidate.setdefault(
                        "target_id",
                        "%s:human:%d"
                        % (self._cached_vision_epoch, active_track_id),
                    )
                    candidate.setdefault(
                        "detection_confidence",
                        candidate.get("confidence", 0.0),
                    )
                    self._cached_human_candidates = [candidate]
        self._cached_objects = [
            dict(item)
            for item in data.get("tracked_objects", [])
            if isinstance(item, dict)
        ]

        # ── Cache active_target for check_person / interaction_resolver ──
        target = data.get("active_target") or {}
        if target:
            identity = target.get("identity", "unknown")
            is_registered = target.get("is_registered", False)
            is_speaking = target.get("is_speaking", False)
            target_type = str(
                target.get("target_type", target.get("type", ""))
            ).lower()
            non_person_target = target_type in (
                "animal", "dog", "cat", "object", "toy",
            )
            tracking_state = str(
                target.get("tracking_state", "tracking")
            ).lower()
            try:
                target_age_ms = float(
                    target.get("last_seen_age_ms", 0.0)
                )
            except (TypeError, ValueError):
                target_age_ms = self.VISUAL_TARGET_MAX_AGE_MS + 1.0
            target_is_current = (
                tracking_state == "tracking"
                and 0.0 <= target_age_ms <= self.VISUAL_TARGET_MAX_AGE_MS
            )
            self._person_present = (
                bool(self._cached_humans)
                or (
                    target_is_current
                    and
                    not non_person_target
                    and bool(
                        is_registered
                        or is_speaking
                        or identity not in ("", "unknown")
                        or target_type in (
                            "human", "person", "owner", "master",
                        )
                    )
                )
            )
            self._active_identity = identity if identity != "unknown" else "unknown"
        else:
            # An explicit empty active_target means the previously tracked
            # person has left the frame; do not retain stale interaction
            # context indefinitely.
            self._person_present = bool(self._cached_humans)
            self._active_identity = "unknown"

        event_types = []
        for item in events:
            event_type = item.strip()
            if event_type and event_type not in event_types:
                event_types.append(event_type)

        current_direct_events = set(event_types) & direct_events
        if (
            OWNER_PRESENCE_EVENT in current_direct_events
            and not _presence_instance_id(self, OWNER_PRESENCE_EVENT)
        ):
            # EVT_VISION_MASTER also carries the retained immediate
            # non-owner face fact. Only the state-qualified owner cycle is a
            # Behavior direct event; a bare family/known-face MASTER stays
            # available to Emotion without appearing as an owner edge here.
            current_direct_events.discard(OWNER_PRESENCE_EVENT)
        if (
            STRANGER_PRESENCE_EVENT in current_direct_events
            and not _presence_instance_id(self, STRANGER_PRESENCE_EVENT)
        ):
            # Historical producers can send an immediate stranger face fact.
            # Only an instance-bound presence cycle is a Behavior event;
            # leave an unqualified fact out of the active-edge cache.
            current_direct_events.discard(STRANGER_PRESENCE_EVENT)
        previous_direct_events = getattr(
            self, "_active_direct_visual_events", set()
        )
        if (
            previous_received_at > 0.0
            and received_at - previous_received_at
            > self.VISUAL_CACHE_TIMEOUT_SEC
        ):
            previous_direct_events = set()
        for event_type in event_types:
            if event_type not in current_direct_events:
                continue
            if event_type in VISUAL_PRESENCE_EVENT_NAMES | VISUAL_OBJECT_EVENT_NAMES:
                event_id = _presence_instance_id(self, event_type)
                consumed_id = _consumed_presence_instance_id(
                    self, event_type
                )
                pending_id = _pending_presence_instance_id(
                    self, event_type
                )
                if (
                    self._on_visual_event is None
                    or (event_type in VISUAL_PRESENCE_EVENT_NAMES
                        and self._cached_observation_status != "valid")
                    or not event_id
                    or event_id in {consumed_id, pending_id}
                ):
                    continue
                if (
                    event_type in VISUAL_OBJECT_EVENT_NAMES
                    and not visual_object_snapshot_is_current(self)
                ):
                    continue
                if (
                    event_type in VISUAL_POSTURE_EVENT_NAMES
                    and not owner_posture_snapshot_is_current(self)
                ):
                    continue
                if (
                    event_type == OWNER_RECALL_GESTURE_EVENT
                    and not owner_recall_snapshot_is_current(self)
                ):
                    continue
                if event_type in VISUAL_POSTURE_EVENT_NAMES and not any(
                    candidate.get("identity") == "owner"
                    and candidate.get("identity_state") == "confirmed_known"
                    and candidate.get("tracking_state") == "tracking"
                    and candidate.get("vision_epoch") == self._cached_vision_epoch
                    and isinstance(candidate.get("pose_action"), str)
                    and candidate.get("pose_action") in VISUAL_POSTURE_ACTIONS
                    for candidate in self._cached_human_candidates
                ):
                    continue
                _set_pending_presence_instance_id(self, event_type, event_id)
                dispatch_events.append((event_type, event_id))
                continue
            if event_type not in previous_direct_events:
                dispatch_events.append((event_type, ""))
        self._active_direct_visual_events = current_direct_events

        if event_types:
            self._logger.debug(
                "visual_event received: events=%s direct_rising=%s"
                % (event_types, [event for event, _ in dispatch_events])
            )

    # Do not invoke consumers while holding the scene-cache lock.
    if self._on_visual_event:
        for event_type, event_id in dispatch_events:
            accepted = False
            try:
                result = self._on_visual_event(event_type, data)
                accepted = result is True
            finally:
                if event_id:
                    with self._lock:
                        if (
                            _pending_presence_instance_id(self, event_type)
                            == event_id
                        ):
                            _set_pending_presence_instance_id(self, event_type, "")
                            if accepted:
                                _set_consumed_presence_instance_id(
                                    self, event_type, event_id
                                )
