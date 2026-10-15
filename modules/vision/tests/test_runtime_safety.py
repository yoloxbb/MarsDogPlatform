import json
import threading
import time
from types import MethodType, SimpleNamespace

import numpy as np
import pytest

from marsdog_vision_interaction.core.face_enrollment_manager import (
    FaceEnrollmentManager,
    set_storage_root,
)
from marsdog_vision_interaction.core.held_object_pose import (
    HELD_OBJECT_LABELS,
    HeldObjectPoseStatus,
)
from marsdog_vision_interaction.core.owner_presence_event_state import (
    OwnerPresenceEventConfig,
    OwnerPresenceEventState,
)
from marsdog_vision_interaction.core.owner_posture_event_state import (
    OwnerPostureEventConfig,
    OwnerPostureEventState,
)
from marsdog_vision_interaction.core.owner_recall_gesture_event_state import (
    OwnerRecallGestureEventConfig,
    OwnerRecallGestureEventState,
)
from marsdog_vision_interaction.core.presence_event_state import (
    PresenceEventConfig,
    PresenceEventState,
)
from marsdog_vision_interaction.core.toy_presence_event_state import (
    ToyPresenceEventConfig,
    ToyPresenceEventState,
)
from marsdog_vision_interaction.core.object_detection_session import (
    ObjectDetectionSessionManager,
)
from marsdog_vision_interaction.core.visual_target_manager import VisualTargetManager
from marsdog_vision_interaction.nodes.camera_driver_node import (
    _video_capture_source,
)
from marsdog_vision_interaction.nodes.vision_interaction_node import VisionInteractionNode
from marsdog_vision_interaction.nodes import vision_interaction_node as vision_node_module
from marsdog_vision_interaction.nodes.vision_debug_viewer_node import (
    VisionDebugViewerNode,
)
from marsdog_vision_interaction.providers.object_detector import ObjectDetectorProvider
from marsdog_vision_interaction.providers.face_recognition import (
    FaceRecognitionProvider,
)
from marsdog_vision_interaction.providers import (
    face_recognition as face_recognition_module,
    vision_observation as vision_observation_module,
)
from marsdog_vision_interaction.providers.vision_observation import (
    VisionObservationProvider,
)


class _CachedVision:
    def is_available(self) -> bool:
        return True

    def get_observation(self) -> dict:
        return {
            "humans": [{
                "x": 0.2, "y": 0.1, "w": 0.4, "h": 0.8,
                "confidence": 0.9,
            }],
        }


def test_camera_source_accepts_portable_index_and_explicit_override() -> None:
    assert _video_capture_source("4") == 4
    assert _video_capture_source("custom-device") == "custom-device"


class _Publisher:
    def __init__(self) -> None:
        self.messages = []

    def publish(self, message) -> None:
        self.messages.append(message)


class _FakeLandmarker:
    def __init__(self) -> None:
        self.calls = []

    def detect(self, image):
        self.calls.append(("image", image, None))
        return "image-result"

    def detect_for_video(self, image, timestamp_ms):
        self.calls.append(("video", image, timestamp_ms))
        return "video-result"


class _FakeFaceDetector:
    def setInputSize(self, size) -> None:
        self.size = size

    def detect(self, frame):
        _ = frame
        detection = np.array([
            2, 3, 20, 24,
            5, 6, 15, 6, 10, 11, 6, 19, 15, 19,
            0.95,
        ], dtype=np.float32)
        return None, np.array([detection], dtype=np.float32)


class _FakeFaceTracker:
    def update(self, xyxy, scores):
        _ = scores
        return np.arange(1, len(xyxy) + 1, dtype=np.int64)


def test_stale_camera_does_not_refresh_cached_target(monkeypatch) -> None:
    timing_traces = []
    monkeypatch.setattr(
        vision_node_module,
        "vision_timing_trace",
        lambda **fields: timing_traces.append(fields),
    )
    manager = VisualTargetManager()
    manager.update_vision([{
        "x": 0.2, "y": 0.1, "w": 0.4, "h": 0.8,
        "confidence": 0.9,
    }], [])
    manager._active.last_seen_at = time.time() - 1.0
    publisher = _Publisher()
    fake_node = SimpleNamespace(
        _state_lock=threading.Lock(),
        _enrollment_lock=threading.RLock(),
        _enrollment=SimpleNamespace(face_session=None),
        _providers={"vision": _CachedVision()},
        _vision_is_mock=False,
        _latest_camera_monotonic=time.monotonic() - 1.0,
        _camera_stale_timeout_sec=0.5,
        _latest_objects_monotonic=0.0,
        _object_cache_timeout_sec=1.0,
        _latest_objects=[],
        _target_manager=manager,
        _visual_pub=publisher,
        _publish_gesture_debug=lambda raw: None,
        _derive_events=VisionInteractionNode._derive_events,
        _process_enrollment_frame=lambda: None,
        _owner_presence_event_state=OwnerPresenceEventState(
            OwnerPresenceEventConfig(), source_freshness_sec=0.5
        ),
    )

    VisionInteractionNode._publish_visual(fake_node)
    payload = json.loads(publisher.messages[-1].data)
    assert payload["humans"] == []
    assert payload["active_target"]["tracking_state"] == "temporarily_lost"
    assert payload["active_target"]["last_seen_age_ms"] >= 900.0
    assert payload["observation_status"] == "invalid"
    assert "EVT_VISION_MASTER" not in payload["events"]
    assert any(
        item["module"] == "depth_fusion"
        and item["stage"] == "aligned_depth_range"
        for item in timing_traces
    )
    assert any(
        item["module"] == "visual_event"
        and item["stage"] == "event_publish"
        for item in timing_traces
    )


def test_presence_event_publication_preserves_instances_and_strips_private_evidence() -> None:
    from marsdog_vision_interaction.nodes.vision_interaction_node import (
        _apply_presence_event_states,
    )

    def state(tag, key, identities, identity_state):
        return PresenceEventState(
            PresenceEventConfig(
                enter_duration_sec=0.2,
                exit_duration_sec=0.2,
                retrigger_delay_sec=3.0,
            ),
            event_tag=tag,
            source_target_ids_key=key,
            identities=set(identities),
            identity_state=identity_state,
            source_freshness_sec=0.5,
        )

    family = state(
        "family-presence",
        "_source_family_target_ids",
        {"family_member_1", "family_member_2", "family_member_3", "family_member_4"},
        "confirmed_known",
    )
    stranger = state(
        "stranger-presence",
        "_source_stranger_target_ids",
        {"unknown"},
        "confirmed_unknown",
    )
    presence_states = (
        ("EVT_VISION_FAMILY_PRESENT", family),
        ("EVT_VISION_STRANGER", stranger),
    )

    def observation(sequence, *, status="valid", present=True):
        family_id = f"epoch:human:family-{sequence}"
        stranger_id = f"epoch:human:stranger-{sequence}"
        return {
            "schema_version": 1,
            "vision_epoch": "epoch",
            "snapshot_id": f"epoch:{sequence}",
            "sequence": sequence,
            "source_observation_id": f"frame:{sequence}",
            "_source_observation_age_sec": 0.0,
            "observation_status": status,
            "events": ["EVT_VISION_MASTER"],
            "event_instances": {
                "EVT_VISION_MASTER": {"event_id": "owner-cycle"},
                "UNRELATED_EVENT": {"event_id": "keep-me"},
            },
            "_source_owner_target_ids": [],
            "_source_family_target_ids": [family_id] if present else [],
            "_source_stranger_target_ids": [stranger_id] if present else [],
            "human_candidates": [
                {
                    "vision_epoch": "epoch",
                    "target_id": family_id,
                    "track_id": sequence + 1,
                    "identity": "family_member_1",
                    "identity_state": "confirmed_known",
                    "tracking_state": "tracking",
                },
                {
                    "vision_epoch": "epoch",
                    "target_id": stranger_id,
                    "track_id": sequence + 101,
                    "identity": "unknown",
                    "identity_state": "confirmed_unknown",
                    "tracking_state": "tracking",
                },
            ] if present else [],
        }

    packet = None
    for index in range(3):
        packet = _apply_presence_event_states(
            observation(index + 1), presence_states, now=10.0 + index * 0.11
        )
    assert packet is not None
    assert "EVT_VISION_FAMILY_PRESENT" in packet["events"]
    assert "EVT_VISION_STRANGER" in packet["events"]
    assert "EVT_VISION_STRANGER_PRESENT" not in packet["events"]
    assert packet["event_instances"]["EVT_VISION_MASTER"] == {
        "event_id": "owner-cycle"
    }
    assert packet["event_instances"]["UNRELATED_EVENT"] == {
        "event_id": "keep-me"
    }
    family_event_id = packet["event_instances"]["EVT_VISION_FAMILY_PRESENT"][
        "event_id"
    ]
    stranger_event_id = packet["event_instances"]["EVT_VISION_STRANGER"][
        "event_id"
    ]
    assert family_event_id != stranger_event_id
    assert not any(key.startswith("_source_") for key in packet)

    packet = _apply_presence_event_states(
        observation(4, status="invalid", present=False),
        presence_states,
        now=10.33,
    )
    assert packet["event_instances"]["EVT_VISION_FAMILY_PRESENT"][
        "event_id"
    ] == family_event_id
    assert packet["event_instances"]["EVT_VISION_STRANGER"][
        "event_id"
    ] == stranger_event_id

    for index in range(3):
        packet = _apply_presence_event_states(
            observation(5 + index, present=False),
            presence_states,
            now=10.44 + index * 0.11,
        )
    assert "EVT_VISION_FAMILY_PRESENT" not in packet["events"]
    assert "EVT_VISION_STRANGER" not in packet["events"]
    assert "EVT_VISION_FAMILY_PRESENT" not in packet["event_instances"]
    assert "EVT_VISION_STRANGER" not in packet["event_instances"]
    assert packet["event_instances"]["EVT_VISION_MASTER"][
        "event_id"
    ] == "owner-cycle"


