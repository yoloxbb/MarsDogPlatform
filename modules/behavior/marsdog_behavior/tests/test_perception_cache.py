from __future__ import annotations

import json
import threading
import time

from marsdog_behavior.perception_client_adapter import PerceptionClientAdapter


class _Message:
    def __init__(self, value: dict) -> None:
        self.data = json.dumps(value)


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def debug(self, *args, **kwargs) -> None:
        pass

    def warn(self, message, *args, **kwargs) -> None:
        self.warnings.append(str(message) % args if args else str(message))

    def error(self, message, *args, **kwargs) -> None:
        self.errors.append(str(message) % args if args else str(message))


class _FakeTimer:
    def __init__(self, callback) -> None:
        self._callback = callback
        self.canceled = False

    def cancel(self) -> None:
        self.canceled = True

    def fire(self) -> None:
        if not self.canceled:
            self._callback()


class _FakeNode:
    def __init__(self) -> None:
        self.timers: list[_FakeTimer] = []
        self.destroyed: list[_FakeTimer] = []

    def create_timer(self, _period_sec, callback):
        timer = _FakeTimer(callback)
        self.timers.append(timer)
        return timer

    def destroy_timer(self, timer) -> None:
        self.destroyed.append(timer)


class _FakeFuture:
    def __init__(self) -> None:
        self._callbacks = []
        self._response = None

    def add_done_callback(self, callback) -> None:
        self._callbacks.append(callback)

    def result(self):
        return self._response

    def resolve(self, response) -> None:
        self._response = response
        for callback in list(self._callbacks):
            callback(self)


class _FakeVisionClient:
    def __init__(self) -> None:
        self.future = _FakeFuture()

    def service_is_ready(self) -> bool:
        return True

    def call_async(self, _request):
        return self.future


class _FakeVisionTask:
    class Request:
        def __init__(self) -> None:
            self.task_id = ""
            self.task_type = ""
            self.params_json = ""


class _FakeVisionResponse:
    def __init__(self, result: dict, *, success: bool = True) -> None:
        self.success = success
        self.result_json = json.dumps(result)
        self.error_message = "" if success else "failed"


def _adapter() -> PerceptionClientAdapter:
    adapter = object.__new__(PerceptionClientAdapter)
    adapter._ros2_ready = True
    adapter._logger = _Logger()
    adapter._on_audio_direct = None
    adapter._on_visual_event = None
    adapter._active_direct_visual_events = set()
    adapter._person_present = False
    adapter._active_identity = "unknown"
    adapter._cached_humans = []
    adapter._cached_human_candidates = []
    adapter._cached_objects = []
    adapter._cached_vision_epoch = ""
    adapter._cached_visual_header = {}
    adapter._visual_cache_updated_at = 0.0
    adapter._lock = threading.Lock()
    return adapter


def _audio_command(event_type: str, command_id: str) -> dict:
    return {
        "schema_version": 2,
        "event_type": event_type,
        "interaction_id": "voice-1",
        "utterance_id": "utterance-1",
        "command_id": command_id,
        "specific_event_type": event_type,
        "dispatch_role": "specific_command",
        "should_trigger_behavior_tree": True,
        "slots": [],
    }


def _audio_reaction(event_type: str, social: str) -> dict:
    return {
        **_audio_command(event_type, "CMD_%s" % social),
        "dispatch_role": "social_reaction",
        "social": social,
        "emotion": social,
        "intent": "NONE",
        "action": "NONE",
        "control": "NONE",
        "is_executable": False,
    }


def _service_adapter() -> tuple[
    PerceptionClientAdapter,
    _FakeNode,
    _FakeVisionClient,
]:
    adapter = _adapter()
    node = _FakeNode()
    client = _FakeVisionClient()
    adapter._node = node
    adapter._vision_client = client
    adapter._vision_service_type = _FakeVisionTask
    adapter._vision_service_name = "/perception/vision/task"
    adapter._vision_task_timeout_sec = 2.0
    return adapter, node, client


