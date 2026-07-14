"""Perception Client Adapter — encapsulates perception system interactions.

Connects the behavior tree to the perception subsystem:

Subscriptions:
  /perception/audio_event  (RELIABLE, depth=10)
    → Whitelist: EVT_VOICE_CALL_NAME, EVT_VOICE_COMMAND_KNOWN
    → Other audio events (PRAISE, SCOLD, HAPPY, SAD, etc.) are IGNORED —
      they should be consumed by emotion_engine_node, not behavior_tree_node.

  /perception/visual_event  (BEST_EFFORT, depth=5)
    → ONLY for active_target cache (person presence check).
    → visual_event.events MUST NOT be mapped to behavior candidates.
    → Visual events go through emotion_engine → /emotion/signal_event.

Service Client:
  /perception/perception_task
    → check_person()    — is a person present? → interactive/solo mode
    → detect_objects()  — what objects are visible? → exploration targets

In standalone mode (no ROS2), falls back to MockPerceptionClient.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Optional, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from .ros2_compat import NodeBase, HAS_ROS2, is_ros2_ready

# ── Whitelist: audio events behavior_tree_node directly processes ──────
_ALLOWED_AUDIO_EVENTS = {
    "EVT_VOICE_CALL_NAME",
    "EVT_VOICE_COMMAND_KNOWN",
    "EVT_VOICE_COMMAND_UNKNOWN",
}

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


class PerceptionClientAdapter:
    """Adapts ROS2 perception topics/services for the behavior tree.

    Audio events: whitelist-only (EVT_VOICE_CALL_NAME, EVT_VOICE_COMMAND_KNOWN).
    Visual events: active_target cache only, NO behavior candidate generation.

    Usage:
        adapter = PerceptionClientAdapter(node)
        adapter.set_on_audio_direct(lambda event_type, data: ...)
        adapter.set_on_visual_event(lambda evt, data: ...)  # optional, for logging

        person = adapter.check_person()
        objects = adapter.detect_objects()
    """

    AUDIO_EVENT_TOPIC = "/perception/audio_event"
    VISUAL_EVENT_TOPIC = "/perception/visual_event"
    PERCEPTION_SERVICE = "/perception/perception_task"

    def __init__(self, node: NodeBase):
        self._node = node
        self._logger = node.get_logger()

        # Callbacks
        self._on_audio_direct: Optional[Callable] = None  # (event_type, data_dict)
        self._on_visual_event: Optional[Callable] = None

        # Cached state from visual_event (for check_person / interaction_resolver)
        self._person_present: bool = False
        self._active_identity: str = "unknown"
        self._lock = threading.Lock()

        if HAS_ROS2 and is_ros2_ready():
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

        self._logger.info(
            "PerceptionClientAdapter: audio_event + visual_event subscriptions ready")

    def _setup_mock(self):
        from bionic_dog_bt.mock_perception_client import MockPerceptionClient
        self._mock_client = MockPerceptionClient()
        self._logger.info(
            "PerceptionClientAdapter: using MockPerceptionClient (standalone mode)")

    # ── ROS2 Callbacks ───────────────────────────────────────────────────────

    def _on_audio_ros2(self, msg):
        """Handle /perception/audio_event messages with whitelist filtering.

        Whitelist: EVT_VOICE_CALL_NAME, EVT_VOICE_COMMAND_KNOWN.
        All other audio events are IGNORED — they belong to emotion_engine_node.
        """
        try:
            data = json.loads(msg.data if hasattr(msg, 'data') else str(msg))
        except (json.JSONDecodeError, TypeError):
            return

        event_type = data.get("event_type", "")

        # ── Whitelist: direct audio events behavior_tree processes ────
        if event_type in _ALLOWED_AUDIO_EVENTS:
            if event_type == "EVT_VOICE_COMMAND_UNKNOWN":
                self._logger.debug(
                    f"EVT_VOICE_COMMAND_UNKNOWN (disabled by default): "
                    f"asr='{data.get('asr_text', '')}'")
                # Still forward — intent_mapper checks enabled flag
            if self._on_audio_direct:
                self._on_audio_direct(event_type, data)
            return

        # ── Audio events for emotion_engine (NOT behavior_tree) ──────
        if event_type in _AUDIO_FOR_EMOTION_ENGINE:
            self._logger.debug(
                f"Audio event {event_type} ignored_by_behavior_tree "
                f"(→ emotion_engine_node / internal_need_node)")
            return

        # ── Unknown audio events ─────────────────────────────────────
        self._logger.debug(f"Audio event {event_type} ignored (not in whitelist)")

    def _on_visual_ros2(self, msg):
        """Handle /perception/visual_event messages.

        ONLY caches active_target for person-presence checks.
        visual_event.events are NOT mapped to behavior candidates —
        they go through emotion_engine_node or internal_need_node.
        """
        try:
            data = json.loads(msg.data if hasattr(msg, 'data') else str(msg))
        except (json.JSONDecodeError, TypeError):
            return

        with self._lock:
            # ── Cache active_target for check_person / interaction_resolver ──
            target = data.get("active_target", {})
            if target:
                identity = target.get("identity", "unknown")
                is_registered = target.get("is_registered", False)
                is_speaking = target.get("is_speaking", False)
                self._person_present = is_registered or is_speaking
                self._active_identity = identity if identity != "unknown" else "unknown"

            # ── Log events but DO NOT generate behavior candidates ────────
            events = data.get("events", [])
            if events:
                event_types = [e if isinstance(e, str) else e.get("event_type", "?")
                             for e in events]
                self._logger.debug(
                    f"visual_event received for target cache only, "
                    f"not behavior candidate generation. events={event_types}")
                if self._on_visual_event:
                    for evt in events:
                        self._on_visual_event(evt, data)

    # ── Callback Registration ────────────────────────────────────────────────

    def set_on_audio_direct(self, callback: Callable) -> None:
        """Register callback for whitelisted audio events.

        callback(event_type: str, data: dict)
        Called for: EVT_VOICE_CALL_NAME, EVT_VOICE_COMMAND_KNOWN
        """
        self._on_audio_direct = callback

    def set_on_command(self, callback: Callable) -> None:
        """[DEPRECATED] Use set_on_audio_direct instead.

        Kept for backward compatibility — wraps the old
        (command_id, behavior_name, confidence, params) signature.
        """
        def _wrap(event_type, data):
            if event_type == "EVT_VOICE_COMMAND_KNOWN":
                command_id = data.get("command_id", "")
                # behavior_name is now resolved downstream via intent_mapper
                callback(command_id, command_id,  # pass command_id as placeholder
                        float(data.get("intent_confidence", 0.8)),
                        {"command_id": command_id,
                         "source": "audio_command",
                         "asr_text": data.get("asr_text", ""),
                         "intent_confidence": data.get("intent_confidence", 0.8)})
            elif event_type == "EVT_VOICE_CALL_NAME":
                callback("EVT_VOICE_CALL_NAME", "orient_to_sound",
                        float(data.get("wake_confidence", 0.8)),
                        {"source": "audio_command",
                         "use_wake_angle": True})
        self._on_audio_direct = _wrap

    def set_on_visual_event(self, callback: Callable) -> None:
        """Register callback for visual events (logging/debug only).

        Visual events do NOT generate behavior candidates.
        They are only used for active_target cache.
        """
        self._on_visual_event = callback

    # ── Service Methods ──────────────────────────────────────────────────────

    def check_person(self) -> dict:
        """Check if a person is currently visible/interacting.

        In ROS2 mode, uses cached state from visual_event first,
        falling back to /perception/perception_task service.
        """
        if HAS_ROS2 and is_ros2_ready():
            return self._check_person_ros2()
        else:
            return self._mock_client.check_person()

    def _check_person_ros2(self) -> dict:
        with self._lock:
            if self._person_present:
                return {
                    "present": True,
                    "count": 1,
                    "identity": self._active_identity,
                }
        try:
            result = self._call_perception_service("check_person", "[]")
            if result:
                for item in result:
                    if item.get("key") == "present":
                        return {
                            "present": item.get("value") == "true",
                            "count": int(self._get_result_item(result, "count", "0")),
                            "identity": self._get_result_item(result, "identity", "unknown"),
                        }
        except Exception as e:
            self._logger.error(f"check_person service failed: {e}")
        return {"present": False, "count": 0, "identity": "unknown"}

    def detect_objects(self, confidence: float = 0.5) -> list[dict]:
        """Detect objects in the current frame."""
        if HAS_ROS2 and is_ros2_ready():
            return self._detect_objects_ros2(confidence)
        else:
            return (self._mock_client.detect_objects()
                    if hasattr(self._mock_client, 'detect_objects') else [])

    def _detect_objects_ros2(self, confidence: float) -> list[dict]:
        params = json.dumps([{"key": "confidence", "value": str(confidence)}])
        try:
            result = self._call_perception_service("detect_objects", params)
            if result:
                for item in result:
                    if item.get("key") == "objects":
                        return json.loads(item.get("value", "[]"))
        except Exception as e:
            self._logger.error(f"detect_objects service failed: {e}")
        return []

    def is_person_present(self) -> bool:
        """Quick cached check — is a person currently visible?"""
        if HAS_ROS2 and is_ros2_ready():
            with self._lock:
                return self._person_present
        else:
            return self._mock_client.is_person_present()

    def get_active_identity(self) -> str:
        """Get the identity of the currently visible person."""
        if HAS_ROS2 and is_ros2_ready():
            with self._lock:
                return self._active_identity
        else:
            return self._mock_client.check_person().get("identity", "unknown")

    def _call_perception_service(self, task_type: str, params_json: str) -> Optional[list]:
        """Call /perception/perception_task and parse result_json."""
        import uuid
        task_id = f"bt_{uuid.uuid4().hex[:8]}"
        self._logger.debug(
            f"Service call: /perception/perception_task "
            f"task_type={task_type} task_id={task_id}")
        # In real ROS2 deployment, this would use marsdog_interfaces.srv.PerceptionTask
        return None

    @staticmethod
    def _get_result_item(result: list, key: str, default: str = "") -> str:
        for item in result:
            if item.get("key") == key:
                return item.get("value", default)
        return default

    # ── Mock Control (for testing) ───────────────────────────────────────────

    def mock_set_person_present(self, present: bool, identity: str = "owner"):
        if not HAS_ROS2:
            self._mock_client.set_person_present(present, identity=identity)

    def mock_set_no_person(self):
        if not HAS_ROS2:
            self._mock_client.set_no_person()


# Backward-compatibility alias
PerceptionBridge = PerceptionClientAdapter