def test_owner_presence_publishes_master_state_and_keeps_legacy_family_master() -> None:
    from marsdog_vision_interaction.messages.visual_event_types import (
        EVT_VISION_MASTER,
    )
    from marsdog_vision_interaction.nodes.vision_interaction_node import (
        _apply_presence_event_states,
        _suppress_owner_master_face_fact,
    )

    state = OwnerPresenceEventState(
        OwnerPresenceEventConfig(
            enter_duration_sec=0.4,
            exit_duration_sec=0.4,
            retrigger_delay_sec=3.0,
        ),
        source_freshness_sec=0.5,
    )
    states = ((EVT_VISION_MASTER, state),)
    target_id = "epoch:human:7"

    def observation(
        sequence,
        *,
        identity="owner",
        status="valid",
        present=True,
    ):
        target = {
            "vision_epoch": "epoch",
            "target_id": target_id,
            "target_type": "human",
            "track_id": 7,
            "identity": identity,
            "identity_state": "confirmed_known",
            "tracking_state": "tracking",
            "last_seen_age_ms": 0.0,
        }
        return {
            "schema_version": 1,
            "vision_epoch": "epoch",
            "snapshot_id": f"epoch:{sequence}",
            "sequence": sequence,
            "source_observation_id": f"frame:{sequence}",
            "_source_observation_age_sec": 0.0,
            "observation_status": status,
            # Face derivation is immediate; the node gates this only for owner.
            "events": [EVT_VISION_MASTER] if present else [],
            "active_target": target if present else {},
            "_source_owner_target_ids": (
                [target_id] if present and identity == "owner" else []
            ),
            "human_candidates": [target] if present else [],
        }

    def publish(value, now):
        preserve_legacy_master = _suppress_owner_master_face_fact(value)
        return _apply_presence_event_states(
            value,
            states,
            now=now,
            preserve_if_inactive=(
                frozenset({EVT_VISION_MASTER})
                if preserve_legacy_master
                else frozenset()
            ),
        )

    first = publish(observation(1), 10.0)
    second = publish(observation(2), 10.2)
    assert EVT_VISION_MASTER not in first["events"]
    assert EVT_VISION_MASTER not in second["events"]

    entered = publish(observation(3), 10.4)
    event_id = entered["event_instances"][EVT_VISION_MASTER]["event_id"]
    assert EVT_VISION_MASTER in entered["events"]
    assert "EVT_VISION_OWNER_PRESENT" not in entered["events"]
    assert "EVT_VISION_OWNER_PRESENT" not in entered["event_instances"]

    invalid = publish(observation(4, status="invalid"), 10.6)
    assert invalid["event_instances"][EVT_VISION_MASTER]["event_id"] == event_id

    publish(observation(5, present=False), 10.8)
    publish(observation(6, present=False), 11.0)
    publish(observation(7, present=False), 11.2)
    exited = publish(observation(8, present=False), 11.4)
    assert EVT_VISION_MASTER not in exited["events"]
    assert EVT_VISION_MASTER not in exited.get("event_instances", {})

    family = publish(
        observation(9, identity="family_member_1"),
        11.6,
    )
    assert EVT_VISION_MASTER in family["events"]
    assert EVT_VISION_MASTER not in family.get("event_instances", {})


def test_owner_posture_event_publication_adds_holds_and_removes_active_instance() -> None:
    from marsdog_vision_interaction.nodes.vision_interaction_node import (
        _apply_presence_event_states,
    )

    event_state = OwnerPostureEventState(
        OwnerPostureEventConfig.from_mapping({"enter_duration_sec": 1.0}),
        source_freshness_sec=0.5,
    )
    states = (("EVT_VISION_OWNER_BEND_SQUAT", event_state),)
    target_id = "epoch:human:7"

    def observation(sequence, *, pose="bend_over", status="valid"):
        return {
            "schema_version": 1,
            "vision_epoch": "epoch",
            "snapshot_id": f"epoch:{sequence}",
            "sequence": sequence,
            "source_observation_id": f"frame:{sequence}",
            "_source_observation_age_sec": 0.0,
            "observation_status": status,
            "events": ["EVT_VISION_MASTER"],
            "event_instances": {
                "EVT_VISION_MASTER": {"event_id": "owner-cycle"},
            },
            "_source_owner_target_ids": [target_id],
            "_source_human_target_ids": [target_id],
            "human_candidates": [{
                "vision_epoch": "epoch",
                "target_id": target_id,
                "track_id": 7,
                "target_type": "human",
                "identity": "owner",
                "identity_state": "confirmed_known",
                "tracking_state": "tracking",
                "pose_action": pose,
                "last_seen_age_ms": 0.0,
            }],
        }

    packet = None
    for sequence in range(1, 7):
        packet = _apply_presence_event_states(
            observation(sequence), states, now=10.0 + (sequence - 1) * 0.2
        )
    assert packet is not None
    posture_id = packet["event_instances"]["EVT_VISION_OWNER_BEND_SQUAT"][
        "event_id"
    ]
    assert "EVT_VISION_OWNER_BEND_SQUAT" in packet["events"]
    assert "EVT_VISION_MASTER" in packet["events"]
    assert not any(key.startswith("_source_") for key in packet)

    duplicate = observation(7)
    duplicate["source_observation_id"] = "frame:6"
    held = _apply_presence_event_states(duplicate, states, now=12.0)
    assert held["event_instances"]["EVT_VISION_OWNER_BEND_SQUAT"][
        "event_id"
    ] == posture_id

    invalid = _apply_presence_event_states(
        observation(8, pose="", status="invalid"),
        states,
        now=12.2,
    )
    assert invalid["event_instances"]["EVT_VISION_OWNER_BEND_SQUAT"][
        "event_id"
    ] == posture_id

    released = _apply_presence_event_states(
        observation(9, pose=""), states, now=12.4
    )
    assert "EVT_VISION_OWNER_BEND_SQUAT" not in released["events"]
    assert "EVT_VISION_OWNER_BEND_SQUAT" not in released.get(
        "event_instances", {}
    )
    assert "EVT_VISION_MASTER" in released["events"]


