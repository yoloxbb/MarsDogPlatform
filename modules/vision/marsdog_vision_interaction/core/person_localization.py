"""Pure contracts for one-shot SLAM person localization.

The ROS node owns transport and scheduling.  This module deliberately keeps
the wire conversion and safety checks free of ROS imports so they can be used
by unit tests and by deployments where the optional SLAM interface is absent.
"""

from __future__ import annotations

import math
from typing import Any


LOCALIZATION_INTERFACE_UNAVAILABLE = "localization_interface_unavailable"
LOCALIZATION_SERVER_UNAVAILABLE = "localization_server_unavailable"
LOCALIZATION_TIMEOUT = "localization_timeout"
LOCALIZATION_CLIENT_ERROR = "localization_client_error"
LOCALIZATION_INVALID_TARGET = "localization_invalid_target"
LOCALIZATION_INVALID_SOURCE = "localization_invalid_source"
LOCALIZATION_UNSUPPORTED_GEOMETRY = "localization_unsupported_geometry"
LOCALIZATION_INVALID_BBOX = "localization_invalid_bbox"
LOCALIZATION_INVALID_REQUEST = "localization_invalid_request"
LOCALIZATION_INVALID_RESPONSE = "localization_invalid_response"
LOCALIZATION_SERVER_ERROR = "localization_server_error"


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        if float(value) != float(result):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return result


def stamp_to_dict(stamp: Any) -> dict[str, int] | None:
    """Convert a ROS ``builtin_interfaces/Time`` or mapping exactly."""
    if isinstance(stamp, dict):
        sec_value = stamp.get("sec")
        nanosec_value = stamp.get("nanosec")
    else:
        sec_value = getattr(stamp, "sec", None)
        nanosec_value = getattr(stamp, "nanosec", None)
    sec = _integer(sec_value)
    nanosec = _integer(nanosec_value)
    if sec is None or nanosec is None or nanosec < 0 or nanosec >= 1_000_000_000:
        return None
    return {"sec": sec, "nanosec": nanosec}


def header_to_dict(header: Any) -> dict[str, Any] | None:
    """Convert a ROS Header or mapping to JSON-safe primitive fields."""
    if isinstance(header, dict):
        stamp_value = header.get("stamp")
        frame_id = header.get("frame_id", "")
    else:
        stamp_value = getattr(header, "stamp", None)
        frame_id = getattr(header, "frame_id", "")
    stamp = stamp_to_dict(stamp_value)
    if stamp is None:
        return None
    return {"stamp": stamp, "frame_id": str(frame_id or "")}


def validate_source_metadata(
    source: Any,
    *,
    now_monotonic: float | None = None,
    max_age_sec: float | None = None,
) -> str | None:
    """Return a local error code when source metadata cannot be used safely."""
    if not isinstance(source, dict):
        return LOCALIZATION_INVALID_SOURCE
    header = header_to_dict(source.get("header"))
    if header is None:
        return LOCALIZATION_INVALID_SOURCE
    stamp = header["stamp"]
    if stamp["sec"] == 0 and stamp["nanosec"] == 0:
        return LOCALIZATION_INVALID_SOURCE
    if not header["frame_id"].strip():
        return LOCALIZATION_INVALID_SOURCE
    try:
        width = int(source.get("source_width", 0))
        height = int(source.get("source_height", 0))
    except (TypeError, ValueError, OverflowError):
        return LOCALIZATION_INVALID_SOURCE
    if width <= 0 or height <= 0:
        return LOCALIZATION_INVALID_SOURCE
    if bool(source.get("view_split", False)):
        return LOCALIZATION_UNSUPPORTED_GEOMETRY
    if not _is_finite_number(source.get("received_monotonic")):
        return LOCALIZATION_INVALID_SOURCE
    received = float(source["received_monotonic"])
    if received <= 0.0:
        return LOCALIZATION_INVALID_SOURCE
    if max_age_sec is not None:
        try:
            max_age = float(max_age_sec)
        except (TypeError, ValueError):
            return LOCALIZATION_INVALID_SOURCE
        if not math.isfinite(max_age) or max_age < 0.0:
            return LOCALIZATION_INVALID_SOURCE
        current = time_monotonic() if now_monotonic is None else float(now_monotonic)
        if not math.isfinite(current) or current < received or current - received > max_age:
            return LOCALIZATION_INVALID_SOURCE
    return None


def time_monotonic() -> float:
    # Kept as a tiny seam for deterministic tests without importing time in
    # callers that only need the pure geometry helpers.
    import time

    return time.monotonic()


