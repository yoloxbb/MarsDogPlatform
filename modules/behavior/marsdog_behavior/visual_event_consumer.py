"""Visual subscription policy and cache updates, independent of ROS construction.

The adapter remains the cache/lock owner. Consumers run after that lock is released.
"""
from __future__ import annotations
import json
import time


def consume_visual_event(self, msg, *, direct_events):
    """Handle /perception/visual_event messages.

    Caches humans, active_target, and tracked_objects as a visual-service
    fallback. STRANGER, FALL, and STOP_GESTURE are forwarded once on their
    appearance edge; the 10 Hz visual state stream may repeat them across
    snapshots.
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

    dispatch_events: list[str] = []
    with self._lock:
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
        raw_candidates = data.get("human_candidates", [])
        self._cached_human_candidates = [
            dict(item)
            for item in raw_candidates
            if isinstance(item, dict)
        ] if isinstance(raw_candidates, list) else []
        snapshot_id = str(data.get("snapshot_id", "")).strip()
        snapshot_sequence = data.get("sequence")
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
        previous_direct_events = getattr(
            self, "_active_direct_visual_events", set()
        )
        if (
            previous_received_at > 0.0
            and received_at - previous_received_at
            > self.VISUAL_CACHE_TIMEOUT_SEC
        ):
            previous_direct_events = set()
        dispatch_events = [
            event_type
            for event_type in event_types
            if event_type in current_direct_events
            and event_type not in previous_direct_events
        ]
        self._active_direct_visual_events = current_direct_events

        if event_types:
            self._logger.debug(
                "visual_event received: events=%s direct_rising=%s"
                % (event_types, dispatch_events)
            )

    # Do not invoke consumers while holding the scene-cache lock.
    if self._on_visual_event:
        for event_type in dispatch_events:
            self._on_visual_event(event_type, data)