def test_owner_recall_publication_uses_private_stable_actions_and_v1_instance() -> None:
    from marsdog_vision_interaction.nodes.vision_interaction_node import (
        _apply_presence_event_states,
    )

    event_name = "EVT_VISION_OWNER_RECALL_GESTURE"
    target_id = "epoch:human:7"
    state = OwnerRecallGestureEventState(
        OwnerRecallGestureEventConfig(), source_freshness_sec=0.5
    )
    states = ((event_name, state),)

    def observation(sequence, *, actions=(), status="valid"):
        target = {
            "vision_epoch": "epoch",
            "target_id": target_id,
            "target_type": "human",
            "track_id": 7,
            "identity": "owner",
            "identity_state": "confirmed_known",
            "tracking_state": "tracking",
            "last_seen_age_ms": 0.0,
        }
        return {
            "schema_version": 1,
            "vision_epoch": "epoch",
            "snapshot_id": f"epoch:{sequence}",
            "sequence": sequence,
            "source_observation_id": f"frame:{sequence}",
            "_source_observation_age_sec": 0.0,
            "_source_owner_target_ids": [target_id],
            "_source_human_target_ids": [target_id],
            "observation_status": status,
            "events": ["EVT_VISION_MASTER"],
            "human_candidates": [dict(target)],
            "active_target": dict(target),
            "_gesture_target_id": target_id,
            "_gesture_track_id": 7,
            "_gesture_diagnostics": {
                "recognized_actions": [{"name": action} for action in actions],
                "recall_gesture_evidence": {
                    name: {
                        "valid_sides": ["left", "right"],
                        "release_sides": ["left", "right"],
                        "active_sides": ["left"] if name in actions else [],
                    }
                    for name in ("beckoning", "waving")
                },
                "raw_scores": [{"name": "beckoning", "score": 0.0}],
            },
        }

    trigger = observation(1, actions=("beckoning",))
    packet = _apply_presence_event_states(
        trigger,
        states,
        now=10.0,
        event_state_observations={event_name: trigger},
    )
    event_id = packet["event_instances"][event_name]["event_id"]
    assert event_name in packet["events"]
    assert packet["event_instances"][event_name] == {"event_id": event_id}
    assert "EVT_VISION_MASTER" in packet["events"]
    assert not any(key.startswith("_") for key in packet)

    invalid = observation(2, status="invalid")
    packet = _apply_presence_event_states(
        invalid,
        states,
        now=10.1,
        event_state_observations={event_name: invalid},
    )
    assert packet["event_instances"][event_name]["event_id"] == event_id

    release = observation(3)
    packet = _apply_presence_event_states(
        release,
        states,
        now=10.2,
        event_state_observations={event_name: release},
    )
    assert event_name not in packet["events"]
    assert event_name not in packet.get("event_instances", {})
    assert "EVT_VISION_MASTER" in packet["events"]


def test_observation_cache_keeps_source_identity_and_marks_latest_inference_failure() -> None:
    provider = VisionObservationProvider({})
    provider._cached_observation = {"human_candidates": []}
    provider._source_observation_id = "camera-stamp:4"
    provider._source_observation_monotonic = time.monotonic()
    provider._source_observation_valid = True

    first = provider.get_observation()
    second = provider.get_observation()
    assert first["_source_observation_id"] == "camera-stamp:4"
    assert second["_source_observation_id"] == first["_source_observation_id"]
    assert first["_source_observation_valid"] is True
    assert first["_source_observation_age_sec"] <= second["_source_observation_age_sec"]

    # A failed latest inference leaves the legacy cache available but makes
    # that cached result invalid owner-event evidence.
    provider._source_observation_valid = False
    failed = provider.get_observation()
    assert failed["_source_observation_id"] == "camera-stamp:4"
    assert failed["_source_observation_valid"] is False


def test_source_human_target_ids_require_current_body_and_face_association() -> None:
    current_humans = [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}]
    current_faces = [{"track_id": 17, "recognized_user": "family_member_1"}]
    candidate = {
        "bbox": [0.1, 0.2, 0.3, 0.4],
        "target_id": "epoch:human:7",
        "track_id": 7,
        "face_track_id": 17,
        "identity": "family_member_1",
        "identity_state": "confirmed_known",
        "tracking_state": "tracking",
    }

    current = VisionObservationProvider._current_source_human_target_ids(
        current_humans,
        current_faces,
        [candidate],
    )
    assert current == ["epoch:human:7"]

    # A retained manager row without this source frame's matching face is not
    # source association evidence.
    assert VisionObservationProvider._current_source_human_target_ids(
        current_humans,
        [],
        [candidate],
    ) == []

    lost_track = {**candidate, "tracking_state": "temporarily_lost"}
    assert VisionObservationProvider._current_source_human_target_ids(
        current_humans,
        current_faces,
        [lost_track],
    ) == []


@pytest.mark.parametrize("failure", [None, "face", "pose"])
def test_detector_failure_is_not_valid_owner_absence(failure) -> None:
    class FaceDetector:
        def setInputSize(self, size):
            pass

        def detect(self, frame):
            if failure == "face":
                raise RuntimeError("face inference failed")
            return None, None

    class PoseBackend:
        def process(self, frame):
            if failure == "pose":
                raise RuntimeError("pose inference failed")
            return []

        def close(self):
            pass

    provider = VisionObservationProvider({})
    provider.available = True
    provider.task_hand_enabled = False
    provider._face_detector = FaceDetector()
    provider._face_rec_model = object()
    provider._pose_backend_kind = "rknn"
    provider._pose_backend = PoseBackend()
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    result = provider._process_frame_impl(frame)
    assert result["_source_owner_target_ids"] == []
    assert result["_source_inference_valid"] is (failure is None)

    # Internal detector failures still produce the legacy empty frame, but
    # must remain invalid after the worker caches and publishes its evidence.
    provider._process_frame_impl = lambda frame: dict(result)
    provider._start_inference_worker()
    try:
        provider.process_frame(frame)
        deadline = time.monotonic() + 1.0
        while provider._inferred_frame_count < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert provider._inferred_frame_count == 1
        assert provider.get_observation()["_source_observation_valid"] is (failure is None)
    finally:
        provider.stop()


def test_recognition_failure_invalidates_owner_evidence() -> None:
    class RecognitionModel:
        def feature(self, frame):
            raise RuntimeError("recognition inference failed")

    provider = VisionObservationProvider({})
    provider._face_rec_model = RecognitionModel()
    provider._face_rec_throttle = SimpleNamespace(enrolled_count=1)
    provider._disable_fatal_face_model = lambda *args: False
    provider._owner_presence_inference_valid = True
    result = provider._run_sface(
        np.zeros((40, 40, 3), dtype=np.uint8),
        {"x1": 1, "y1": 1, "x2": 20, "y2": 20},
    )
    assert result == ("unknown", 0.0)
    assert provider._owner_presence_inference_valid is False


def test_current_owner_source_evidence_requires_current_confirmed_face_and_body() -> None:
    human = {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.7}
    candidate = {
        "target_id": "epoch:human:7",
        "bbox": [0.1, 0.1, 0.3, 0.7],
        "track_id": 7,
        "face_track_id": 17,
        "identity": "owner",
        "identity_state": "confirmed_known",
        "tracking_state": "tracking",
    }
    current_face = {
        "track_id": 17,
        "recognized_user": "owner",
        "identity_state": "confirmed_known",
    }

    assert VisionObservationProvider._current_owner_target_ids(
        [human], [current_face], [candidate]
    ) == ["epoch:human:7"]
    assert VisionObservationProvider._current_owner_target_ids(
        [human], [{**current_face, "recognized_user": "family_member_1"}], [candidate]
    ) == []
    assert VisionObservationProvider._current_owner_target_ids(
        [human], [{**current_face, "identity_state": "unverified"}], [candidate]
    ) == []
    assert VisionObservationProvider._current_owner_target_ids(
        [human], [], [candidate]
    ) == []
    assert VisionObservationProvider._current_owner_target_ids(
        [human], [current_face], [{**candidate, "tracking_state": "temporarily_lost"}]
    ) == []


@pytest.mark.parametrize(
    ("identity", "identity_state"),
    [
        ("owner", "confirmed_known"),
        ("family_member_3", "confirmed_known"),
        ("unknown", "confirmed_unknown"),
    ],
)
@pytest.mark.parametrize("malformed_identity", [[], {}, 42])
def test_current_presence_source_evidence_rejects_non_string_identity(
    identity: str,
    identity_state: str,
    malformed_identity,
) -> None:
    human = {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.7}
    candidate = {
        "target_id": "epoch:human:7",
        "bbox": [0.1, 0.1, 0.3, 0.7],
        "track_id": 7,
        "face_track_id": 17,
        "identity": identity,
        "identity_state": identity_state,
        "tracking_state": "tracking",
    }
    face = {
        "track_id": 17,
        "recognized_user": identity,
        "identity_state": identity_state,
    }
    for current_face, current_candidate in (
        ({**face, "recognized_user": malformed_identity}, candidate),
        (face, {**candidate, "identity": malformed_identity}),
    ):
        assert VisionObservationProvider._current_presence_target_ids(
            [human], [current_face], [current_candidate],
            identities={identity},
            identity_state=identity_state,
        ) == []


