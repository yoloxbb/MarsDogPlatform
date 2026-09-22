"""Rendering helpers for the live vision/control diagnostic view."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from marsdog_vision_interaction.providers.pose_backends.contract import normalize_keypoint_format


_POSE_CONNECTIONS = (
    (0, 7), (0, 8), (7, 11), (8, 12),
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31),
    (24, 26), (26, 28), (28, 30), (30, 32),
)

_COCO_POSE_CONNECTIONS = (
    (0, 1), (0, 2), (1, 3), (2, 4),
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
)

_HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)

_MAX_OBJECT_OVERLAYS = 30

# OpenCV colors are BGR. Keep these aligned with the dashboard legend.
_FACE_UNKNOWN_COLOR = (119, 101, 255)  # RGB #FF6577
_FACE_CANDIDATE_COLOR = (87, 200, 255)  # RGB #FFC857
_FACE_CONFIRMED_COLOR = (143, 229, 62)  # RGB #3EE58F

# OSD drawing sizes are defined against the normal 640x480 camera view.  The
# viewer may crop a side-by-side input to 320x240 and then resize it again for
# the web stream, so fixed OpenCV pixel sizes become disproportionately large
# on small output frames.  Keep a small lower bound for legibility and cap the
# upper bound so a high-resolution stream does not grow without limit.
_OSD_REFERENCE_WIDTH = 640.0
_OSD_REFERENCE_HEIGHT = 480.0
_OSD_MIN_SCALE = 0.55
_OSD_MAX_SCALE = 2.0


def _osd_scale(width: int, height: int) -> float:
    """Return a resolution-aware OSD scale for the final output frame."""
    if width <= 0 or height <= 0:
        return 1.0
    resolution_scale = min(
        float(width) / _OSD_REFERENCE_WIDTH,
        float(height) / _OSD_REFERENCE_HEIGHT,
    )
    return min(
        _OSD_MAX_SCALE,
        max(_OSD_MIN_SCALE, resolution_scale),
    )


def _scaled_pixels(value: float, scale: float, minimum: int = 1) -> int:
    """Scale a pixel dimension while keeping it visible."""
    return max(minimum, int(round(float(value) * scale)))


def _face_overlay_color(face: dict[str, Any]) -> tuple[int, int, int]:
    """Return the identity-state color for one face overlay."""
    identity_state = str(face.get("identity_state", "unverified"))
    if identity_state == "confirmed_known":
        return _FACE_CONFIRMED_COLOR
    if identity_state == "candidate_known":
        return _FACE_CANDIDATE_COLOR
    return _FACE_UNKNOWN_COLOR


def _pixel_box(
    item: dict[str, Any], width: int, height: int
) -> tuple[int, int, int, int]:
    x1 = int(float(item.get("x", 0.0)) * width)
    y1 = int(float(item.get("y", 0.0)) * height)
    x2 = int(
        (float(item.get("x", 0.0)) + float(item.get("w", 0.0))) * width
    )
    y2 = int(
        (float(item.get("y", 0.0)) + float(item.get("h", 0.0))) * height
    )
    return (
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(0, min(width - 1, x2)),
        max(0, min(height - 1, y2)),
    )


def _draw_dashed_line(
    frame: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
    thickness: int,
    dash_length: int,
) -> None:
    """Draw a line made of short painted segments with visible gaps."""
    x1, y1 = start
    x2, y2 = end
    length = max(abs(x2 - x1), abs(y2 - y1))
    if length <= 0:
        return
    period = max(2, dash_length * 2)
    for offset in range(0, length, period):
        segment_end = min(length, offset + dash_length)
        start_ratio = offset / float(length)
        end_ratio = segment_end / float(length)
        cv2.line(
            frame,
            (
                int(round(x1 + (x2 - x1) * start_ratio)),
                int(round(y1 + (y2 - y1) * start_ratio)),
            ),
            (
                int(round(x1 + (x2 - x1) * end_ratio)),
                int(round(y1 + (y2 - y1) * end_ratio)),
            ),
            color,
            thickness,
            cv2.LINE_AA,
        )


def _draw_overlay_box(
    frame: np.ndarray,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    thickness: int,
    *,
    dashed: bool = False,
    scale: float = 1.0,
) -> None:
    """Draw either a solid or dashed normalized-detection rectangle."""
    x1, y1, x2, y2 = box
    if not dashed:
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        return
    dash_length = _scaled_pixels(7, scale, minimum=3)
    _draw_dashed_line(frame, (x1, y1), (x2, y1), color, thickness, dash_length)
    _draw_dashed_line(frame, (x2, y1), (x2, y2), color, thickness, dash_length)
    _draw_dashed_line(frame, (x2, y2), (x1, y2), color, thickness, dash_length)
    _draw_dashed_line(frame, (x1, y2), (x1, y1), color, thickness, dash_length)


def _overlay_items(
    event: dict[str, Any],
    debug_key: str,
    fallback_key: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Select an optional debug array and report whether debug mode is active."""
    if isinstance(event.get(debug_key), list):
        return [item for item in event[debug_key] if isinstance(item, dict)], True
    values = event.get(fallback_key, [])
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else [], False


