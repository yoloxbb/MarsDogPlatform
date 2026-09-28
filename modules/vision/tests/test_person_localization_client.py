import threading
import time
from types import SimpleNamespace

from marsdog_vision_interaction.core.visual_target_manager import VisualTargetManager
from marsdog_vision_interaction.nodes.vision_interaction_node import VisionInteractionNode


class _Stamp:
    sec = 0
    nanosec = 0


class _Header:
    def __init__(self):
        self.stamp = _Stamp()
        self.frame_id = ""


class _ROI:
    x_offset = 0
    y_offset = 0
    width = 0
    height = 0
    do_rectify = True


class _Request:
    def __init__(self):
        self.image_header = _Header()
        self.bbox = _ROI()
        self.stand_off_distance = 0.0


class _LocateFromBbox:
    Request = _Request


class _Future:
    def __init__(self, response=None, error=None, callback_error=None):
        self._response = response
        self._error = error
        self._callbacks = []
        self._done = response is not None or error is not None
        self._callback_error = callback_error
        self.cancelled = False

    def add_done_callback(self, callback):
        if self._callback_error is not None:
            raise self._callback_error
        self._callbacks.append(callback)
        if self._done:
            callback(self)

    def result(self):
        if self._error is not None:
            raise self._error
        return self._response

    def cancel(self):
        self.cancelled = True


class _Client:
    def __init__(
        self,
        response=None,
        ready=True,
        delayed=False,
        call_error=None,
        callback_error=None,
    ):
        self.response = response
        self.ready = ready
        self.delayed = delayed
        self.call_error = call_error
        self.callback_error = callback_error
        self.requests = []
        self.removed = []
        self.future = None

    def service_is_ready(self):
        return self.ready

    def call_async(self, request):
        if self.call_error is not None:
            raise self.call_error
        self.requests.append(request)
        self.future = _Future(
            None if self.delayed else self.response,
            callback_error=self.callback_error,
        )
        return self.future

    def remove_pending_request(self, future):
        self.removed.append(future)

    def complete(self):
        self.future._response = self.response
        self.future._done = True
        for callback in self.future._callbacks:
            callback(self.future)


def _response():
    header = SimpleNamespace(
        stamp=SimpleNamespace(sec=20, nanosec=30),
        frame_id="map",
    )
    point = SimpleNamespace(
        header=header,
        point=SimpleNamespace(x=1.0, y=0.2, z=0.0),
    )
    goal = SimpleNamespace(
        header=header,
        pose=SimpleNamespace(
            position=SimpleNamespace(x=0.4, y=0.2, z=0.0),
            orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
    )
    return SimpleNamespace(
        success=True,
        navigation_required=True,
        status=0,
        message="",
        person_point=point,
        navigation_goal=goal,
        valid_depth_ratio=0.8,
        mean_depth=2.0,
        depth_stddev=0.02,
    )


def _node(client):
    manager = VisualTargetManager(vision_epoch="epoch-client")
    manager.update_vision(
        [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "confidence": 0.9}],
        [],
        source_metadata={
            "header": {
                "stamp": {"sec": 20, "nanosec": 30},
                "frame_id": "camera_color_optical_frame",
            },
            "source_width": 640,
            "source_height": 480,
            "view_width": 640,
            "view_height": 480,
            "view_split": False,
            "received_monotonic": time.monotonic(),
        },
    )
    target_id = manager.get_human_candidates()[0]["target_id"]
    return SimpleNamespace(
        _target_manager=manager,
        _target_current_timeout_sec=0.35,
        _slam_service_type=_LocateFromBbox,
        _slam_client=client,
        _slam_ready_timeout_sec=0.01,
        _slam_response_timeout_sec=0.05,
        target_id=target_id,
    )


def test_locate_person_once_builds_one_exact_request():
    client = _Client(response=_response())
    node = _node(client)
    result = VisionInteractionNode._locate_person_once(
        node,
        {"target_id": node.target_id, "stand_off_distance": 1.5},
    )
    assert result["ok"] is True
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.image_header.stamp.sec == 20
    assert request.image_header.stamp.nanosec == 30
    assert request.image_header.frame_id == "camera_color_optical_frame"
    assert (request.bbox.x_offset, request.bbox.y_offset) == (64, 96)
    # Conservative ceil on the right/bottom can expand a floating-point
    # boundary by one pixel; it must never cut the detector box short.
    assert (request.bbox.width, request.bbox.height) == (192, 193)
    assert request.bbox.do_rectify is False
    assert request.stand_off_distance == 1.5


def test_locate_person_once_does_not_call_unavailable_server():
    client = _Client(response=_response(), ready=False)
    node = _node(client)
    result = VisionInteractionNode._locate_person_once(
        node,
        {"target_id": node.target_id},
    )
    assert result["ok"] is False
    assert result["error_code"] == "localization_server_unavailable"
    assert client.requests == []


def test_locate_person_once_reports_missing_optional_interface():
    client = _Client(response=_response())
    node = _node(client)
    node._slam_service_type = None
    result = VisionInteractionNode._locate_person_once(
        node,
        {"target_id": node.target_id},
    )
    assert result["ok"] is False
    assert result["error_code"] == "localization_interface_unavailable"
    assert client.requests == []


def test_locate_person_once_timeout_removes_pending_request():
    client = _Client(response=_response(), delayed=True)
    node = _node(client)
    result = VisionInteractionNode._locate_person_once(
        node,
        {"target_id": node.target_id},
    )
    assert result["error_code"] == "localization_timeout"
    assert client.removed == [client.future]
    assert client.future.cancelled is True


def test_locate_person_once_cleans_up_when_callback_registration_fails():
    client = _Client(
        response=_response(),
        callback_error=RuntimeError("cannot register callback"),
    )
    node = _node(client)
    result = VisionInteractionNode._locate_person_once(
        node,
        {"target_id": node.target_id},
    )
    assert result["error_code"] == "localization_client_error"
    assert client.removed == [client.future]
    assert client.future.cancelled is True


def test_locate_person_once_reports_call_exception_without_retry():
    client = _Client(
        response=_response(),
        call_error=RuntimeError("transport failed"),
    )
    node = _node(client)
    result = VisionInteractionNode._locate_person_once(
        node,
        {"target_id": node.target_id},
    )
    assert result["error_code"] == "localization_client_error"
    assert client.requests == []