def test_current_family_source_evidence_requires_enrolled_identity() -> None:
    human = {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.7}
    candidate = {
        "target_id": "epoch:human:7",
        "bbox": [0.1, 0.1, 0.3, 0.7],
        "track_id": 7,
        "face_track_id": 17,
        "identity": "family_member_3",
        "identity_state": "confirmed_known",
        "tracking_state": "tracking",
    }
    face = {
        "track_id": 17,
        "recognized_user": "family_member_3",
        "identity_state": "confirmed_known",
    }
    eligible = {
        "family_member_1", "family_member_2",
        "family_member_3", "family_member_4",
    }
    assert VisionObservationProvider._current_presence_target_ids(
        [human], [face], [candidate],
        identities=eligible,
        identity_state="confirmed_known",
    ) == ["epoch:human:7"]
    assert VisionObservationProvider._current_presence_target_ids(
        [human], [face], [{**candidate, "identity": "owner"}],
        identities=eligible,
        identity_state="confirmed_known",
    ) == []
    assert VisionObservationProvider._current_presence_target_ids(
        [human], [face], [{**candidate, "identity_state": "candidate_known"}],
        identities=eligible,
        identity_state="confirmed_known",
    ) == []


def test_current_stranger_source_evidence_requires_confirmed_unknown_face() -> None:
    human = {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.7}
    candidate = {
        "target_id": "epoch:human:7",
        "bbox": [0.1, 0.1, 0.3, 0.7],
        "track_id": 7,
        "face_track_id": 17,
        "identity": "unknown",
        "identity_state": "confirmed_unknown",
        "tracking_state": "tracking",
    }
    face = {
        "track_id": 17,
        "recognized_user": "",
        "identity_state": "confirmed_unknown",
    }
    assert VisionObservationProvider._current_presence_target_ids(
        [human], [face], [candidate],
        identities={"unknown"},
        identity_state="confirmed_unknown",
    ) == ["epoch:human:7"]
    assert VisionObservationProvider._current_presence_target_ids(
        [human], [{**face, "identity_state": "unknown_candidate"}], [candidate],
        identities={"unknown"},
        identity_state="confirmed_unknown",
    ) == []
    assert VisionObservationProvider._current_presence_target_ids(
        [human], [face], [{**candidate, "tracking_state": "temporarily_lost"}],
        identities={"unknown"},
        identity_state="confirmed_unknown",
    ) == []


def test_mono_task_frame_is_not_cropped() -> None:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    fake_node = SimpleNamespace(
        _state_lock=threading.Lock(),
        _vision_is_mock=False,
        _latest_frame=frame,
        _latest_camera_monotonic=time.monotonic(),
        _camera_stale_timeout_sec=0.5,
        _stereo_enabled=False,
        _stereo_view="left",
        _stereo_min_aspect_ratio=2.2,
    )
    selected = VisionInteractionNode._frame_for_tasks(fake_node)
    assert selected is not None
    assert selected.shape == (480, 640, 3)


def test_face_detector_and_tracker_emit_separate_stage_timings(
    monkeypatch,
) -> None:
    traces = []
    monkeypatch.setattr(
        vision_observation_module,
        "vision_timing_trace",
        lambda **fields: traces.append(fields),
    )
    provider = VisionObservationProvider({"face_tracking": {}})
    provider._face_detector = _FakeFaceDetector()
    provider._face_tracker = _FakeFaceTracker()

    faces = provider._detect_faces(
        np.zeros((40, 40, 3), dtype=np.uint8),
        40,
        40,
        inference_sequence=9,
    )

    assert len(faces) == 1
    assert faces[0]["track_id"] == 1
    assert [item["module"] for item in traces] == [
        "face_detection",
        "face_tracking",
    ]
    assert traces[0]["stage"] == "yunet_inference"
    assert traces[0]["detection_count"] == 1
    assert traces[1]["stage"] == "bytetrack_update"
    assert traces[1]["track_count"] == 1
    assert all(item["inference_sequence"] == 9 for item in traces)


def test_real_provider_uses_latest_eligible_frame_without_callback_blocking() -> None:
    provider = VisionObservationProvider({"inference_frame_stride": 2})
    provider.available = True
    inferred_values = []
    first_started = threading.Event()
    release_first = threading.Event()

    def infer(frame):
        value = int(frame[0, 0, 0])
        inferred_values.append(value)
        if value == 0:
            first_started.set()
            assert release_first.wait(timeout=1.0)
        return {"frame_value": value}

    provider._process_frame_impl = infer
    provider._start_inference_worker()
    try:
        provider.process_frame(np.zeros((2, 2, 3), dtype=np.uint8))
        assert first_started.wait(timeout=1.0)
        for value in range(1, 6):
            provider.process_frame(
                np.full((2, 2, 3), value, dtype=np.uint8)
            )
        release_first.set()
        deadline = time.monotonic() + 1.0
        while provider._inferred_frame_count < 2 and time.monotonic() < deadline:
            time.sleep(0.005)

        assert inferred_values == [0, 4]
        assert provider._received_frame_count == 6
        assert provider._inference_candidate_count == 3
        assert provider._inferred_frame_count == 2
        assert provider._replaced_pending_frame_count == 1
        observation = provider.get_observation()
        assert observation["frame_value"] == 4
        assert observation["header"]["frame_id"] == "camera_link"
        assert observation["header"]["stamp"] > 0.0
    finally:
        release_first.set()
        provider.stop()


def test_pose_model_variant_selects_configured_full_model() -> None:
    provider = VisionObservationProvider({
        "pose_model_variant": "full",
        "pose_models": {
            "lite": "models/pose_landmarker_lite.task",
            "full": "models/pose_landmarker_full.task",
        },
    })
    assert provider._pose_model_variant == "full"
    assert provider._mediapipe_model.endswith(
        "pose_landmarker_full.task"
    )


def test_video_landmarker_uses_strict_monotonic_timestamps() -> None:
    provider = VisionObservationProvider({
        "landmarker_running_mode": "video",
    })
    landmarker = _FakeLandmarker()
    first_timestamp = provider._next_landmarker_timestamp()
    second_timestamp = provider._next_landmarker_timestamp()
    assert second_timestamp > first_timestamp
    assert provider._run_landmarker(
        landmarker, "frame", second_timestamp
    ) == "video-result"
    assert landmarker.calls == [("video", "frame", second_timestamp)]


def test_landmarker_ab_metrics_include_pose_quality_and_latency() -> None:
    provider = VisionObservationProvider({
        "pose_model_variant": "lite",
        "mediapipe_model": "models/pose_landmarker_lite.task",
    })
    provider._landmarker_times.extend((10.0, 10.1, 10.2))
    provider._pipeline_latency_ms.extend((20.0, 22.0, 24.0))
    provider._pose_latency_ms.extend((10.0, 12.0, 14.0))
    provider._hand_latency_ms.extend((5.0, 6.0, 7.0))
    provider._hand_detected.extend((1.0, 0.0, 1.0))
    provider._record_pose_quality([{
        "confidence": 0.9,
        "keypoints": [
            {
                "id": index,
                "confidence": 0.9 if index != 16 else 0.2,
                "presence": 0.9,
            }
            for index in range(33)
        ],
    }])
    diagnostics = provider._landmarker_diagnostics()
    assert diagnostics["pose_model_variant"] == "lite"
    assert diagnostics["running_mode"] == "video"
    assert diagnostics["effective_inference_fps"] == 10.0
    assert diagnostics["pose"]["detection_rate"] == 1.0
    assert diagnostics["pose"]["keypoint_valid_ratio"] == round(
        32 / 33, 3
    )
    assert diagnostics["pose"]["critical_keypoint_valid_ratio"] < 1.0


def test_hand_landmarker_probes_slowly_until_a_hand_is_active() -> None:
    provider = VisionObservationProvider({
        "hand_idle_inference_stride": 3,
        "hand_active_hold_inferences": 2,
    })
    assert [provider._hand_inference_is_due() for _ in range(4)] == [
        True,
        False,
        False,
        True,
    ]
    provider._hand_active_remaining = 2
    assert provider._hand_inference_is_due()