def test_audio_adapter_accepts_only_concrete_command_namespace() -> None:
    adapter = _adapter()
    received: list[tuple[str, dict]] = []
    adapter.set_on_audio_direct(
        lambda event_type, payload: received.append((event_type, payload))
    )
    concrete = _audio_command("EVT_VOICE_COMMAND_SIT", "CMD_SIT")
    obsolete = _audio_command("EVT_VOICE_INTENT_COMMAND_SIT", "CMD_SIT")

    adapter._on_audio_ros2(_Message(concrete))
    adapter._on_audio_ros2(_Message(obsolete))

    assert [event_type for event_type, _ in received] == [
        "EVT_VOICE_COMMAND_SIT"
    ]


def test_audio_adapter_never_forwards_nickname_social_events_as_commands(
) -> None:
    adapter = _adapter()
    received: list[tuple[str, dict]] = []
    adapter.set_on_audio_direct(
        lambda event_type, payload: received.append((event_type, payload))
    )

    # 非 COMMAND 昵称事件仍被丢弃（喂情绪引擎），不转发为命令。
    event_type = "EVT_VOICE_CALL_NAME"
    adapter._on_audio_ros2(_Message({
        **_audio_command(event_type, "NONE"),
        "social": "CALL",
        "intent": "NONE",
        "control": "NONE",
        "action": "NONE",
        "intent_category": "social",
        # Deliberately drift the authority bits: event identity still wins.
        "is_executable": True,
        "should_trigger_behavior_tree": True,
    }))

    assert received == []


def test_audio_adapter_keeps_command_call_name_social_only() -> None:
    """EVT_VOICE_COMMAND_CALL_NAME remains social-only and is not forwarded."""
    adapter = _adapter()
    received: list[tuple[str, dict]] = []
    adapter.set_on_audio_direct(
        lambda event_type, payload: received.append((event_type, payload))
    )

    event_type = "EVT_VOICE_COMMAND_CALL_NAME"
    adapter._on_audio_ros2(_Message({
        **_audio_command(event_type, "NONE"),
        "social": "CALL",
        "intent": "NONE",
        "control": "NONE",
        "action": "NONE",
        "intent_category": "social",
        "is_executable": False,
        "should_trigger_behavior_tree": False,
    }))

    assert received == []


def test_audio_adapter_forwards_authorized_praise_reaction() -> None:
    adapter = _adapter()
    received: list[tuple[str, dict]] = []
    adapter.set_on_audio_direct(
        lambda event_type, payload: received.append((event_type, payload))
    )
    event_type = "EVT_VOICE_COMMAND_PRAISE"

    adapter._on_audio_ros2(_Message(_audio_reaction(event_type, "PRAISE")))

    assert [event for event, _ in received] == [event_type]


def test_audio_adapter_rejects_legacy_praise_authority() -> None:
    adapter = _adapter()
    received: list[str] = []
    adapter.set_on_audio_direct(lambda event_type, _: received.append(event_type))
    payload = _audio_reaction("EVT_VOICE_COMMAND_PRAISE", "PRAISE")
    payload.update({
        "dispatch_role": "specific_command",
        "should_trigger_behavior_tree": False,
    })

    adapter._on_audio_ros2(_Message(payload))

    assert received == []


def test_audio_adapter_rejects_wrong_schema_and_non_executable_summary() -> None:
    adapter = _adapter()
    received: list[str] = []
    adapter.set_on_audio_direct(lambda event_type, _: received.append(event_type))
    command = _audio_command("EVT_VOICE_COMMAND_SIT", "CMD_SIT")

    adapter._on_audio_ros2(_Message({**command, "schema_version": 1}))
    adapter._on_audio_ros2(_Message({**command, "schema_version": True}))
    adapter._on_audio_ros2(_Message({
        **command,
        "event_type": "EVT_VOICE_INTENT_COMMAND_KNOWN",
        "specific_event_type": "EVT_VOICE_INTENT_COMMAND_SIT",
        "dispatch_role": "semantic_classification",
        "should_trigger_behavior_tree": False,
    }))

    assert received == []


