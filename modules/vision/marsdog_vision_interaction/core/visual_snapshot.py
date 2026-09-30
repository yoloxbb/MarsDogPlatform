"""Snapshot assembly and aged query views over existing manager/cache ports.

Depth fusion and object tracking stay with their existing implementations; this
component receives their callbacks and cannot construct models or ROS objects.
"""
from __future__ import annotations
import copy
import math
from typing import Any
from marsdog_vision_interaction.messages.visual_event import normalize_visual_event


def build_visual_snapshot(self, raw: dict[str, Any] | Any, *, finite_positive, fuse_human_depth, now):
    """Build one versioned target snapshot from one manager read.

    The provider's cached observation carries faces, gestures and source
    image metadata.  Identity, target IDs and target freshness come from a
    single :class:`VisualTargetManager` snapshot so an active target and
    its candidate entry cannot describe different tracker generations.
    """
    raw_dict = dict(raw) if isinstance(raw, dict) else {}
    event = normalize_visual_event(raw_dict)
    target_snapshot = self._target_manager.get_snapshot()
    vision_epoch = str(
        target_snapshot.get("vision_epoch", "")
        or getattr(self, "_vision_epoch", "")
    )
    active_value = target_snapshot.get("active_target")
    active = (
        active_value.to_dict()
        if hasattr(active_value, "to_dict") else {}
    )
    active["vision_epoch"] = vision_epoch
    candidates = [
        dict(item)
        for item in target_snapshot.get("human_candidates", [])
        if isinstance(item, dict)
    ]

    raw_active = raw_dict.get("active_target", {})
    if not isinstance(raw_active, dict):
        raw_active = {}
    raw_candidates = {
        str(item.get("target_id", "")): item
        for item in raw_dict.get("human_candidates", [])
        if isinstance(item, dict) and item.get("target_id")
    }
    active_target_id = str(active.get("target_id", ""))
    for candidate in candidates:
        source = raw_candidates.get(str(candidate.get("target_id", "")))
        if source is not None:
            candidate["pose_action"] = str(
                source.get("pose_action", "")
            )
            candidate["pose_action_label"] = str(
                source.get("pose_action_label", "")
            )

    if (
        active_target_id
        and str(raw_active.get("target_id", "")) == active_target_id
        and active.get("tracking_state") == "tracking"
    ):
        active["pose_action"] = str(raw_active.get("pose_action", ""))
        active["pose_action_label"] = str(
            raw_active.get("pose_action_label", "")
        )
    else:
        active["pose_action"] = ""
        active["pose_action_label"] = ""

    observation_stamp = finite_positive(
        event.get("header", {}).get("stamp")
    )
    with self._state_lock:
        camera_stamp = finite_positive(
            getattr(self, "_latest_camera_stamp", 0.0)
        )
        camera_frame_id = str(
            getattr(self, "_latest_camera_frame_id", "camera_link")
            or "camera_link"
        )
    if not raw_dict.get("header") and camera_stamp is not None:
        event["header"] = {
            "stamp": camera_stamp,
            "frame_id": camera_frame_id,
        }
        observation_stamp = camera_stamp
    elif observation_stamp is None:
        event["header"]["stamp"] = now()
        observation_stamp = float(event["header"]["stamp"])
    if not str(event["header"].get("frame_id", "")).strip():
        event["header"]["frame_id"] = camera_frame_id

    fuse_human_depth(
        self,
        candidates,
        observation_stamp=observation_stamp,
    )
    matching_active = next(
        (
            item for item in candidates
            if str(item.get("target_id", "")) == active_target_id
        ),
        None,
    )
    if matching_active is not None:
        for key in (
            "center",
            "body_center",
            "bearing_deg",
            "bearing_valid",
            "bearing_source",
            "range_valid",
            "distance_m",
            "range_source",
            "depth_sync_delta_ms",
            "pose_3d",
        ):
            if key in matching_active:
                active[key] = copy.deepcopy(matching_active[key])

    with self._state_lock:
        sequence = int(getattr(self, "_visual_sequence", 0)) + 1
        self._visual_sequence = sequence
    event["vision_epoch"] = vision_epoch
    event["sequence"] = sequence
    event["snapshot_id"] = f"{vision_epoch}:{sequence}"
    event["active_target"] = active
    event["human_candidates"] = candidates
    return event