def test_gesture_debug_topic_keeps_exact_engine_labels() -> None:
    publisher = _Publisher()
    fake_node = SimpleNamespace(_gesture_debug_pub=publisher)
    VisionInteractionNode._publish_gesture_debug(fake_node, {
        "active_target": {
            "track_id": 8,
            "tracking_state": "tracking",
            "pose_state": "standing",
            "pose_action": "arm_raise_wave",
        },
        "hands": [{"hand_action": "stop_gesture"}],
        "_gesture_diagnostics": {
            "primary_action": "victory",
            "recognized_actions": [{"name": "victory"}],
            "raw_scores": [{"name": "victory", "score": 0.91}],
        },
    })
    payload = json.loads(publisher.messages[-1].data)
    assert payload["track_id"] == 8
    assert payload["pose_state"] == "standing"
    assert payload["primary_action"] == "victory"
    assert payload["legacy_pose_action"] == "arm_raise_wave"
    assert payload["legacy_hand_actions"] == ["stop_gesture"]


def test_object_detector_honors_object_params_without_synthetic_fallback() -> None:
    detector = ObjectDetectorProvider({
        "object_rknn_model": "models/object",
        "det_threshold": 0.6,
    })
    detector.available = True
    detector._loaded = True
    captured = {}

    def inference(frame, threshold):
        captured["threshold"] = threshold
        return []

    detector._run_inference = inference
    assert detector.detect_objects(
        np.zeros((10, 10, 3), dtype=np.uint8),
        {"confidence": 0.25},
    ) == []
    assert captured["threshold"] == 0.25
    assert detector.last_error == ""

    assert detector.detect_objects(None, {}) == []
    assert detector.last_error == "camera frame unavailable or stale"

    explicit_mock = ObjectDetectorProvider({"mock_mode": True})
    explicit_mock.start()
    assert explicit_mock.detect_objects(None, {})[0]["label"] == "dog toy ball"


def test_object_detector_filters_requested_labels_after_inference() -> None:
    detector = ObjectDetectorProvider({"object_model": "models/object"})
    detector.available = True
    detector._loaded = True
    detector._run_inference = lambda frame, threshold: [
        {"label": "Dog Toy Ball", "confidence": 0.8},
        {"label": "dog food can", "confidence": 0.9},
    ]

    objects = detector.detect_objects(
        np.zeros((10, 10, 3), dtype=np.uint8),
        {"target_labels": ["dog toy ball"]},
    )

    assert objects == [{"label": "Dog Toy Ball", "confidence": 0.8}]


def test_object_detection_session_is_leased_owned_and_rate_limited() -> None:
    manager = ObjectDetectionSessionManager(
        default_rate_hz=2.0,
        max_rate_hz=5.0,
        default_lease_sec=3.0,
    )
    assert manager.poll(now=10.0)["state"] == "inactive"

    started = manager.configure({
        "enabled": True,
        "session_id": "find-001",
        "rate_hz": 2.0,
        "confidence": 0.25,
        "target_labels": ["dog toy ball", "Dog Toy Ball"],
        "lease_sec": 3.0,
    }, now=10.0)
    assert started["ok"] is True
    assert started["stream"]["target_labels"] == ["dog toy ball"]
    due = manager.poll(now=10.0)
    assert due["state"] == "due"
    assert due["params"] == {
        "confidence": 0.25,
        "target_labels": ["dog toy ball"],
    }
    assert manager.poll(now=10.49)["state"] == "waiting"
    assert manager.poll(now=10.5)["state"] == "due"

    conflict = manager.configure({
        "enabled": False,
        "session_id": "another-task",
    }, now=10.6)
    assert conflict["ok"] is False
    assert conflict["stream"]["session_id"] == "find-001"

    renewed = manager.configure({
        "enabled": True,
        "session_id": "find-001",
        "lease_sec": 3.0,
    }, now=12.0)
    assert renewed["ok"] is True
    assert renewed["stream"]["target_labels"] == ["dog toy ball"]
    assert renewed["stream"]["confidence"] == 0.25
    assert manager.poll(now=14.99)["state"] in {"due", "waiting"}
    expired = manager.poll(now=15.0)
    assert expired["state"] == "expired"
    assert expired["stream"]["session_id"] == "find-001"
    assert manager.snapshot(now=15.0)["active"] is False


def test_object_detector_uses_ultralytics_predict_and_results_boxes() -> None:
    detector = ObjectDetectorProvider({
        "object_model": "models/object",
        "det_threshold": 0.6,
        "nms_threshold": 0.2,
        "max_detections": 10,
        "image_size": 640,
    })
    detector.available = True
    detector._loaded = True
    captured = {}
    boxes = SimpleNamespace(
        xyxyn=np.array([[0.4, 0.325, 0.6, 0.425]], dtype=np.float32),
        conf=np.array([0.9], dtype=np.float32),
        cls=np.array([7], dtype=np.float32),
    )

    def predict(**kwargs):
        captured.update(kwargs)
        return [SimpleNamespace(boxes=boxes, names={7: "dog food can"})]

    detector._model = SimpleNamespace(predict=predict)
    frame = np.zeros((360, 480, 3), dtype=np.uint8)
    objects = detector.detect_objects(frame, {"confidence": 0.5})

    assert captured.pop("source") is frame
    assert captured == {
        "conf": 0.5,
        "iou": 0.2,
        "max_det": 10,
        "imgsz": 640,
        "save": False,
        "verbose": False,
    }
    assert objects == [{
        "label": "dog food can",
        "x": 0.4,
        "y": 0.325,
        "w": 0.2,
        "h": 0.1,
        "confidence": 0.9,
        "center_x": 0.5,
        "center_y": 0.375,
    }]


def test_object_detector_handles_ultralytics_result_without_boxes() -> None:
    detector = ObjectDetectorProvider({})
    result = SimpleNamespace(boxes=None, names={})

    assert detector._results_to_objects([result]) == []
    assert detector._results_to_objects([]) == []


def test_object_result_is_cached_and_published_with_freshness_metadata() -> None:
    publisher = _Publisher()
    fake_node = SimpleNamespace(
        _state_lock=threading.Lock(),
        _object_sequence=0,
        _vision_epoch="vision-test",
        _latest_camera_frame_id="camera_color_optical_frame",
        _latest_objects=[],
        _latest_objects_monotonic=0.0,
        _object_pub=publisher,
    )
    objects = [{
        "label": "dog toy ball",
        "x": 0.2,
        "y": 0.3,
        "w": 0.1,
        "h": 0.1,
        "confidence": 0.9,
    }]

    tracked = VisionInteractionNode._record_object_result(
        fake_node,
        objects,
        source="stream",
        status="ok",
        latency_ms=42.5,
    )

    payload = json.loads(publisher.messages[-1].data)
    assert payload["schema_version"] == 2
    assert payload["header"]["frame_id"] == "camera_color_optical_frame"
    assert payload["published_at"] >= payload["header"]["stamp"]
    assert payload["sequence"] == 1
    assert payload["source"] == "stream"
    assert payload["status"] == "ok"
    assert payload["stream"]["active"] is False
    assert payload["request"] == {}
    assert payload["stop_reason"] == ""
    assert payload["inference_latency_ms"] == 42.5
    assert payload["objects"] == tracked
    assert tracked[0]["target_id"] == "vision-test:object:1"
    assert tracked[0]["track_id"] == 1
    assert tracked[0]["tracking_state"] == "tracking"
    assert tracked[0]["range_valid"] is False
    assert tracked[0]["distance_m"] is None
    assert fake_node._latest_objects == tracked
    assert fake_node._latest_objects_monotonic > 0.0