def test_vision_task_timeout_completes_once_and_ignores_late_result() -> None:
    adapter, node, client = _service_adapter()
    results = []

    assert adapter._call_vision_task_async(
        "check_person",
        {},
        results.append,
    )
    [timer] = node.timers
    timer.fire()

    assert results == [None]
    assert timer.canceled
    assert node.destroyed == [timer]
    assert adapter._logger.warnings

    client.future.resolve(_FakeVisionResponse({"present": True}))
    assert results == [None]


def test_vision_task_result_cancels_timeout_and_completes_once() -> None:
    adapter, node, client = _service_adapter()
    results = []

    assert adapter._call_vision_task_async(
        "check_person",
        {},
        results.append,
    )
    [timer] = node.timers
    client.future.resolve(_FakeVisionResponse({"present": True, "count": 1}))

    assert results == [{"present": True, "count": 1}]
    assert timer.canceled
    assert node.destroyed == [timer]

    timer.fire()
    assert results == [{"present": True, "count": 1}]


def test_social_request_timeout_uses_fresh_visual_event_cache() -> None:
    adapter, node, _client = _service_adapter()
    adapter._person_present = True
    adapter._active_identity = "owner"
    adapter._cached_humans = [{"track_id": 7}]
    adapter._visual_cache_updated_at = time.monotonic()
    results = []

    adapter.request_social_target(results.append)
    [timer] = node.timers
    timer.fire()

    assert results == [{
        "route": "human",
        "target": {
            "target_type": "human",
            "target_id": "owner",
            "identity": "owner",
            "count": 1,
        },
    }]


def test_person_cache_expires_when_visual_node_stops_publishing() -> None:
    adapter = _adapter()
    adapter._on_visual_ros2(_Message({
        "schema_version": 1,
        "events": [],
        "humans": [{"track_id": 1, "confidence": 0.9}],
        "active_target": {
            "identity": "owner",
            "tracking_state": "tracking",
            "last_seen_age_ms": 10.0,
        },
    }))
    assert adapter.check_person()["present"] is True

    adapter._visual_cache_updated_at = (
        time.monotonic() - adapter.VISUAL_CACHE_TIMEOUT_SEC - 0.1
    )
    assert adapter.check_person() == {
        "present": False,
        "count": 0,
        "identity": "unknown",
    }
    assert adapter.is_person_present() is False
    assert adapter.get_active_identity() == "unknown"


def test_owner_target_selection_skips_stranger_and_requires_stable_id() -> None:
    candidates = [
        {
            "vision_epoch": "vision-1",
            "target_id": "vision-1:human:2",
            "track_id": 2,
            "identity": "stranger",
        },
        {
            "vision_epoch": "vision-1",
            "target_id": "vision-1:human:7",
            "track_id": 7,
            "identity": "OWNER",
            "identity_state": "confirmed_known",
            "tracking_state": "tracking",
        },
    ]

    assert PerceptionClientAdapter._select_owner_target(candidates) == {
        "target_type": "human",
        "vision_epoch": "vision-1",
        "target_id": "vision-1:human:7",
        "track_id": 7,
        "identity": "owner",
        "identity_state": "confirmed_known",
        "tracking_state": "tracking",
    }
    assert PerceptionClientAdapter._select_owner_target([
        {"identity": "owner", "track_id": 7},
    ]) is None
    assert PerceptionClientAdapter._select_owner_target([{
        **candidates[1], "identity_state": "candidate_known",
    }]) is None
    assert PerceptionClientAdapter._select_owner_target([{
        **candidates[1], "tracking_state": "temporarily_lost",
    }]) is None