def _text(
    frame: np.ndarray,
    value: str,
    x: int,
    y: int,
    color: tuple[int, int, int] = (255, 255, 255),
    *,
    scale: float = 1.0,
) -> None:
    # Long diagnostic strings should shrink to the available width instead of
    # being clipped across the right edge of a small web frame.
    base_font_scale = max(0.1, 0.52 * scale)
    text_size, _ = cv2.getTextSize(
        value,
        cv2.FONT_HERSHEY_SIMPLEX,
        base_font_scale,
        max(1, _scaled_pixels(1, scale)),
    )
    available_width = max(1, frame.shape[1] - max(0, x) - 4)
    font_scale = base_font_scale
    if text_size[0] > available_width:
        font_scale = max(
            0.1,
            base_font_scale * available_width / float(text_size[0]),
        )
    text_scale = font_scale / 0.52
    outline_thickness = _scaled_pixels(3, text_scale)
    text_thickness = _scaled_pixels(1, text_scale)
    cv2.putText(
        frame, value, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
        font_scale, (0, 0, 0), outline_thickness, cv2.LINE_AA,
    )
    cv2.putText(
        frame, value, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
        font_scale, color, text_thickness, cv2.LINE_AA,
    )


def _draw_landmarks(
    frame: np.ndarray,
    landmarks: Any,
    connections: tuple[tuple[int, int], ...],
    color: tuple[int, int, int],
    *,
    min_confidence: float = 0.2,
    scale: float = 1.0,
) -> dict[int, tuple[int, int]]:
    """Draw a normalized landmark graph and return its visible pixel points."""
    if not isinstance(landmarks, list):
        return {}
    height, width = frame.shape[:2]
    points: dict[int, tuple[int, int]] = {}
    for fallback_id, landmark in enumerate(landmarks):
        if not isinstance(landmark, dict):
            continue
        try:
            confidence = float(landmark.get("confidence", 1.0))
            if confidence < min_confidence:
                continue
            point_id = int(landmark.get("id", fallback_id))
            x = int(float(landmark.get("x", 0.0)) * width)
            y = int(float(landmark.get("y", 0.0)) * height)
        except (TypeError, ValueError):
            continue
        if 0 <= x < width and 0 <= y < height:
            points[point_id] = (x, y)

    line_thickness = _scaled_pixels(2, scale)
    outer_radius = _scaled_pixels(3, scale)
    inner_radius = _scaled_pixels(2, scale)
    for first, second in connections:
        if first in points and second in points:
            cv2.line(
                frame,
                points[first],
                points[second],
                color,
                line_thickness,
                cv2.LINE_AA,
            )
    for point in points.values():
        cv2.circle(
            frame, point, outer_radius, (20, 20, 20), -1, cv2.LINE_AA
        )
        cv2.circle(frame, point, inner_radius, color, -1, cv2.LINE_AA)
    return points