def test_object_result_uses_aligned_depth_for_metric_approach() -> None:
    publisher = _Publisher()
    stamp = 100.0
    depth = np.full((20, 20), 2.0, dtype=np.float32)
    fake_node = SimpleNamespace(
        _state_lock=threading.Lock(),
        _object_sequence=0,
        _vision_epoch="vision-depth",
        _latest_camera_frame_id="camera_color_optical_frame",
        _latest_objects=[],
        _latest_objects_monotonic=0.0,
        _object_pub=publisher,
        _depth_enabled=True,
        _latest_depth_m=depth,
        _latest_depth_stamp=stamp,
        _latest_depth_monotonic=time.monotonic(),
        _latest_depth_frame_id="camera_color_optical_frame",
        _camera_intrinsics={
            "fx": 100.0,
            "fy": 100.0,
            "cx": 9.5,
            "cy": 9.5,
            "width": 20,
            "height": 20,
            "frame_id": "camera_color_optical_frame",
        },
        _depth_stale_timeout_sec=0.5,
        _depth_sync_tolerance_sec=0.1,
        _depth_min_m=0.2,
        _depth_max_m=8.0,
        _depth_sample_radius_px=2,
        _depth_min_valid_samples=5,
        _depth_min_valid_fraction=0.2,
    )

    tracked = VisionInteractionNode._record_object_result(
        fake_node,
        [{
            "label": "cat",
            "x": 0.1,
            "y": 0.1,
            "w": 0.8,
            "h": 0.8,
            "confidence": 0.9,
        }],
        source="stream",
        status="ok",
        latency_ms=10.0,
        observation_stamp=stamp,
        frame_id="camera_color_optical_frame",
    )

    assert tracked[0]["target_type"] == "animal"
    assert tracked[0]["range_valid"] is True
    assert 1.99 <= tracked[0]["distance_m"] <= 2.01
    payload = json.loads(publisher.messages[-1].data)
    assert payload["objects"][0]["range_source"] == "aligned_depth"


def test_stopping_object_stream_publishes_terminal_and_clears_cache() -> None:
    publisher = _Publisher()
    manager = ObjectDetectionSessionManager()
    assert manager.configure({
        "enabled": True,
        "session_id": "find-002",
        "lease_sec": 3.0,
    })["ok"]
    fake_node = SimpleNamespace(
        _object_stream=manager,
        _object_inference_lock=threading.Lock(),
        _state_lock=threading.Lock(),
        _object_sequence=0,
        _latest_camera_frame_id="camera_link",
        _latest_objects=[{"label": "dog toy ball"}],
        _latest_objects_monotonic=time.monotonic(),
        _object_tracks={1: {"target_id": "epoch:object:1"}},
        _object_pub=publisher,
    )
    fake_node._record_object_result = MethodType(
        VisionInteractionNode._record_object_result,
        fake_node,
    )

    result = VisionInteractionNode._set_object_detection(fake_node, {
        "enabled": False,
        "session_id": "find-002",
    })

    assert result["ok"] is True
    payload = json.loads(publisher.messages[-1].data)
    assert payload["source"] == "control"
    assert payload["status"] == "stopped"
    assert payload["stop_reason"] == "requested"
    assert payload["stream"]["active"] is False
    assert payload["stream"]["session_id"] == "find-002"
    assert fake_node._latest_objects == []
    assert fake_node._object_tracks == {}


def test_object_stream_skips_an_occupied_inference_slot() -> None:
    inference_lock = threading.Lock()
    inference_lock.acquire()
    fake_node = SimpleNamespace(
        _providers={"object": SimpleNamespace()},
        _object_inference_lock=inference_lock,
    )
    try:
        result = VisionInteractionNode._run_object_detection(
            fake_node,
            {},
            source="stream",
            wait_for_slot=False,
        )
    finally:
        inference_lock.release()

    assert result["ok"] is False
    assert result["busy"] is True


@pytest.mark.parametrize("detector_result", [None, {}, [None], [{}, None]])
def test_malformed_detector_response_is_unknown_for_toy_state(
    monkeypatch, detector_result,
) -> None:
    state = ToyPresenceEventState(
        ToyPresenceEventConfig(), source_freshness_sec=0.75,
    )
    toy = {
        "label": "dog toy ball", "confidence": 0.8,
        "x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1,
    }
    for sequence, at in enumerate((10.0, 10.5, 11.0, 11.5), 1):
        snapshot = state.update({
            "vision_epoch": "toy-shape-epoch",
            "source_observation_id": f"frame-{sequence}",
            "source_observation_monotonic": at,
            "status": "ok",
            "objects": [toy] if at < 11.5 else [],
            "target_labels_valid": True,
            "target_labels": [],
        }, now=at)
    assert snapshot.active
    event_id = snapshot.event_id
    monkeypatch.setattr(vision_node_module.time, "monotonic", lambda: 12.0)
    monkeypatch.setattr(
        vision_node_module, "vision_trace", lambda *_args, **_fields: None
    )
    publisher = _Publisher()
    fake_node = SimpleNamespace(
        _providers={"object": SimpleNamespace(
            detect_objects=lambda _frame, _params: detector_result,
            last_error="",
        )},
        _object_inference_lock=threading.Lock(),
        _state_lock=threading.Lock(),
        _object_sequence=0,
        _vision_epoch="toy-shape-epoch",
        _latest_camera_frame_id="camera_link",
        _latest_objects=[],
        _latest_objects_monotonic=0.0,
        _object_tracks={},
        _toy_presence_event_state=state,
        _object_pub=publisher,
        _frame_for_tasks_with_metadata=lambda: (None, 1012.0, "camera_link", 12.0),
        _object_request_metadata=lambda _params: {},
    )
    fake_node._record_object_result = MethodType(
        VisionInteractionNode._record_object_result, fake_node,
    )

    result = VisionInteractionNode._run_object_detection(
        fake_node, {}, source="stream", wait_for_slot=False,
    )

    assert result["ok"] is False
    assert result["error"] == "object detector returned malformed detections"
    assert json.loads(publisher.messages[-1].data)["status"] == "error"
    assert state.snapshot().event_id == event_id
    # An error clears the pending negative interval instead of advancing it.
    for sequence, at in enumerate((12.5, 13.0, 13.5), 6):
        after_error = state.update({
            "vision_epoch": "toy-shape-epoch",
            "source_observation_id": f"frame-{sequence}",
            "source_observation_monotonic": at,
            "status": "ok",
            "objects": [],
            "target_labels_valid": True,
            "target_labels": [],
        }, now=at)
        assert after_error.active
        assert after_error.event_id == event_id


def test_debug_viewer_consumes_periodic_object_topic() -> None:
    fake_viewer = SimpleNamespace(
        _lock=threading.Lock(),
        _debug_objects=[],
        _debug_objects_monotonic=0.0,
        _object_task={},
    )
    message = SimpleNamespace(data=json.dumps({
        "status": "ok",
        "inference_latency_ms": 37.0,
        "objects": [{"label": "dog", "confidence": 0.8}],
        "error": "",
    }))

    VisionDebugViewerNode._on_objects(fake_viewer, message)

    assert fake_viewer._debug_objects == [
        {"label": "dog", "confidence": 0.8}
    ]
    assert fake_viewer._object_task["success"] is True
    assert fake_viewer._object_task["latency_ms"] == 37.0


class _FaceDetector:
    def setInputSize(self, size) -> None:
        self.size = size

    def detect(self, frame):
        detection = np.zeros((1, 15), dtype=np.float32)
        detection[0, :4] = (1.0, 1.0, 10.0, 10.0)
        detection[0, 4:14] = (3, 3, 8, 3, 5, 5, 3, 8, 8, 8)
        detection[0, -1] = 0.99
        return None, detection


def test_face_enrollment_completion_is_terminal_and_names_are_safe(tmp_path) -> None:
    set_storage_root(tmp_path)
    manager = FaceEnrollmentManager({"quality": {
        "min_face_size_px": 1, "min_brightness": 0, "min_blur_score": 0,
    }})
    manager.set_face_detector(_FaceDetector())
    assert not manager.start_face("../outside")["ok"]
    assert not manager.delete_face("../outside")["ok"]
    assert not manager.start_face("测试用户")["ok"]

    assert manager.start_face("owner", required_shots=1)["ok"]
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    manager.process_face_frame(frame)
    manager.process_face_frame(frame)
    result = manager.process_face_frame(frame)
    assert result["done"] is True
    assert manager.face_session is None
    registry = json.loads((tmp_path / "face_registry.json").read_text())
    assert registry["faces"]["owner"]["paths"] == [
        "faces/owner/001.jpg"
    ]
    assert manager.get_face_paths("owner") == [
        str(tmp_path / "faces" / "owner" / "001.jpg")
    ]


def test_face_enrollment_default_collects_three_continuous_shots(tmp_path) -> None:
    set_storage_root(tmp_path)
    manager = FaceEnrollmentManager()
    result = manager.start_face("owner")
    assert result["total_steps"] == 3
    assert result["pose"] == "continuous"
    assert manager.face_session is not None
    assert manager.face_session.poses == ["continuous"] * 3