def test_temporarily_lost_identity_is_not_a_present_person() -> None:
    adapter = _adapter()
    adapter._on_visual_ros2(_Message({
        "schema_version": 1,
        "events": [],
        "humans": [],
        "active_target": {
            "identity": "owner",
            "is_registered": True,
            "tracking_state": "temporarily_lost",
            "last_seen_age_ms": 600.0,
        },
    }))
    assert adapter.check_person()["present"] is False


def test_direct_visual_events_fire_once_per_appearance() -> None:
    adapter = _adapter()
    received: list[tuple[str, dict]] = []
    adapter.set_on_visual_event(
        lambda event_type, payload: received.append((event_type, payload))
    )
    payload = {
        "schema_version": 1,
        "header": {"stamp": 1786417000.1, "frame_id": "camera_link"},
        "active_target": {"pose_action": "fallen_down"},
        "hands": [{"hand_action": "stop_gesture"}],
        "events": [
            "EVT_VISION_STRANGER",
            "EVT_VISION_FALL",
            "EVT_VISION_STOP_GESTURE",
        ],
    }

    adapter._on_visual_ros2(_Message(payload))
    adapter._on_visual_ros2(_Message(payload))

    assert [event_type for event_type, _ in received] == [
        "EVT_VISION_FALL",
        "EVT_VISION_STOP_GESTURE",
    ]

    adapter._on_visual_ros2(_Message({"schema_version": 1, "events": []}))
    adapter._on_visual_ros2(_Message(payload))
    assert [event_type for event_type, _ in received].count(
        "EVT_VISION_FALL"
    ) == 2


def test_visual_event_rejects_wrong_schema_and_non_string_events() -> None:
    adapter = _adapter()
    received: list[str] = []
    adapter.set_on_visual_event(lambda event_type, _: received.append(event_type))

    adapter._on_visual_ros2(_Message({
        "schema_version": 2,
        "events": ["EVT_VISION_FALL"],
    }))
    adapter._on_visual_ros2(_Message({
        "schema_version": True,
        "events": ["EVT_VISION_FALL"],
    }))
    adapter._on_visual_ros2(_Message({
        "schema_version": 1,
        "events": [{"event_type": "EVT_VISION_STOP_GESTURE"}],
    }))

    assert received == []


def test_direct_visual_event_retriggers_after_stream_timeout() -> None:
    adapter = _adapter()
    received: list[str] = []
    adapter.set_on_visual_event(lambda event_type, _: received.append(event_type))
    payload = {"schema_version": 1, "events": ["EVT_VISION_FALL"]}

    adapter._on_visual_ros2(_Message(payload))
    adapter._visual_cache_updated_at = (
        time.monotonic() - adapter.VISUAL_CACHE_TIMEOUT_SEC - 0.1
    )
    adapter._on_visual_ros2(_Message(payload))

    assert received == ["EVT_VISION_FALL", "EVT_VISION_FALL"]


def test_wake_query_rejects_stale_service_snapshot_and_uses_fresh_cache():
    adapter = _adapter()
    cached = {
        "vision_epoch": "epoch-cache",
        "target_id": "epoch-cache:human:1",
        "target_type": "human",
        "tracking_state": "tracking",
        "last_seen_age_ms": 10.0,
        "detection_confidence": 0.9,
        "bearing_deg": 0.0,
    }
    adapter._cached_human_candidates = [cached]
    adapter._visual_cache_updated_at = time.monotonic()
    def _stale_service(_task_type, _params, callback):
        callback({
            "snapshot_age_ms": 501.0,
            "targets": [{
                **cached,
                "vision_epoch": "epoch-service",
                "target_id": "epoch-service:human:99",
            }],
        })
        return True

    adapter._call_vision_task_async = _stale_service
    selected = []

    adapter.request_wake_speaker(
        selected.append,
        max_snapshot_age_ms=500.0,
    )

    assert selected[0]["target_id"] == "epoch-cache:human:1"