def normalized_bbox_to_roi(
    bbox: Any,
    image_width: int,
    image_height: int,
    *,
    view_split: bool = False,
) -> dict[str, Any] | None:
    """Convert a normalized source-view bbox to a clipped pixel ROI.

    Left/top use floor and right/bottom use ceil so a detection is never
    shortened by integer conversion.  The returned mapping matches
    ``sensor_msgs/RegionOfInterest`` fields.
    """
    if view_split:
        return None
    try:
        width = int(image_width)
        height = int(image_height)
    except (TypeError, ValueError, OverflowError):
        return None
    if width <= 0 or height <= 0:
        return None
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        x, y, box_width, box_height = (float(value) for value in bbox[:4])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x, y, box_width, box_height)):
        return None
    if box_width <= 0.0 or box_height <= 0.0:
        return None
    right = x + box_width
    bottom = y + box_height
    if not math.isfinite(right) or not math.isfinite(bottom) or right <= x or bottom <= y:
        return None
    x1 = max(0, min(width, math.floor(x * width)))
    y1 = max(0, min(height, math.floor(y * height)))
    # Keep the conservative service-boundary rule literal: any fractional
    # right/bottom extent expands to the next pixel so the ROI never cuts the
    # detector box short.
    x2 = max(0, min(width, math.ceil(right * width)))
    y2 = max(0, min(height, math.ceil(bottom * height)))
    if x2 <= x1 or y2 <= y1:
        return None
    return {
        "x_offset": int(x1),
        "y_offset": int(y1),
        "width": int(x2 - x1),
        "height": int(y2 - y1),
        "do_rectify": False,
    }


def _header_message_to_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return header_to_dict(value)
    return header_to_dict(value)


def _point_stamped_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    header = _header_message_to_dict(getattr(value, "header", None))
    point_value = getattr(value, "point", None)
    if header is None or point_value is None:
        return None
    coordinates: dict[str, float] = {}
    for key in ("x", "y", "z"):
        coordinate = getattr(point_value, key, None)
        if not _is_finite_number(coordinate):
            return None
        coordinates[key] = float(coordinate)
    return {"header": header, "point": coordinates}


def _pose_stamped_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    header = _header_message_to_dict(getattr(value, "header", None))
    pose = getattr(value, "pose", None)
    position = getattr(pose, "position", None) if pose is not None else None
    orientation = getattr(pose, "orientation", None) if pose is not None else None
    if header is None or position is None or orientation is None:
        return None
    positions: dict[str, float] = {}
    orientations: dict[str, float] = {}
    for key in ("x", "y", "z"):
        coordinate = getattr(position, key, None)
        if not _is_finite_number(coordinate):
            return None
        positions[key] = float(coordinate)
    for key in ("x", "y", "z", "w"):
        coordinate = getattr(orientation, key, None)
        if not _is_finite_number(coordinate):
            return None
        orientations[key] = float(coordinate)
    return {
        "header": header,
        "pose": {"position": positions, "orientation": orientations},
    }


def _quality_value(response: Any, name: str) -> float | None:
    value = getattr(response, name, None)
    if not _is_finite_number(value):
        return None
    return float(value)


def _status_value(response: Any) -> int:
    try:
        return int(getattr(response, "status", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def serialize_localization_response(
    response: Any,
    *,
    target_id: str,
    source_header: dict[str, Any],
) -> dict[str, Any]:
    """Serialize one SLAM response and reject non-finite success payloads."""
    success = bool(getattr(response, "success", False))
    result: dict[str, Any] = {
        "ok": success,
        "target_id": str(target_id),
        "source_header": source_header,
        "navigation_required": bool(
            getattr(response, "navigation_required", False)
        ),
        "status": _status_value(response),
        "message": str(getattr(response, "message", "") or ""),
    }
    for name in ("valid_depth_ratio", "mean_depth", "depth_stddev"):
        value = _quality_value(response, name)
        if value is not None:
            result[name] = value
        elif success:
            return {
                "ok": False,
                "target_id": str(target_id),
                "source_header": source_header,
                "navigation_required": False,
                "error_code": LOCALIZATION_INVALID_RESPONSE,
                "error": f"non-finite response field: {name}",
                "status": result["status"],
                "message": result["message"],
            }
    if not success:
        # A failed request must never leave an upstream caller with a
        # navigable-looking flag, even if the server filled a stale/default
        # response field.
        result["navigation_required"] = False
        result["error_code"] = LOCALIZATION_SERVER_ERROR
        result["error"] = result["message"] or "SLAM localization failed"
        return result

    person_point = _point_stamped_to_dict(getattr(response, "person_point", None))
    navigation_goal = _pose_stamped_to_dict(
        getattr(response, "navigation_goal", None)
    )
    if person_point is None:
        return {
            "ok": False,
            "target_id": str(target_id),
            "source_header": source_header,
            "navigation_required": False,
            "error_code": LOCALIZATION_INVALID_RESPONSE,
            "error": "successful response has invalid person_point",
            "status": result["status"],
            "message": result["message"],
        }
    if result["navigation_required"] and navigation_goal is None:
        return {
            "ok": False,
            "target_id": str(target_id),
            "source_header": source_header,
            "navigation_required": False,
            "error_code": LOCALIZATION_INVALID_RESPONSE,
            "error": "navigation is required but navigation_goal is invalid",
            "status": result["status"],
            "message": result["message"],
        }
    result["person_point"] = person_point
    if navigation_goal is not None:
        result["navigation_goal"] = navigation_goal
    return result


def localization_error(
    error_code: str,
    error: str,
    *,
    target_id: str = "",
    source_header: dict[str, Any] | None = None,
    status: int | None = None,
    message: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "target_id": str(target_id),
        "error_code": str(error_code),
        "error": str(error),
        "navigation_required": False,
    }
    if source_header is not None:
        result["source_header"] = source_header
    if status is not None:
        result["status"] = int(status)
    if message:
        result["message"] = str(message)
    return result