def test_face_recognition_keeps_and_matches_multiple_templates(monkeypatch) -> None:
    timing_traces = []
    monkeypatch.setattr(
        face_recognition_module,
        "vision_timing_trace",
        lambda **fields: timing_traces.append(fields),
    )
    provider = FaceRecognitionProvider({"match_threshold": 0.5})
    embeddings = iter([
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
    ])
    provider._extract_embedding = lambda _image: next(embeddings)
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    assert provider.enroll(image, "owner")["success"]
    assert provider.enroll(image, "owner")["success"]
    assert provider.enrolled_count == 1
    result = provider.recognize(image)
    assert result["matched"] is True
    assert result["user_id"] == "owner"
    assert result["confidence"] == 1.0
    assert timing_traces[-1]["module"] == "face_recognition"
    assert timing_traces[-1]["stage"] == "sface_task_recognize"
    assert timing_traces[-1]["reason_code"] == "matched"


def test_master_pose_event_requires_confirmed_known_identity() -> None:
    base = {
        "faces": [{"recognized_user": "owner"}],
        "hands": [],
        "active_target": {
            "identity": "owner",
            "identity_state": "candidate_known",
            "tracking_state": "tracking",
            "pose_action": "arm_raise_wave",
        },
    }
    assert VisionInteractionNode._derive_events(base) == ["EVT_VISION_MASTER"]

    confirmed = {
        **base,
        "active_target": {
            **base["active_target"],
            "identity_state": "confirmed_known",
        },
    }
    assert VisionInteractionNode._derive_events(confirmed) == [
        "EVT_VISION_MASTER",
        "EVT_VISION_MASTER_HAPPY",
    ]


def test_victory_hand_publishes_happy_only_after_identity_confirmation() -> None:
    candidate = {
        "faces": [],
        "hands": [{"hand_action": "victory"}],
        "active_target": {
            "identity": "owner",
            "identity_state": "candidate_known",
            "tracking_state": "tracking",
            "pose_action": "",
        },
    }
    assert VisionInteractionNode._derive_events(candidate) == []

    confirmed = {
        **candidate,
        "active_target": {
            **candidate["active_target"],
            "identity_state": "confirmed_known",
        },
    }
    assert VisionInteractionNode._derive_events(confirmed) == [
        "EVT_VISION_MASTER_HAPPY"
    ]


def test_all_pose_events_allow_confirmed_stranger_identity() -> None:
    unrecognized = {
        "faces": [{"recognized_user": ""}],
        "hands": [{"hand_action": "stop_gesture"}],
        "active_target": {
            "identity": "unknown",
            "identity_state": "confirmed_unknown",
            "tracking_state": "tracking",
            "pose_action": "fallen_down",
        },
    }
    assert VisionInteractionNode._derive_events(unrecognized) == [
        "EVT_VISION_FALL",
        "EVT_VISION_STOP_GESTURE",
    ]

    candidate_owner = {
        **unrecognized,
        "faces": [],
        "active_target": {
            **unrecognized["active_target"],
            "identity": "owner",
            "identity_state": "candidate_known",
        },
    }
    assert VisionInteractionNode._derive_events(candidate_owner) == []

    confirmed_owner = {
        **candidate_owner,
        "active_target": {
            **candidate_owner["active_target"],
            "identity_state": "confirmed_known",
        },
    }
    assert VisionInteractionNode._derive_events(confirmed_owner) == [
        "EVT_VISION_FALL",
        "EVT_VISION_STOP_GESTURE",
    ]

    confirmed_family = {
        **confirmed_owner,
        "active_target": {
            **confirmed_owner["active_target"],
            "identity": "family_member_4",
        },
    }
    assert VisionInteractionNode._derive_events(confirmed_family) == [
        "EVT_VISION_FALL",
        "EVT_VISION_STOP_GESTURE",
    ]

    ordinary_family_pose = {
        **confirmed_family,
        "hands": [],
        "active_target": {
            **confirmed_family["active_target"],
            "pose_action": "arm_raise_wave",
        },
    }
    assert VisionInteractionNode._derive_events(ordinary_family_pose) == [
        "EVT_VISION_MASTER_HAPPY",
    ]

    temporarily_lost_owner = {
        **confirmed_owner,
        "active_target": {
            **confirmed_owner["active_target"],
            "tracking_state": "temporarily_lost",
        },
    }
    assert VisionInteractionNode._derive_events(temporarily_lost_owner) == []

    legacy_identity = {
        **confirmed_owner,
        "active_target": {
            **confirmed_owner["active_target"],
            "identity": "legacy_name",
        },
    }
    assert VisionInteractionNode._derive_events(legacy_identity) == []


def test_held_toy_keeps_pose_data_without_bypassing_stable_toy_state() -> None:
    object_only = {
        "faces": [],
        "hands": [],
        "tracked_objects": [{"label": "dog toy ball"}],
        "active_target": {
            "identity": "unknown",
            "identity_state": "confirmed_unknown",
            "tracking_state": "tracking",
            "pose_action": "",
        },
    }
    assert VisionInteractionNode._derive_events(object_only) == []

    holding_toy = {
        **object_only,
        "faces": [{"recognized_user": "owner"}],
        "active_target": {
            **object_only["active_target"],
            "identity": "owner",
            "identity_state": "confirmed_known",
            "pose_action": "holding_toy",
        },
    }
    assert VisionInteractionNode._derive_events(holding_toy) == [
        "EVT_VISION_MASTER",
    ]
    holding_food = {
        **holding_toy,
        "active_target": {
            **holding_toy["active_target"],
            "pose_action": "holding_dog_food",
        },
    }
    assert VisionInteractionNode._derive_events(holding_food) == [
        "EVT_VISION_MASTER",
        "EVT_VISION_FOOD",
    ]


def test_existing_two_hz_held_stream_feeds_one_stable_toy_event(
    monkeypatch,
) -> None:
    monotonic_values = iter((10.0, 10.5, 11.0))
    monkeypatch.setattr(
        vision_node_module.time,
        "monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(
        VisionInteractionNode,
        "_fuse_human_depth",
        staticmethod(lambda _self, _objects, *, observation_stamp: None),
        raising=False,
    )
    monkeypatch.setattr(
        vision_node_module, "vision_trace", lambda *_args, **_fields: None
    )

    publisher = _Publisher()
    state = ToyPresenceEventState(
        ToyPresenceEventConfig.from_mapping(None),
        source_freshness_sec=0.75,
        result_max_age_sec=2.0,
    )
    fake_node = SimpleNamespace(
        _state_lock=threading.Lock(),
        _object_sequence=0,
        _vision_epoch="held-toy-epoch",
        _latest_camera_frame_id="camera_color_optical_frame",
        _latest_objects=[],
        _latest_objects_monotonic=0.0,
        _object_tracks={},
        _next_object_track_id=1,
        _object_target_persistence_sec=2.0,
        _toy_presence_event_state=state,
        _object_pub=publisher,
    )
    toy = {
        "label": "dog toy ball",
        "x": 0.2,
        "y": 0.3,
        "w": 0.1,
        "h": 0.1,
        "confidence": 0.21,
    }
    for sequence in range(3):
        VisionInteractionNode._record_object_result(
            fake_node,
            [toy],
            source="stream",
            status="ok",
            latency_ms=10.0,
            observation_stamp=1000.0 + sequence * 0.5,
            frame_id="camera_color_optical_frame",
            source_monotonic=10.0 + sequence * 0.5,
            request={"target_labels": list(HELD_OBJECT_LABELS)},
            toy_target_labels=list(HELD_OBJECT_LABELS),
        )

    state_snapshot = state.snapshot()
    assert state_snapshot.active is True
    assert state_snapshot.transition == "HOLD"
    visual = {
        "events": ["EVT_VISION_MASTER"],
        "event_instances": {"EVT_VISION_MASTER": {"event_id": "human-1"}},
        "active_target": {
            "held_object": {
                "state": "confirmed",
                "action": "holding_toy",
                "object_label": "dog toy ball",
            },
            "pose_action": "holding_toy",
        },
    }
    merged = vision_node_module._apply_toy_presence_event_state(
        visual,
        state,
    )
    assert "EVT_VISION_TOY" in merged["events"]
    assert merged["event_instances"]["EVT_VISION_TOY"]["event_id"] == (
        state_snapshot.event_id
    )
    assert merged["event_instances"]["EVT_VISION_MASTER"]["event_id"] == (
        "human-1"
    )
    assert merged["active_target"]["held_object"]["object_label"] == (
        "dog toy ball"
    )


