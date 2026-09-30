"""Perception Client Adapter — encapsulates perception system interactions.

Connects the behavior tree to the perception subsystem:

Subscriptions:
  /perception/audio_event  (RELIABLE, depth=10)
    → Whitelist: wake/lifecycle, audited commands, and exact social reactions
    → Model-Intent emotion/classification evidence is ignored here and remains
      owned by emotion_engine_node or internal_need_node.

  /perception/visual_event  (BEST_EFFORT, depth=5)
    → Caches humans, active_target, and tracked_objects as service fallback.
    → Forwards STRANGER, FALL, and STOP_GESTURE appearance edges.
    → Repeated state snapshots are collapsed to one callback per appearance.

Service Client:
  /perception/vision/task
    → check_person()    — is a person present? → interactive/solo mode
    → detect_objects()  — what objects are visible? → exploration targets

The legacy /perception/perception_task contract is used as a fallback when its
service type is installed. Standalone mode uses MockPerceptionClient.
"""

from __future__ import annotations

from . import visual_event_consumer

import json
import threading
import time
from typing import Optional, Callable

from bionic_dog_bt.visual_context import (
    select_exploration_context,
    select_hunger_context,
    select_social_animal,
    select_wake_speaker,
)

from .ros2_compat import NodeBase, HAS_ROS2, is_ros2_ready

# ── Direct event types processed by behavior_tree_node ─────────────────
_ALLOWED_AUDIO_EVENTS = {
    "EVT_VOICE_WAKEUP",
    "EVT_VOICE_WAKE_SPEAKER_RESULT",
}

# ── Prefix for per-command events (EVT_VOICE_COMMAND_SIT, etc.) ────────
_COMMAND_EVENT_PREFIXES = (
    "EVT_VOICE_COMMAND_",
)

# ── Social/state evidence that must not directly enter the Tree ───────
_AUDIO_NON_TREE_EVENTS = {
    "EVT_VOICE_MASTER_ID",
    "EVT_VOICE_FOLK_ID",
    "EVT_VOICE_UNMASTER_ID",
    "EVT_VOICE_STRANGER_ID",
    "EVT_VOICE_CALL_NAME",
    "EVT_VOICE_COMMAND_CALL_NAME",
    "EVT_VOICE_PRAISE",
    "EVT_VOICE_SCOLD",
    "EVT_VOICE_COMFORT",
    "EVT_VOICE_PLAY_INTERACTION",
    "EVT_VOICE_POSITIVE_EMOTION",
    "EVT_VOICE_NEGATIVE_EMOTION",
    "EVT_VOICE_STATUS_CARE",
    "EVT_VOICE_COMMAND_KNOWN",
    "EVT_VOICE_COMMAND_UNKNOWN",
    "EVT_VOICE_HAPPY",
    "EVT_VOICE_SAD",
    "EVT_VOICE_NEUTRAL",
    "speech",
}

# ── Explicit one-shot vocabulary reactions ─────────────────────────
# PRAISE/SCOLD stay non-executable events while explicitly authorizing one
# bounded behavior-tree reaction.
_AUDIO_REACTION_EVENTS = {
    "EVT_VOICE_COMMAND_PRAISE",
    "EVT_VOICE_COMMAND_SCOLD",
}

# ── Audio lifecycle events consumed by behavior_tree ───────────────────
_AUDIO_STATE_EVENTS = {
    "EVT_STATE_CHANGED",
}

