"""Perception Client Adapter — encapsulates perception system interactions.

Connects the behavior tree to the perception subsystem:

Subscriptions:
  /perception/audio_event  (RELIABLE, depth=10)
    → Whitelist: EVT_VOICE_CALL_NAME and exact EVT_VOICE_COMMAND_<ACTION> events
    → Other audio events (PRAISE, SCOLD, HAPPY, SAD, etc.) are IGNORED —
      they should be consumed by emotion_engine_node, not behavior_tree_node.

  /perception/visual_event  (BEST_EFFORT, depth=5)
    → Caches humans, active_target, and tracked_objects as service fallback.
    → visual_event.events MUST NOT be mapped to behavior candidates.
    → Visual events go through emotion_engine → /emotion/signal_event.

Service Client:
  /perception/vision/task
    → check_person()    — is a person present? → interactive/solo mode
    → detect_objects()  — what objects are visible? → exploration targets

The legacy /perception/perception_task contract is used as a fallback when its
service type is installed. Standalone mode uses MockPerceptionClient.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Optional, Callable

from bionic_dog_bt.visual_context import (
    select_exploration_context,
    select_hunger_context,
    select_social_animal,
)

from .ros2_compat import NodeBase, HAS_ROS2, is_ros2_ready

# ── Direct event types processed by behavior_tree_node ─────────────────
_ALLOWED_AUDIO_EVENTS = {
    "EVT_VOICE_CALL_NAME",
}

# ── Prefix for per-command events (EVT_VOICE_COMMAND_SIT, etc.) ────────
_COMMAND_EVENT_PREFIX = "EVT_VOICE_COMMAND_"

# ── Audio events that should go to emotion_engine, NOT behavior_tree ────
_AUDIO_FOR_EMOTION_ENGINE = {
    "EVT_VOICE_MASTER_ID",
    "EVT_VOICE_STRANGER_ID",
    "EVT_VOICE_PRAISE",
    "EVT_VOICE_SCOLD",
    "EVT_VOICE_HAPPY",
    "EVT_VOICE_SAD",
    "EVT_VOICE_NEUTRAL",
}

# ── Audio lifecycle events consumed by behavior_tree ───────────────────
_AUDIO_STATE_EVENTS = {
    "EVT_STATE_CHANGED",
}


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class PerceptionClientAdapter:
    """Adapts ROS2 perception topics/services for the behavior tree.

    Audio events: event-type-only (CALL_NAME or EVT_VOICE_COMMAND_<ACTION>).
    Visual events: scene cache only, NO direct behavior candidate generation.
    Hunger/Social/Exploration need events query the visual service and use this
    cache only when that service is unavailable.

    Usage:
        adapter = PerceptionClientAdapter(node)
        adapter.set_on_audio_direct(lambda event_type, data: ...)
        adapter.set_on_visual_event(lambda evt, data: ...)  # optional, for logging

        person = adapter.check_person()
        objects = adapter.detect_objects()
    """

    AUDIO_EVENT_TOPIC = "/perception/audio_event"
    VISUAL_EVENT_TOPIC = "/perception/visual_event"
    VISION_SERVICE = "/perception/vision/task"
    LEGACY_PERCEPTION_SERVICE = "/perception/perception_task"
    # /perception/visual_event normally arrives at 10 Hz.  Five missed
    # updates are enough to consider the scene cache offline/stale.
    VISUAL_CACHE_TIMEOUT_SEC = 0.5
    VISUAL_TARGET_MAX_AGE_MS = 500.0

    def __init__(self, node: NodeBase):
        self._node = node
        self._logger = node.get_logger()
        self._ros2_ready = (
            HAS_ROS2
            and is_ros2_ready()
            and getattr(node, "_ros2_ready", True)
        )

        # Callbacks
        self._on_audio_direct: Optional[Callable] = None  # (event_type, data_dict)
        self._on_visual_event: Optional[Callable] = None

        # Cached state from visual_event (service fallback / interaction resolver)
        self._person_present: bool = False
        self._active_identity: str = "unknown"
        self._cached_humans: list[dict] = []
        self._cached_objects: list[dict] = []
        self._visual_cache_updated_at: float = 0.0
        self._lock = threading.Lock()
        self._vision_client = None
        self._vision_service_type = None
        self._vision_service_name = ""

        if self._ros2_ready:
            self._setup_ros2()
        else:
            self._setup_mock()

    # ── ROS2 Setup ───────────────────────────────────────────────────────────

    def _setup_ros2(self):
        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

        audio_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST, depth=10,
        )
        self._node.create_subscription(
            String, self.AUDIO_EVENT_TOPIC, self._on_audio_ros2, audio_qos)

        visual_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST, depth=5,
        )
        self._node.create_subscription(
            String, self.VISUAL_EVENT_TOPIC, self._on_visual_ros2, visual_qos)

        self._setup_vision_service_client()
        self._logger.info(
            "PerceptionClientAdapter: audio_event + visual_event subscriptions ready")

    def _setup_mock(self):
        from bionic_dog_bt.mock_perception_client import MockPerceptionClient
        self._mock_client = MockPerceptionClient()
        self._logger.info(
            "PerceptionClientAdapter: using MockPerceptionClient (standalone mode)")

    def _setup_vision_service_client(self) -> None:
        """Prefer the current vision service and retain legacy compatibility."""
        candidates = (
            (
                "marsdog_vision_interaction.srv",
                "VisionTask",
                self.VISION_SERVICE,
            ),
            (
                "marsdog_interfaces.srv",
                "PerceptionTask",
                self.LEGACY_PERCEPTION_SERVICE,
            ),
            (
                "marsdog_perception.srv",
                "PerceptionTask",
                self.LEGACY_PERCEPTION_SERVICE,
            ),
        )
        for module_name, class_name, service_name in candidates:
            try:
                module = __import__(module_name, fromlist=[class_name])
                service_type = getattr(module, class_name)
                self._vision_client = self._node.create_client(
                    service_type,
                    service_name,
                )
                self._vision_service_type = service_type
                self._vision_service_name = service_name
                self._logger.info(
                    "Vision service client ready: %s (%s.%s)"
                    % (service_name, module_name, class_name)
                )
                return
            except Exception as exc:
                self._logger.debug(
                    "Vision service interface unavailable: %s.%s (%s)"
                    % (module_name, class_name, exc)
                )

        self._logger.warn(
            "No vision service type installed; need-driven visual routing "
            "will use /perception/visual_event cache"
        )

    # ── ROS2 Callbacks ───────────────────────────────────────────────────────

    def _on_audio_ros2(self, msg):
        """Handle /perception/audio_event messages with whitelist filtering.

        Supported events:
          EVT_VOICE_CALL_NAME
          EVT_VOICE_COMMAND_<ACTION>  (e.g. EVT_VOICE_COMMAND_SIT)

        All other audio events are IGNORED — they belong to emotion_engine_node.
        IntentMapper performs the final exact-event lookup.
        """
        try:
            data = json.loads(msg.data if hasattr(msg, 'data') else str(msg))
        except (json.JSONDecodeError, TypeError):
            return

        event_type = data.get("event_type", "")

        # ── Name-call event ─────────────────────────────────────────────
        if event_type in _ALLOWED_AUDIO_EVENTS:
            if self._on_audio_direct:
                self._on_audio_direct(event_type, data)
            return

        # ── Per-command events (EVT_VOICE_COMMAND_<ACTION>) ─────────────
        if event_type.startswith(_COMMAND_EVENT_PREFIX):
            if self._on_audio_direct:
                self._on_audio_direct(event_type, data)
            return

        # ── Session lifecycle events ──────────────────────────────────
        if event_type in _AUDIO_STATE_EVENTS:
            if self._on_audio_direct:
                self._on_audio_direct(event_type, data)
            return

        # ── Audio events for emotion_engine (NOT behavior_tree) ──
        if event_type in _AUDIO_FOR_EMOTION_ENGINE:
            self._logger.debug(
                f"Audio event {event_type} ignored_by_behavior_tree "
                f"(→ emotion_engine_node / internal_need_node)")
            return

        # ── Unknown audio events ─────────────────────────────────────
        self._logger.debug(f"Audio event {event_type} ignored (not in whitelist)")

    def _on_visual_ros2(self, msg):
        """Handle /perception/visual_event messages.

        Caches humans, active_target, and tracked_objects as a visual-service
        fallback.
        visual_event.events are NOT mapped to behavior candidates —
        they go through emotion_engine_node or internal_need_node.
        """
        try:
            data = json.loads(msg.data if hasattr(msg, 'data') else str(msg))
        except (json.JSONDecodeError, TypeError):
            return

        with self._lock:
            self._visual_cache_updated_at = time.monotonic()
            self._cached_humans = [
                dict(item)
                for item in data.get("humans", [])
                if isinstance(item, dict)
            ]
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

            # ── Log events but DO NOT generate behavior candidates ────────
            events = data.get("events", [])
            if events:
                event_types = [e if isinstance(e, str) else e.get("event_type", "?")
                             for e in events]
                self._logger.debug(
                    f"visual_event received for scene cache only, "
                    f"not behavior candidate generation. events={event_types}")
                if self._on_visual_event:
                    for evt in events:
                        self._on_visual_event(evt, data)

    # ── Callback Registration ────────────────────────────────────────────────

    def set_on_audio_direct(self, callback: Callable) -> None:
        """Register callback for event-type-driven audio events.

        callback(event_type: str, data: dict)
        Called for: EVT_VOICE_CALL_NAME and EVT_VOICE_COMMAND_<ACTION>.
        """
        self._on_audio_direct = callback

    def set_on_visual_event(self, callback: Callable) -> None:
        """Register callback for visual events (logging/debug only).

        Visual events do NOT generate behavior candidates.
        Their scene fields are cached as a visual-service fallback.
        """
        self._on_visual_event = callback

    # ── Service Methods ──────────────────────────────────────────────────────

    def check_person(self) -> dict:
        """Check if a person is currently visible/interacting.

        This synchronous compatibility API uses the visual-event cache.
        Need routing uses :meth:`request_social_target` for an asynchronous
        service-backed decision.
        """
        if self._ros2_ready:
            return self._check_person_ros2()
        else:
            return self._mock_client.check_person()

    def _check_person_ros2(self) -> dict:
        with self._lock:
            if not self._visual_cache_is_fresh_locked():
                return {
                    "present": False,
                    "count": 0,
                    "identity": "unknown",
                }
            return {
                "present": self._person_present,
                "count": len(self._cached_humans) or int(self._person_present),
                "identity": self._active_identity,
            }

    def detect_objects(self, confidence: float = 0.5) -> list[dict]:
        """Return cached/mock objects through a synchronous compatibility API."""
        if self._ros2_ready:
            with self._lock:
                if not self._visual_cache_is_fresh_locked():
                    return []
                return [
                    dict(item)
                    for item in self._cached_objects
                    if float(item.get("confidence", 1.0)) >= confidence
                ]
        else:
            return self._mock_client.detect_objects(confidence)

    def request_social_target(self, callback: Callable[[dict | None], None]) -> None:
        """Resolve person-first social targeting without blocking ROS callbacks."""
        if not self._ros2_ready:
            callback(self._social_context_from_mock())
            return

        scheduled = self._call_vision_task_async(
            "check_person",
            {},
            lambda result: self._on_social_person_result(result, callback),
        )
        if not scheduled:
            callback(self._social_context_from_cache())

    def request_emotion_context(
        self,
        callback: Callable[[dict], None],
    ) -> None:
        """Resolve human/solo emotion mode through ``check_person``."""
        if not self._ros2_ready:
            callback(self._emotion_context_from_person(
                self._mock_client.check_person()
            ))
            return

        scheduled = self._call_vision_task_async(
            "check_person",
            {},
            lambda result: callback(
                self._emotion_context_from_person(
                    result if result is not None else self.check_person()
                )
            ),
        )
        if not scheduled:
            callback(self._emotion_context_from_person(self.check_person()))

    def _emotion_context_from_person(self, person: dict) -> dict:
        if _as_bool(person.get("present")):
            identity = str(
                person.get("identity")
                or self.get_active_identity()
                or "unknown"
            )
            try:
                count = int(person.get("count", 1))
            except (TypeError, ValueError):
                count = 1
            return {
                "route": "human",
                "target": {
                    "target_type": "human",
                    "target_id": identity,
                    "identity": identity,
                    "count": count,
                },
            }
        return {"route": "solo", "target": None}

    def _on_social_person_result(
        self,
        result: dict | None,
        callback: Callable[[dict | None], None],
    ) -> None:
        if result is None:
            # Do not choose an animal after an indeterminate person check:
            # fall back to the latest full scene so human-first ordering holds.
            callback(self._social_context_from_cache())
            return

        if _as_bool(result.get("present")):
            identity = str(result.get("identity") or self.get_active_identity())
            try:
                count = int(result.get("count", 1))
            except (TypeError, ValueError):
                count = 1
            callback({
                "route": "human",
                "target": {
                    "target_type": "human",
                    "target_id": identity or "unknown",
                    "identity": identity or "unknown",
                    "count": count,
                },
            })
            return

        scheduled = self._call_vision_task_async(
            "detect_objects",
            {"confidence": 0.5},
            lambda objects_result: self._on_social_objects_result(
                objects_result,
                callback,
            ),
        )
        if not scheduled:
            callback(self._social_context_from_cache())

    def _on_social_objects_result(
        self,
        result: dict | None,
        callback: Callable[[dict | None], None],
    ) -> None:
        objects = self._objects_from_result(result)
        if objects is None:
            callback(self._social_context_from_cache())
            return
        target = select_social_animal(objects)
        callback(
            {"route": "animal", "target": target}
            if target is not None
            else None
        )

    def request_exploration_context(
        self,
        callback: Callable[[dict], None],
    ) -> None:
        """Resolve familiar/unfamiliar/empty exploration context."""
        if not self._ros2_ready:
            callback(select_exploration_context(
                self._mock_client.detect_objects(0.5)
            ))
            return

        scheduled = self._call_vision_task_async(
            "detect_objects",
            {"confidence": 0.5},
            lambda result: callback(self._exploration_context_from_result(result)),
        )
        if not scheduled:
            callback(select_exploration_context(self.detect_objects(0.5)))

    def request_hunger_context(
        self,
        callback: Callable[[dict], None],
    ) -> None:
        """Resolve visible-dog-food versus search-food Hunger context."""
        if not self._ros2_ready:
            callback(select_hunger_context(
                self._mock_client.detect_objects(0.5)
            ))
            return

        scheduled = self._call_vision_task_async(
            "detect_objects",
            {"confidence": 0.5},
            lambda result: callback(self._hunger_context_from_result(result)),
        )
        if not scheduled:
            callback(select_hunger_context(self.detect_objects(0.5)))

    def _hunger_context_from_result(self, result: dict | None) -> dict:
        objects = self._objects_from_result(result)
        if objects is None:
            objects = self.detect_objects(0.5)
        return select_hunger_context(objects)

    def _exploration_context_from_result(self, result: dict | None) -> dict:
        objects = self._objects_from_result(result)
        if objects is None:
            objects = self.detect_objects(0.5)
        return select_exploration_context(objects)

    def _social_context_from_mock(self) -> dict | None:
        person = self._mock_client.check_person()
        if person.get("present"):
            identity = str(person.get("identity", "unknown"))
            return {
                "route": "human",
                "target": {
                    "target_type": "human",
                    "target_id": identity,
                    "identity": identity,
                    "count": int(person.get("count", 1)),
                },
            }
        target = select_social_animal(self._mock_client.detect_objects(0.5))
        return (
            {"route": "animal", "target": target}
            if target is not None
            else None
        )

    def _social_context_from_cache(self) -> dict | None:
        person = self.check_person()
        if person.get("present"):
            identity = str(person.get("identity", "unknown"))
            return {
                "route": "human",
                "target": {
                    "target_type": "human",
                    "target_id": identity,
                    "identity": identity,
                    "count": int(person.get("count", 1)),
                },
            }
        target = select_social_animal(self.detect_objects(0.5))
        return (
            {"route": "animal", "target": target}
            if target is not None
            else None
        )

    @staticmethod
    def _objects_from_result(result: dict | None) -> list[dict] | None:
        if result is None:
            return None
        objects = result.get("objects")
        if isinstance(objects, str):
            try:
                objects = json.loads(objects)
            except json.JSONDecodeError:
                return None
        if not isinstance(objects, list):
            return None
        return [
            dict(item)
            for item in objects
            if isinstance(item, dict)
        ]

    def is_person_present(self) -> bool:
        """Quick cached check — is a person currently visible?"""
        if self._ros2_ready:
            with self._lock:
                return (
                    self._visual_cache_is_fresh_locked()
                    and self._person_present
                )
        else:
            return self._mock_client.is_person_present()

    def get_active_identity(self) -> str:
        """Get the identity of the currently visible person."""
        if self._ros2_ready:
            with self._lock:
                return (
                    self._active_identity
                    if self._visual_cache_is_fresh_locked()
                    else "unknown"
                )
        else:
            return self._mock_client.check_person().get("identity", "unknown")

    def _visual_cache_is_fresh_locked(self) -> bool:
        """Return whether the last visual scene is recent enough to trust."""
        return (
            self._visual_cache_updated_at > 0.0
            and time.monotonic() - self._visual_cache_updated_at
            <= self.VISUAL_CACHE_TIMEOUT_SEC
        )

    def _call_vision_task_async(
        self,
        task_type: str,
        params: dict,
        callback: Callable[[dict | None], None],
    ) -> bool:
        """Schedule a non-blocking VisionTask/PerceptionTask request."""
        client = self._vision_client
        service_type = self._vision_service_type
        if client is None or service_type is None:
            return False
        if hasattr(client, "service_is_ready") and not client.service_is_ready():
            self._logger.warn(
                "Vision service unavailable: %s; using visual-event cache"
                % self._vision_service_name
            )
            return False

        import uuid
        task_id = f"bt_{uuid.uuid4().hex[:8]}"
        request = service_type.Request()
        request.task_id = task_id
        request.task_type = task_type
        request.params_json = json.dumps(params, ensure_ascii=False)
        try:
            future = client.call_async(request)
        except Exception as exc:
            self._logger.error(f"Vision service call failed: {exc}")
            return False

        def _done(completed) -> None:
            try:
                response = completed.result()
                if response is None or not bool(response.success):
                    error = (
                        getattr(response, "error_message", "")
                        if response is not None
                        else "empty response"
                    )
                    self._logger.error(
                        f"Vision task {task_type} failed: {error}"
                    )
                    callback(None)
                    return
                result = json.loads(response.result_json or "{}")
                if isinstance(result, list):
                    result = {
                        str(item.get("key", "")): item.get("value")
                        for item in result if isinstance(item, dict)
                    }
                callback(result if isinstance(result, dict) else None)
            except Exception as exc:
                self._logger.error(
                    f"Vision task {task_type} response failed: {exc}"
                )
                callback(None)

        future.add_done_callback(_done)
        self._logger.debug(
            "Vision service call: %s task_type=%s task_id=%s"
            % (self._vision_service_name, task_type, task_id)
        )
        return True

    # ── Mock Control (for testing) ───────────────────────────────────────────

    def mock_set_person_present(self, present: bool, identity: str = "owner"):
        if not self._ros2_ready:
            self._mock_client.set_person_present(present, identity=identity)

    def mock_set_no_person(self):
        if not self._ros2_ready:
            self._mock_client.set_no_person()

    def mock_set_animals(self, animals: list[str | dict]) -> None:
        if not self._ros2_ready:
            self._mock_client.set_animals(animals)

    def mock_set_objects(self, objects: list[dict]) -> None:
        if not self._ros2_ready:
            self._mock_client.set_objects(objects)

    def mock_clear_scene(self) -> None:
        if not self._ros2_ready:
            self._mock_client.clear_scene()


# Backward-compatibility alias
PerceptionBridge = PerceptionClientAdapter