def query_targets(self, params: dict[str, Any], *, object_candidates, finite_nonnegative, now):
    """Return a safely re-aged copy of the latest published snapshot."""
    with self._state_lock:
        snapshot = copy.deepcopy(
            getattr(self, "_latest_visual_snapshot", {})
        )
        cached_monotonic = float(
            getattr(self, "_latest_visual_snapshot_monotonic", 0.0)
        )
        object_candidates = (
            object_candidates(
                self,
                now_monotonic=now(),
            )
        )
    if (
        not snapshot
        or int(snapshot.get("sequence", 0) or 0) <= 0
        or not math.isfinite(cached_monotonic)
        or cached_monotonic <= 0.0
    ):
        return {"ok": False, "error": "visual snapshot unavailable"}

    snapshot_age_ms = max(
        0.0, now() - cached_monotonic
    ) * 1000.0
    current_timeout_ms = max(
        1.0,
        float(getattr(self, "_target_current_timeout_sec", 0.35))
        * 1000.0,
    )
    for item in [
        snapshot.get("active_target", {}),
        *snapshot.get("human_candidates", []),
    ]:
        if not isinstance(item, dict):
            continue
        age = finite_nonnegative(
            item.get("last_seen_age_ms")
        )
        if age is None:
            item["tracking_state"] = "lost"
            item["range_valid"] = False
            item["distance_m"] = None
            continue
        age += snapshot_age_ms
        item["last_seen_age_ms"] = round(age, 1)
        if age > current_timeout_ms:
            item["tracking_state"] = "temporarily_lost"
            # Cached range must never survive target loss.
            item["range_valid"] = False
            item["distance_m"] = None
            pose_3d = item.get("pose_3d")
            if isinstance(pose_3d, dict):
                pose_3d.update({
                    "valid": False,
                    "x": None,
                    "y": None,
                    "z": None,
                })

    requested_types = params.get("target_types", ["human"])
    if isinstance(requested_types, str):
        requested_types = [requested_types]
    allowed_types = {
        str(value).strip().lower()
        for value in requested_types
        if str(value).strip()
    } if isinstance(requested_types, list) else {"human"}
    minimum_confidence = finite_nonnegative(
        params.get("min_confidence", 0.0)
    )
    minimum_confidence = min(1.0, minimum_confidence or 0.0)
    maximum_age_ms = finite_nonnegative(
        params.get("max_age_ms")
    )
    human_targets: list[dict[str, Any]] = []
    if "human" in allowed_types or "person" in allowed_types:
        for item in snapshot.get("human_candidates", []):
            if not isinstance(item, dict):
                continue
            confidence = finite_nonnegative(
                item.get(
                    "detection_confidence",
                    item.get("confidence", 0.0),
                )
            ) or 0.0
            age = finite_nonnegative(
                item.get("last_seen_age_ms")
            )
            if confidence < minimum_confidence:
                continue
            if maximum_age_ms is not None and (
                age is None or age > maximum_age_ms
            ):
                continue
            human_targets.append(copy.deepcopy(item))

    nonhuman_targets: list[dict[str, Any]] = []
    for item in object_candidates:
        target_type = str(item.get("target_type", "object"))
        if target_type not in allowed_types:
            continue
        confidence = finite_nonnegative(
            item.get(
                "detection_confidence",
                item.get("confidence", 0.0),
            )
        ) or 0.0
        age = finite_nonnegative(
            item.get("last_seen_age_ms")
        )
        if confidence < minimum_confidence:
            continue
        if maximum_age_ms is not None and (
            age is None or age > maximum_age_ms
        ):
            continue
        nonhuman_targets.append(copy.deepcopy(item))
    targets = human_targets + nonhuman_targets

    return {
        "ok": True,
        "schema_version": int(snapshot.get("schema_version", 1)),
        "header": copy.deepcopy(snapshot.get("header", {})),
        "vision_epoch": str(snapshot.get("vision_epoch", "")),
        "sequence": int(snapshot.get("sequence", 0)),
        "snapshot_id": str(snapshot.get("snapshot_id", "")),
        "snapshot_age_ms": round(snapshot_age_ms, 1),
        "targets": targets,
        "human_candidates": copy.deepcopy(human_targets),
        "animal_candidates": [
            copy.deepcopy(item) for item in nonhuman_targets
            if item.get("target_type") == "animal"
        ],
        "object_candidates": [
            copy.deepcopy(item) for item in nonhuman_targets
            if item.get("target_type") == "object"
        ],
        "active_target": copy.deepcopy(
            snapshot.get("active_target", {})
        ),
    }