_DIRECT_VISUAL_EVENTS = {
    "EVT_VISION_FALL",
    "EVT_VISION_STOP_GESTURE",
}


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class PerceptionClientAdapter:
    """Adapts ROS2 perception topics/services for the behavior tree.

    Audio events: schema-v2 wake/lifecycle and explicitly authorized commands.
    Visual events: scene cache plus direct STRANGER/FALL/STOP callbacks.
    Hunger/Social/Exploration need events query the visual service and use this
    cache only when that service is unavailable.

    Usage:
        adapter = PerceptionClientAdapter(node)
        adapter.set_on_audio_direct(lambda event_type, data: ...)
        adapter.set_on_visual_event(lambda event_type, data: ...)

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
    VISION_TASK_TIMEOUT_SEC = 2.0

    def __init__(
        self,
        node: NodeBase,
        *,
        vision_task_timeout_sec: float = VISION_TASK_TIMEOUT_SEC,
    ):
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
        self._active_direct_visual_events: set[str] = set()

        # Cached state from visual_event (service fallback / interaction resolver)
        self._person_present: bool = False
        self._active_identity: str = "unknown"
        self._cached_humans: list[dict] = []
        self._cached_human_candidates: list[dict] = []
        self._cached_objects: list[dict] = []
        self._cached_vision_epoch: str = ""
        self._cached_visual_header: dict = {}
        self._visual_cache_updated_at: float = 0.0
        self._lock = threading.Lock()
        self._vision_client = None
        self._vision_service_type = None
        self._vision_service_name = ""
        self._vision_task_timeout_sec = max(
            0.05, float(vision_task_timeout_sec)
        )

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
          EVT_VOICE_WAKEUP / EVT_STATE_CHANGED
          EVT_VOICE_COMMAND_<ACTION>

        All other audio events are IGNORED — they belong to emotion_engine_node.
        IntentMapper performs the final exact-event lookup.
        """
        try:
            data = json.loads(msg.data if hasattr(msg, 'data') else str(msg))
        except (json.JSONDecodeError, TypeError):
            return
        if (
            not isinstance(data, dict)
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != 2
        ):
            self._logger.debug(
                "audio_event rejected: expected object with schema_version=2"
            )
            return
        event_type = data.get("event_type", "")
        if not isinstance(event_type, str) or not event_type:
            self._logger.debug(
                "audio_event rejected: event_type must be a non-empty string"
            )
            return

        # ── Hardware wake and correlated wake-speaker result ─────────────
        if event_type in _ALLOWED_AUDIO_EVENTS:
            if self._on_audio_direct:
                self._on_audio_direct(event_type, data)
            return

        # ── Social/classification/identity evidence (never direct action) ─
        # Check this before the generic command prefix so catalog CALL/PRAISE/
        # SCOLD stay non-executable even if an upstream permission bit drifts.
        if event_type in _AUDIO_NON_TREE_EVENTS:
            self._logger.debug(
                f"Audio event {event_type} ignored_by_behavior_tree "
                f"(owned by social/emotion/need consumers)")
            return

        # ── Social events bound to emotion behaviors ─────────────────────
        # Non-executable social events need explicit Tree reaction authority.
        if event_type in _AUDIO_REACTION_EVENTS:
            if (
                data.get("should_trigger_behavior_tree") is True
                and data.get("dispatch_role") == "social_reaction"
                and data.get("is_executable") is False
                and self._on_audio_direct
            ):
                self._on_audio_direct(event_type, data)
            else:
                self._logger.debug(
                    "audio reaction ignored: event_type=%s has invalid "
                    "authority fields" % event_type
                )
            return

        # ── Per-command events (EVT_VOICE_COMMAND_<ACTION>) ─────────────
        if event_type.startswith(_COMMAND_EVENT_PREFIXES):
            if (
                data.get("should_trigger_behavior_tree") is not True
                or data.get("dispatch_role") != "specific_command"
            ):
                self._logger.debug(
                    "audio_event ignored: event_type=%s is not an authorized "
                    "specific command" % event_type
                )
                return
            if self._on_audio_direct:
                self._on_audio_direct(event_type, data)
            return

        # ── Session lifecycle events ──────────────────────────────────
        if event_type in _AUDIO_STATE_EVENTS:
            if self._on_audio_direct:
                self._on_audio_direct(event_type, data)
            return

        # ── Unknown audio events ─────────────────────────────────────
        self._logger.debug(f"Audio event {event_type} ignored (not in whitelist)")

    def _on_visual_ros2(self, msg):
        return visual_event_consumer.consume_visual_event(self, msg, direct_events=_DIRECT_VISUAL_EVENTS)

    # ── Callback Registration ────────────────────────────────────────────────

    def set_on_audio_direct(self, callback: Callable) -> None:
        """Register callback for event-type-driven audio events.

        callback(event_type: str, data: dict)
        Called for: EVT_VOICE_WAKEUP and EVT_VOICE_COMMAND_<ACTION>.
        """
        self._on_audio_direct = callback

    def set_on_visual_event(self, callback: Callable) -> None:
        """Register callback for direct visual-event appearance edges."""
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

    def request_owner_target(
        self,
        callback: Callable[[dict | None], None],
        *,
        min_confidence: float = 0.5,
        max_age_ms: float = 500.0,
    ) -> None:
        """Resolve one immutable owner target without choosing another human."""
        if not self._ros2_ready:
            person = self._mock_client.check_person()
            identity = str(person.get("identity", "")).strip().lower()
            if not _as_bool(person.get("present")) or identity != "owner":
                callback(None)
                return
            callback({
                "target_type": "human",
                "vision_epoch": "mock-vision",
                "target_id": "mock-vision:human:1",
                "track_id": 1,
                "identity": "owner",
                "identity_state": "confirmed_known",
                "identity_confidence": 1.0,
                "detection_confidence": 1.0,
                "tracking_state": "tracking",
                "last_seen_age_ms": 0.0,
            })
            return

        def _select(result: dict | None) -> None:
            candidates = self._human_targets_from_result(result)
            if candidates is None:
                candidates = self._wake_candidates_from_cache()
            callback(self._select_owner_target(candidates))

        scheduled = self._call_vision_task_async(
            "query_targets",
            {
                "target_types": ["human"],
                "min_confidence": float(min_confidence),
                "max_age_ms": float(max_age_ms),
            },
            _select,
        )
        if not scheduled:
            _select(None)

    def request_wake_speaker(
        self,
        callback: Callable[[dict | None], None],
        *,
        reference_bearing_deg: float = 0.0,
        min_confidence: float = 0.3,
        max_age_ms: float = 300.0,
        max_bearing_error_deg: float = 25.0,
        max_snapshot_age_ms: float = 500.0,
    ) -> None:
        """Resolve the human aligned with a completed wake-source turn.

        The service response and visual-event fallback use the same pure
        selection function.  This keeps audio/vision fusion in the behavior
        layer while Vision remains a fact provider.
        """
        def _select(result: dict | None) -> None:
            if isinstance(result, dict):
                try:
                    snapshot_age_ms = float(
                        result.get("snapshot_age_ms", 0.0)
                    )
                except (TypeError, ValueError):
                    snapshot_age_ms = float("inf")
                if (
                    snapshot_age_ms < 0.0
                    or snapshot_age_ms > float(max_snapshot_age_ms)
                ):
                    result = None
            candidates = self._human_targets_from_result(result)
            if candidates is None:
                candidates = self._wake_candidates_from_cache()
            callback(select_wake_speaker(
                candidates,
                reference_bearing_deg=reference_bearing_deg,
                min_confidence=min_confidence,
                max_age_ms=max_age_ms,
                max_bearing_error_deg=max_bearing_error_deg,
            ))

        if not self._ros2_ready:
            person = self._mock_client.check_person()
            if not person.get("present"):
                callback(None)
                return
            identity = str(person.get("identity", "unknown"))
            callback({
                "vision_epoch": "mock-vision",
                "target_id": "mock-vision:human:1",
                "track_id": 1,
                "target_type": "human",
                "identity": identity,
                "identity_state": (
                    "confirmed_known" if identity not in ("", "unknown")
                    else "unknown"
                ),
                "identity_confidence": 1.0 if identity != "unknown" else 0.0,
                "detection_confidence": 1.0,
                "tracking_state": "tracking",
                "last_seen_age_ms": 0.0,
                "center_x": 0.5,
                "center_y": 0.5,
                "bearing_deg": 0.0,
                "range_valid": False,
                "distance_m": None,
                "selection_reason": "mock_wake_speaker",
            })
            return

        scheduled = self._call_vision_task_async(
            "query_targets",
            {
                "target_types": ["human"],
                "min_confidence": float(min_confidence),
                "max_age_ms": float(max_age_ms),
            },
            _select,
        )
        if not scheduled:
            _select(None)

    def _emotion_context_from_person(self, person: dict) -> dict:
        if _as_bool(person.get("present")):
            identity = str(
                person.get("identity")
                or self.get_active_identity()
                or "unknown"
            )
            candidates = self._human_targets_from_result(person)
            if candidates is None and getattr(self, "_ros2_ready", False):
                candidates = self._wake_candidates_from_cache()
            elif candidates is None:
                # Standalone perception has no persistent vision stream; keep
                # an explicit mock epoch so the same immutable-target contract
                # is still visible at the Action boundary.
                candidates = [{
                    "vision_epoch": "mock-vision",
                    "target_id": identity,
                }]
            selected = next(
                (
                    dict(candidate)
                    for candidate in candidates
                    if str(candidate.get("vision_epoch", "")).strip()
                    and str(candidate.get("target_id", "")).strip()
                ),
                None,
            )
            if selected is None:
                # Presence without an immutable visual target is not safe for
                # a WithHuman mobility behavior.  Route solo instead of
                # dispatching a target that Action must reject.
                return {"route": "solo", "target": None}
            try:
                count = int(person.get("count", 1))
            except (TypeError, ValueError):
                count = 1
            selected.update({
                "target_type": "human",
                "identity": identity,
                "count": count,
            })
            return {
                "route": "human",
                "target": selected,
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

    @staticmethod
    def _human_targets_from_result(
        result: dict | None,
    ) -> list[dict] | None:
        if result is None:
            return None
        targets = result.get("targets", result.get("human_candidates"))
        if not isinstance(targets, list):
            return None
        vision_epoch = str(result.get("vision_epoch", "")).strip()
        snapshot_id = str(result.get("snapshot_id", "")).strip()
        snapshot_sequence = result.get("sequence")
        header = result.get("header")
        normalized: list[dict] = []
        for item in targets:
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            if vision_epoch:
                candidate.setdefault("vision_epoch", vision_epoch)
            if snapshot_id:
                candidate.setdefault("snapshot_id", snapshot_id)
            if isinstance(snapshot_sequence, int) and not isinstance(
                snapshot_sequence, bool
            ):
                candidate.setdefault("snapshot_sequence", snapshot_sequence)
            if isinstance(header, dict):
                candidate.setdefault("source_stamp", header.get("stamp"))
                candidate.setdefault("frame_id", header.get("frame_id"))
            normalized.append(candidate)
        return normalized

    @staticmethod
    def _select_owner_target(candidates: list[dict]) -> dict | None:
        """Select only a stable Vision target explicitly identified as owner."""
        for item in candidates:
            if not isinstance(item, dict):
                continue
            identity = str(item.get("identity", "")).strip().lower()
            vision_epoch = str(item.get("vision_epoch", "")).strip()
            target_id = str(item.get("target_id", "")).strip()
            if (
                identity != "owner"
                or item.get("identity_state") != "confirmed_known"
                or item.get("tracking_state") != "tracking"
                or not vision_epoch
                or not target_id
            ):
                continue
            selected = dict(item)
            selected.update({
                "target_type": "human",
                "identity": "owner",
            })
            return selected
        return None

    def _wake_candidates_from_cache(self) -> list[dict]:
        with self._lock:
            if not self._visual_cache_is_fresh_locked():
                return []
            return [dict(item) for item in self._cached_human_candidates]

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

        completion_lock = threading.Lock()
        completion = {"finished": False, "timer": None}

        def _finish_once(result: dict | None) -> bool:
            timer = None
            with completion_lock:
                if completion["finished"]:
                    return False
                completion["finished"] = True
                timer = completion["timer"]
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass
                destroy_timer = getattr(self._node, "destroy_timer", None)
                if callable(destroy_timer):
                    try:
                        destroy_timer(timer)
                    except Exception:
                        pass
            callback(result)
            return True

        def _done(completed) -> None:
            try:
                response = completed.result()
                if response is None or not bool(response.success):
                    error = (
                        getattr(response, "error_message", "")
                        if response is not None
                        else "empty response"
                    )
                    if _finish_once(None):
                        self._logger.error(
                            f"Vision task {task_type} failed: {error}"
                        )
                    return
                result = json.loads(response.result_json or "{}")
                if isinstance(result, list):
                    result = {
                        str(item.get("key", "")): item.get("value")
                        for item in result if isinstance(item, dict)
                    }
                _finish_once(result if isinstance(result, dict) else None)
            except Exception as exc:
                if _finish_once(None):
                    self._logger.error(
                        f"Vision task {task_type} response failed: {exc}"
                    )

        def _timed_out() -> None:
            if _finish_once(None):
                self._logger.warn(
                    "Vision task %s timed out after %.2fs: task_id=%s; "
                    "using visual-event cache"
                    % (task_type, self._vision_task_timeout_sec, task_id)
                )

        try:
            timer = self._node.create_timer(
                self._vision_task_timeout_sec,
                _timed_out,
            )
        except Exception as exc:
            self._logger.error(
                "Vision task %s timeout timer failed: %s"
                % (task_type, exc)
            )
            _finish_once(None)
            return True
        with completion_lock:
            completion["timer"] = timer

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