def test_held_object_pose_updates_only_matching_person_and_preserves_fall() -> None:
    event = {
        "active_target": {
            "target_id": "epoch:human:7",
            "track_id": 7,
            "pose_action": "neutral_stand_sit",
        },
        "human_candidates": [
            {"target_id": "epoch:human:7", "pose_action": ""},
            {"target_id": "epoch:human:8", "pose_action": ""},
        ],
        "humans": [
            {"track_id": 7, "pose_action": ""},
            {"track_id": 8, "pose_action": ""},
        ],
    }
    status = HeldObjectPoseStatus(
        state="confirmed",
        action="holding_toy",
        action_label="手持玩具",
        candidate_action="holding_toy",
        object_label="dog toy ball",
        object_track_id=3,
        hand_source="pose_left_wrist",
        association_score=0.9,
        wrist_distance_ratio=0.01,
    )
    VisionInteractionNode._apply_held_object_pose(event, status)

    assert event["active_target"]["pose_action"] == "holding_toy"
    assert event["human_candidates"][0]["pose_action"] == "holding_toy"
    assert event["human_candidates"][1]["pose_action"] == ""
    assert event["humans"][0]["pose_action"] == "holding_toy"
    assert event["humans"][1]["pose_action"] == ""
    assert event["active_target"]["held_object"]["object_track_id"] == 3

    event["active_target"]["pose_action"] = "fallen_down"
    VisionInteractionNode._apply_held_object_pose(event, status)
    assert event["active_target"]["pose_action"] == "fallen_down"


def test_human_visibility_controls_preemptible_held_object_stream() -> None:
    manager = ObjectDetectionSessionManager(
        default_rate_hz=2.0,
        max_rate_hz=5.0,
        default_lease_sec=5.0,
        max_lease_sec=30.0,
    )
    node = SimpleNamespace(
        _held_object_stream=manager,
        _held_object_enabled=True,
        _providers={"object": SimpleNamespace(
            is_available=lambda: True
        )},
        _held_object_session_id="vision-human-holding",
        _held_object_rate_hz=2.0,
        _held_object_confidence=0.35,
        _held_object_last_human_at=0.0,
        _held_object_absence_grace_sec=2.0,
    )
    visible = {
        "active_target": {
            "tracking_state": "tracking",
            "confidence": 0.9,
        },
    }
    VisionInteractionNode._update_held_object_stream(node, visible, 10.0)
    snapshot = manager.snapshot(now=10.0)
    assert snapshot["active"] is True
    assert snapshot["session_id"] == "vision-human-holding"
    assert snapshot["rate_hz"] == 2.0

    lost = {"active_target": {"tracking_state": "temporarily_lost"}}
    VisionInteractionNode._update_held_object_stream(node, lost, 11.9)
    assert manager.snapshot(now=11.9)["active"] is True
    VisionInteractionNode._update_held_object_stream(node, lost, 12.0)
    assert manager.snapshot(now=12.0)["active"] is False


def test_human_loss_publishes_automatic_stream_terminal_state() -> None:
    context = ObjectDetectionSessionManager(default_lease_sec=5.0)
    external = ObjectDetectionSessionManager(default_lease_sec=5.0)
    records = []
    node = SimpleNamespace(
        _held_object_stream=context,
        _object_stream=external,
        _held_object_enabled=True,
        _providers={"object": SimpleNamespace(is_available=lambda: True)},
        _held_object_session_id="vision-human-holding",
        _held_object_rate_hz=2.0,
        _held_object_confidence=0.35,
        _held_object_last_human_at=10.0,
        _held_object_absence_grace_sec=2.0,
        _record_object_result=lambda objects, **kwargs: records.append(
            (objects, kwargs)
        ),
    )
    context.configure({
        "enabled": True,
        "session_id": "vision-human-holding",
        "lease_sec": 5.0,
    }, now=10.0)

    VisionInteractionNode._update_held_object_stream(
        node,
        {"active_target": {"tracking_state": "temporarily_lost"}},
        12.0,
    )

    assert context.snapshot(now=12.0)["active"] is False
    assert len(records) == 1
    assert records[0][1]["status"] == "stopped"
    assert records[0][1]["stop_reason"] == "human_absent"
    assert records[0][1]["stream"]["active"] is False


def test_object_state_keeps_automatic_stream_separate_from_external_owner() -> None:
    external = ObjectDetectionSessionManager(default_lease_sec=5.0)
    context = ObjectDetectionSessionManager(default_lease_sec=5.0)
    context.configure({
        "enabled": True,
        "session_id": "vision-human-holding",
        "lease_sec": 5.0,
    })
    node = SimpleNamespace(
        _object_stream=external,
        _held_object_stream=context,
        _providers={},
    )

    result = VisionInteractionNode._run_task(
        node,
        "get_object_detection_state",
        {},
    )

    assert result["stream"]["active"] is False
    assert result["automatic_stream"]["active"] is True
    assert result["automatic_stream"]["session_id"] == "vision-human-holding"


def test_explicit_object_stream_runs_before_held_pose_stream() -> None:
    explicit = ObjectDetectionSessionManager()
    context = ObjectDetectionSessionManager()
    now = time.monotonic()
    explicit.configure({
        "enabled": True,
        "session_id": "action-find-toy",
        "lease_sec": 3.0,
    }, now=now)
    context.configure({
        "enabled": True,
        "session_id": "vision-human-holding",
        "lease_sec": 3.0,
    }, now=now)
    calls = []
    node = SimpleNamespace(
        _object_stream=explicit,
        _held_object_stream=context,
        _run_object_detection=lambda params, **kwargs: (
            calls.append((params, kwargs)) or {"ok": True}
        ),
    )

    # Both streams are immediately due, but the externally owned Action stream
    # is authoritative and consumes the only inference slot.
    VisionInteractionNode._poll_objects(node)
    assert len(calls) == 1
    assert calls[0][1]["stream"]["session_id"] == "action-find-toy"


def test_visual_state_log_reports_gate_and_deduplicates(monkeypatch) -> None:
    messages = []
    monkeypatch.setattr(
        vision_node_module.logger,
        "info",
        lambda message, *args: messages.append(message % args),
    )
    node = SimpleNamespace(_last_visual_log_signature=None)
    event = {
        "active_target": {
            "track_id": 7,
            "tracking_state": "tracking",
            "identity": "owner",
            "identity_state": "candidate_known",
            "pose_action": "arm_raise_wave",
        },
        "hands": [],
        "events": ["EVT_VISION_MASTER"],
    }
    VisionInteractionNode._log_visual_event_state(node, event)
    VisionInteractionNode._log_visual_event_state(node, event)
    assert len(messages) == 1
    assert "identity_state=candidate_known" in messages[0]
    assert "pose_event_gate=blocked" in messages[0]
    assert "events=EVT_VISION_MASTER" in messages[0]

    event["active_target"]["identity_state"] = "confirmed_known"
    event["events"].append("EVT_VISION_MASTER_HAPPY")
    VisionInteractionNode._log_visual_event_state(node, event)
    assert len(messages) == 2
    assert "pose_event_gate=open" in messages[1]
    assert "EVT_VISION_MASTER_HAPPY" in messages[1]


def test_visual_state_trace_reports_publish_and_suppression(monkeypatch) -> None:
    traces = []
    monkeypatch.setattr(
        vision_node_module,
        "vision_trace",
        lambda record, **fields: traces.append((record, fields)),
    )
    node = SimpleNamespace(
        _last_visual_log_signature=None,
        _last_traced_events=(),
    )
    event = {
        "vision_epoch": "epoch-1",
        "sequence": 17,
        "snapshot_id": "epoch-1:17",
        "active_target": {
            "track_id": 7,
            "tracking_state": "tracking",
            "identity": "owner",
            "identity_state": "candidate_known",
            "pose_action": "stop_gesture",
        },
        "hands": [],
        "events": [],
    }
    VisionInteractionNode._log_visual_event_state(node, event)
    assert traces[-1][0] == "event_suppressed"
    assert traces[-1][1]["reason_code"] == "identity_not_confirmed"

    event["active_target"]["identity_state"] = "confirmed_known"
    event["events"] = ["EVT_VISION_STOP_GESTURE"]
    VisionInteractionNode._log_visual_event_state(node, event)
    published = [fields for record, fields in traces if record == "event_publish"]
    assert published[-1]["event_type"] == "EVT_VISION_STOP_GESTURE"
    assert published[-1]["sequence"] == 17