def draw_visual_debug(
    frame: np.ndarray,
    event: dict[str, Any] | None,
    *,
    control: dict[str, Any] | None = None,
    cmd_vel: tuple[float, float] | None = None,
    enabled: bool = True,
) -> np.ndarray:
    """Draw normalized detections and control state on a BGR frame."""
    if not enabled:
        return frame.copy()
    output = frame.copy()
    height, width = output.shape[:2]
    event = event or {}
    control = control or {}
    osd_scale = _osd_scale(width, height)
    box_thickness = _scaled_pixels(2, osd_scale)
    guide_thickness = _scaled_pixels(1, osd_scale)
    margin = _scaled_pixels(10, osd_scale, minimum=4)
    label_gap = _scaled_pixels(6, osd_scale, minimum=3)
    label_baseline = _scaled_pixels(18, osd_scale, minimum=10)
    line_pitch = _scaled_pixels(22, osd_scale, minimum=10)
    input_baseline = max(
        22,
        label_baseline,
        _scaled_pixels(22, osd_scale),
    )
    active_baseline = max(
        _scaled_pixels(46, osd_scale),
        input_baseline + line_pitch,
    )
    active_center_baseline = active_baseline + line_pitch
    active_pose_baseline = active_center_baseline + line_pitch
    gesture_baseline = max(
        _scaled_pixels(112, osd_scale),
        (
            active_pose_baseline + line_pitch
            if isinstance(event.get("active_target"), dict)
            and float(
                event.get("active_target", {}).get("confidence", 0.0) or 0.0
            ) > 0.0
            else input_baseline + 2 * line_pitch
        ),
    )
    fall_baseline = gesture_baseline + line_pitch
    object_only = control.get("mode") == "object_only"
    active = event.get("active_target", {})
    if not isinstance(active, dict):
        active = {}
    try:
        active_track_id = int(active.get("track_id", 0) or 0)
    except (TypeError, ValueError):
        active_track_id = 0
    try:
        active_face_track_id = int(active.get("face_track_id", -1) or -1)
    except (TypeError, ValueError):
        active_face_track_id = -1

    if not object_only:
        cv2.line(
            output,
            (width // 2, 0),
            (width // 2, height),
            (0, 255, 255),
            guide_thickness,
        )
        # Solid centre, inner stop band (±0.08), outer activation band (±0.14).
        for ratio in (0.42, 0.58, 0.36, 0.64):
            x = int(width * ratio)
            cv2.line(
                output,
                (x, 0),
                (x, height),
                (80, 80, 80),
                guide_thickness,
            )

    tracked_objects = [
        item for item in event.get("tracked_objects", [])
        if isinstance(item, dict)
    ]
    tracked_objects.sort(
        key=lambda item: float(item.get("confidence", 0.0) or 0.0),
        reverse=True,
    )
    for detected_object in tracked_objects[:_MAX_OBJECT_OVERLAYS]:
        x1, y1, x2, y2 = _pixel_box(detected_object, width, height)
        cv2.rectangle(
            output, (x1, y1), (x2, y2), (255, 0, 220), box_thickness
        )
        _text(
            output,
            f"object {detected_object.get('label', '?')} "
            f"{float(detected_object.get('confidence', 0.0)):.2f}",
            x1,
            max(label_baseline, y1 - label_gap),
            (255, 80, 240),
            scale=osd_scale,
        )

    humans, debug_humans = _overlay_items(event, "debug_humans", "humans")
    for human in humans:
        x1, y1, x2, y2 = _pixel_box(human, width, height)
        try:
            human_track_id = int(human.get("track_id", -1) or -1)
        except (TypeError, ValueError):
            human_track_id = -1
        human_is_active = (
            debug_humans
            and human_track_id > 0
            and human_track_id == active_track_id
        )
        human_color = (0, 0, 255) if human_is_active else (0, 220, 0)
        _draw_overlay_box(
            output,
            (x1, y1, x2, y2),
            human_color,
            box_thickness,
            dashed=debug_humans and not human_is_active,
            scale=osd_scale,
        )
        action = str(human.get("pose_action", ""))
        if debug_humans and not human_is_active:
            action = ""
        _text(
            output,
            f"body id={human.get('track_id', -1)} "
            f"conf={float(human.get('confidence', 0.0)):.2f} "
            f"{human.get('pose_state', '')} "
            f"{action}",
            x1,
            max(label_baseline, y1 - label_gap),
            human_color,
            scale=osd_scale,
        )
        try:
            keypoint_format = normalize_keypoint_format(human.get("keypoint_format"))
        except ValueError:
            keypoint_format = ""
        if keypoint_format:
            _draw_landmarks(
                output,
                human.get("keypoints", []),
                (
                    _COCO_POSE_CONNECTIONS
                    if keypoint_format == "coco_17"
                    else _POSE_CONNECTIONS
                ),
                human_color,
                scale=osd_scale,
            )

    for hand in event.get("hands", []):
        if not isinstance(hand, dict):
            continue
        points = _draw_landmarks(
            output,
            hand.get("landmarks", []),
            _HAND_CONNECTIONS,
            (20, 120, 255),
            min_confidence=0.0,
            scale=osd_scale,
        )
        if points:
            anchor = points.get(0, next(iter(points.values())))
            _text(
                output,
                f"{hand.get('handedness', 'hand')} "
                f"{hand.get('hand_action', '')}",
                anchor[0],
                max(label_baseline, anchor[1] - label_gap),
                (30, 180, 255),
                scale=osd_scale,
            )

    faces, debug_faces = _overlay_items(event, "debug_faces", "faces")
    for face in faces:
        x1, y1, x2, y2 = _pixel_box(face, width, height)
        face_color = _face_overlay_color(face)
        try:
            face_track_id = int(face.get("track_id", -1) or -1)
        except (TypeError, ValueError):
            face_track_id = -1
        face_is_active = (
            debug_faces
            and face_track_id > 0
            and face_track_id == active_face_track_id
        )
        _draw_overlay_box(
            output,
            (x1, y1, x2, y2),
            face_color,
            box_thickness,
            dashed=debug_faces and not face_is_active,
            scale=osd_scale,
        )
        name = str(face.get("recognized_user", "") or "unknown")
        _text(
            output,
            f"face id={face.get('track_id', -1)} {name} "
            f"conf={float(face.get('confidence', 0)):.2f}",
            x1,
            min(height - label_gap, y2 + label_baseline),
            face_color,
            scale=osd_scale,
        )

    if (
        isinstance(active, dict)
        and float(active.get("confidence", 0.0) or 0.0) > 0.0
    ):
        values = active.get("bbox", [0, 0, 0, 0])
        if not isinstance(values, (list, tuple)) or len(values) < 4:
            values = [0, 0, 0, 0]
        bbox = {"x": values[0], "y": values[1], "w": values[2], "h": values[3]}
        x1, y1, x2, y2 = _pixel_box(bbox, width, height)
        cv2.rectangle(
            output, (x1, y1), (x2, y2), (0, 0, 255), box_thickness
        )
        center = active.get("body_center", [0.0, 0.0])
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            center = [0.0, 0.0]
        cx, cy = int(float(center[0]) * width), int(float(center[1]) * height)
        cv2.drawMarker(
            output,
            (cx, cy),
            (0, 0, 255),
            cv2.MARKER_CROSS,
            _scaled_pixels(20, osd_scale),
            box_thickness,
        )
        state = str(active.get("tracking_state", "lost"))
        _text(
            output,
            f"ACTIVE id={active.get('track_id', 0)} {state}",
            margin,
            active_baseline,
            (0, 80, 255),
            scale=osd_scale,
        )
        _text(
            output,
            f"center_x={float(center[0]):.3f} "
            f"err={float(center[0]) - 0.5:+.3f} "
            f"bbox_h={float(bbox['h']):.3f}",
            margin,
            active_center_baseline,
            (0, 80, 255),
            scale=osd_scale,
        )
        _text(
            output,
            f"pose={active.get('pose_state', '')} "
            f"action={active.get('pose_action', '')}",
            margin,
            active_pose_baseline,
            (0, 80, 255),
            scale=osd_scale,
        )

    mode = str(
        control.get(
            "mode", "disabled" if not control.get("enabled") else "centering"
        )
    )
    layout = str(control.get("_input_layout", ""))
    layout_text = f" source={layout}" if layout else ""
    visual_age_ms = control.get("_visual_age_ms")
    freshness = ""
    if isinstance(visual_age_ms, (int, float)):
        freshness = f" visual_age={float(visual_age_ms):.0f}ms"
    _text(
        output,
        f"input={width}x{height}{layout_text} mode={mode}{freshness}",
        margin,
        input_baseline,
        scale=osd_scale,
    )
    if event.get("events"):
        _text(
            output,
            "events=" + ",".join(str(item) for item in event["events"][:3]),
            margin,
            height - _scaled_pixels(36, osd_scale, minimum=18),
            (80, 180, 255),
            scale=osd_scale,
        )
    gesture_debug = control.get("_gesture_debug", {})
    if isinstance(gesture_debug, dict) and gesture_debug:
        recognized = gesture_debug.get("recognized_actions", [])
        names = [
            str(item.get("name", ""))
            for item in recognized
            if isinstance(item, dict) and item.get("name")
        ]
        if names:
            gesture_text = "recognized=" + ",".join(names[:4])
        else:
            candidates = gesture_debug.get("raw_scores", [])
            top = [
                f"{item.get('name')}:{float(item.get('score', 0.0)):.2f}"
                for item in candidates[:3]
                if isinstance(item, dict)
            ]
            gesture_text = "candidates=" + ",".join(top)
        _text(
            output,
            gesture_text,
            margin,
            gesture_baseline,
            (80, 255, 255),
            scale=osd_scale,
        )
        fall = gesture_debug.get("fall_detector", {})
        if isinstance(fall, dict) and fall:
            _text(
                output,
                f"fall={fall.get('phase', '?')} "
                f"armed={bool(fall.get('armed', False))} "
                f"lying={float(fall.get('lying_score', 0.0)):.2f} "
                f"transition={float(fall.get('transition_score', 0.0)):.2f}",
                margin,
                fall_baseline,
                (80, 255, 255),
                scale=osd_scale,
            )
    if cmd_vel is not None:
        _text(
            output,
            f"cmd linear.x={cmd_vel[0]:+.3f} angular.z={cmd_vel[1]:+.3f}",
            margin,
            height - _scaled_pixels(14, osd_scale, minimum=8),
            (255, 255, 0),
            scale=osd_scale,
        )
    return output
