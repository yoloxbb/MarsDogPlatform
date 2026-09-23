import math
import time
from types import SimpleNamespace

import numpy as np

from marsdog_vision_interaction.core.person_localization import (
    LOCALIZATION_INVALID_SOURCE,
    LOCALIZATION_UNSUPPORTED_GEOMETRY,
    normalized_bbox_to_roi,
    serialize_localization_response,
    validate_source_metadata,
)
from marsdog_vision_interaction.core.visual_target_manager import VisualTargetManager
from marsdog_vision_interaction.providers.vision_observation import VisionObservationProvider


def _source(*, split=False):
    return {
        "header": {
            "stamp": {"sec": 1789700000, "nanosec": 123456789},
            "frame_id": "camera_color_optical_frame",
        },
        "source_width": 640,
        "source_height": 480,
        "view_width": 640,
        "view_height": 480,
        "view_split": split,
        "received_monotonic": time.monotonic(),
    }


def test_roi_clips_edges_and_preserves_rectify_contract():
    assert normalized_bbox_to_roi(
        (-0.1, 0.2, 0.5, 0.9), 640, 480
    ) == {
        "x_offset": 0,
        "y_offset": 96,
        "width": 256,
        "height": 384,
        "do_rectify": False,
    }
    assert normalized_bbox_to_roi((0.2, 0.3, 0.0, 0.2), 640, 480) is None
    assert normalized_bbox_to_roi((math.nan, 0.3, 0.2, 0.2), 640, 480) is None
    assert normalized_bbox_to_roi((0.2, 0.3, 0.2, 0.2), 640, 480, view_split=True) is None


def test_roi_ceil_rule_keeps_a_real_fractional_right_edge():
    # One representable step beyond an integer pixel boundary is still a real
    # fractional extent and must expand rather than be rounded back down.
    right = math.nextafter(0.5, math.inf)
    roi = normalized_bbox_to_roi((0.25, 0.25, right - 0.25, 0.25), 640, 480)
    assert roi is not None
    assert roi["x_offset"] == 160
    assert roi["width"] == 161


def test_source_validation_rejects_zero_stamp_and_split_geometry():
    invalid = _source()
    invalid["header"]["stamp"] = {"sec": 0, "nanosec": 0}
    assert validate_source_metadata(invalid) == LOCALIZATION_INVALID_SOURCE
    assert validate_source_metadata(_source(split=True)) == LOCALIZATION_UNSUPPORTED_GEOMETRY


def test_manager_keeps_bbox_and_exact_source_atomically():
    manager = VisualTargetManager(vision_epoch="epoch-localization")
    source = _source()
    manager.update_vision(
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "confidence": 0.9}],
        [],
        source_metadata=source,
    )
    target_id = manager.get_human_candidates()[0]["target_id"]
    candidate = manager.get_localization_candidate(target_id)
    assert candidate is not None
    assert candidate["target"]["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert candidate["source"]["header"]["stamp"]["nanosec"] == 123456789

    # A later detection with missing provenance must not reuse the old source.
    manager.update_vision(
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "confidence": 0.9}],
        [],
    )
    assert manager.get_localization_candidate(target_id)["source"] is None


def test_latest_frame_slot_replaces_image_and_source_together():
    provider = VisionObservationProvider({"inference_frame_stride": 1})
    provider.available = True
    frame_a = np.zeros((2, 3, 3), dtype=np.uint8)
    frame_b = np.ones((4, 5, 3), dtype=np.uint8)
    source_a = _source()
    source_b = _source()
    source_b["header"]["stamp"] = {"sec": 1789700001, "nanosec": 987}
    provider.process_frame(frame_a, source_metadata=source_a)
    provider.process_frame(frame_b, source_metadata=source_b)
    with provider._frame_condition:
        assert provider._pending_frame is frame_b
        assert provider._pending_source_metadata == source_b


def _header(sec, nanosec, frame_id):
    return SimpleNamespace(
        stamp=SimpleNamespace(sec=sec, nanosec=nanosec),
        frame_id=frame_id,
    )


def test_response_serialization_preserves_nested_ros_geometry():
    point = SimpleNamespace(
        header=_header(10, 20, "map"),
        point=SimpleNamespace(x=1.0, y=2.0, z=0.0),
    )
    goal = SimpleNamespace(
        header=_header(11, 0, "map"),
        pose=SimpleNamespace(
            position=SimpleNamespace(x=0.5, y=0.6, z=0.0),
            orientation=SimpleNamespace(x=0.0, y=0.0, z=0.7, w=0.7),
        ),
    )
    response = SimpleNamespace(
        success=True,
        navigation_required=True,
        status=0,
        message="",
        person_point=point,
        navigation_goal=goal,
        valid_depth_ratio=0.8,
        mean_depth=2.1,
        depth_stddev=0.04,
    )
    result = serialize_localization_response(
        response,
        target_id="epoch-localization:human:1",
        source_header=_source()["header"],
    )
    assert result["ok"] is True
    assert result["person_point"]["header"]["stamp"] == {"sec": 10, "nanosec": 20}
    assert result["navigation_goal"]["pose"]["orientation"]["w"] == 0.7


def test_failed_response_never_exposes_navigation_geometry():
    response = SimpleNamespace(
        success=False,
        navigation_required=True,
        status=3,
        message="invalid bbox",
        person_point=SimpleNamespace(),
        navigation_goal=SimpleNamespace(),
        valid_depth_ratio=0.0,
        mean_depth=0.0,
        depth_stddev=0.0,
    )
    result = serialize_localization_response(
        response,
        target_id="epoch-localization:human:1",
        source_header=_source()["header"],
    )
    assert result["ok"] is False
    assert result["navigation_required"] is False
    assert result["error_code"] == "localization_server_error"
    assert "person_point" not in result
    assert "navigation_goal" not in result


def test_nonfinite_success_response_fails_without_navigation_geometry():
    response = SimpleNamespace(
        success=True,
        navigation_required=True,
        status=0,
        message="",
        person_point=SimpleNamespace(),
        navigation_goal=SimpleNamespace(),
        valid_depth_ratio=math.nan,
        mean_depth=2.0,
        depth_stddev=0.02,
    )
    result = serialize_localization_response(
        response,
        target_id="epoch-localization:human:1",
        source_header=_source()["header"],
    )
    assert result["ok"] is False
    assert result["navigation_required"] is False
    assert result["error_code"] == "localization_invalid_response"
    assert "person_point" not in result
    assert "navigation_goal" not in result
