"""Perception Bridge — ROS2 interface to the perception system.

Connects the behavior tree to real perception nodes:

Subscriptions:
  /perception/audio_event  (RELIABLE, depth=10)
    → Filters EVT_VOICE_COMMAND_KNOWN events
    → Extracts command_id → behavior_name via COMMAND_BEHAVIOR_MAP
    → Feeds candidate into behavior_tree_node candidate pool

Service Client:
  /perception/perception_task  (RELIABLE)
    → check_person()    — is a person present? → interactive/solo mode
    → detect_objects()  — what objects are visible? → exploration targets

In standalone mode (no ROS2), falls back to MockPerceptionClient.
"""

from __future__ import annotations

import json
import sys
import time
import threading
from pathlib import Path
from typing import Optional, Callable

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bionic_dog_bt.constants import COMMAND_BEHAVIOR_MAP, PRIORITY_LEVELS

from .ros2_compat import NodeBase, HAS_ROS2


# ═══════════════════════════════════════════════════════════════════════════════
# Perception Bridge
# ═══════════════════════════════════════════════════════════════════════════════

class PerceptionBridge:
    """Bridges ROS2 perception topics/services to the behavior tree.

    Usage:
        bridge = PerceptionBridge(node)
        bridge.set_on_command_callback(lambda cmd_id, bhv_name, confidence: ...)

        # In BT tick:
        person = bridge.check_person()
        objects = bridge.detect_objects()
    """

    # ── QoS constants (matching perception system) ──────────────────────────

    AUDIO_EVENT_TOPIC = "/perception/audio_event"
    VISUAL_EVENT_TOPIC = "/perception/visual_event"
    PERCEPTION_SERVICE = "/perception/perception_task"

    # audio_event QoS: RELIABLE, KEEP_LAST, depth=10
    AUDIO_QOS = {"reliability": "reliable", "durability": "volatile",
                 "history": "keep_last", "depth": 10}
    # visual_event QoS: BEST_EFFORT, KEEP_LAST, depth=5
    VISUAL_QOS = {"reliability": "best_effort", "durability": "volatile",
                  "history": "keep_last", "depth": 5}

    def __init__(self, node: NodeBase):
        self._node = node
        self._logger = node.get_logger()

        # Callbacks
        self._on_command: Optional[Callable] = None  # (command_id, behavior_name, confidence, params)
        self._on_visual_event: Optional[Callable] = None  # (event_type, data)

        # Cached state from visual_event
        self._person_present: bool = False
        self._active_identity: str = "unknown"
        self._lock = threading.Lock()

        # Service availability
        self._service_ready: bool = False

        if HAS_ROS2:
            self._setup_ros2()
        else:
            self._setup_mock()

    # ── ROS2 Setup ───────────────────────────────────────────────────────────

    def _setup_ros2(self):
        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

        # Audio event subscription (RELIABLE, depth=10)
        audio_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self._node.create_subscription(
            String, self.AUDIO_EVENT_TOPIC, self._on_audio_ros2, audio_qos,
        )

        # Visual event subscription (BEST_EFFORT, depth=5)
        visual_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
        )
        self._node.create_subscription(
            String, self.VISUAL_EVENT_TOPIC, self._on_visual_ros2, visual_qos,
        )

        # Perception task service client
        self._service_client = None  # Created lazily
        self._logger.info("PerceptionBridge: audio_event + visual_event subscriptions ready")

    def _setup_mock(self):
        from bionic_dog_bt.mock_perception_client import MockPerceptionClient
        self._mock_client = MockPerceptionClient()
        self._logger.info("PerceptionBridge: using MockPerceptionClient (standalone mode)")

    # ── ROS2 Callbacks ───────────────────────────────────────────────────────

    def _on_audio_ros2(self, msg):
        """Handle /perception/audio_event messages."""
        try:
            data = json.loads(msg.data if hasattr(msg, 'data') else str(msg))
        except (json.JSONDecodeError, TypeError):
            return

        event_type = data.get("event_type", "")

        # ── EVT_VOICE_COMMAND_KNOWN → behavior candidate ─────────────────
        if event_type == "EVT_VOICE_COMMAND_KNOWN":
            command_id = data.get("command_id", "CMD_UNKNOWN")
            intent_confidence = data.get("intent_confidence", 0.8)
            is_executable = data.get("is_executable", True)
            asr_text = data.get("asr_text", "")
            state = data.get("state", "")

            if not is_executable or command_id == "CMD_UNKNOWN":
                self._logger.debug(f"Ignoring non-executable command: {command_id}")
                return

            behavior_name = COMMAND_BEHAVIOR_MAP.get(command_id)
            if behavior_name is None:
                self._logger.debug(f"Unknown command_id: {command_id}")
                return

            params = {
                "command_id": command_id,
                "source": "audio_command",
                "asr_text": asr_text,
                "intent_confidence": intent_confidence,
            }

            self._logger.info(
                f"COMMAND: {command_id} → {behavior_name} "
                f"(confidence={intent_confidence:.2f}, asr='{asr_text}')"
            )

            if self._on_command:
                self._on_command(command_id, behavior_name, intent_confidence, params)

        # ── Other audio events → log (handled by emotion_engine) ──────────
        elif event_type in (
            "EVT_VOICE_CALL_NAME", "EVT_VOICE_MASTER_ID",
            "EVT_VOICE_PRAISE", "EVT_VOICE_SCOLD",
            "EVT_VOICE_HAPPY", "EVT_VOICE_SAD", "EVT_VOICE_NEUTRAL",
        ):
            self._logger.debug(f"Audio event (→ emotion_engine): {event_type}")

    def _on_visual_ros2(self, msg):
        """Handle /perception/visual_event messages."""
        try:
            data = json.loads(msg.data if hasattr(msg, 'data') else str(msg))
        except (json.JSONDecodeError, TypeError):
            return

        with self._lock:
            # Update person presence from active_target
            target = data.get("active_target", {})
            if target:
                identity = target.get("identity", "unknown")
                is_registered = target.get("is_registered", False)
                is_speaking = target.get("is_speaking", False)
                self._person_present = is_registered or is_speaking
                self._active_identity = identity if identity != "unknown" else "unknown"

            # Forward visual events
            events = data.get("events", [])
            for evt in events:
                if self._on_visual_event:
                    self._on_visual_event(evt, data)

    # ── Callback Registration ────────────────────────────────────────────────

    def set_on_command(self, callback: Callable) -> None:
        """Register callback for EVT_VOICE_COMMAND_KNOWN.

        callback(command_id: str, behavior_name: str, confidence: float, params: dict)
        """
        self._on_command = callback

    def set_on_visual_event(self, callback: Callable) -> None:
        """Register callback for visual events.

        callback(event_type: str, data: dict)
        """
        self._on_visual_event = callback

    # ── Service Methods ──────────────────────────────────────────────────────

    def check_person(self) -> dict:
        """Check if a person is currently visible/interacting.

        In ROS2 mode, calls /perception/perception_task with task_type="check_person".
        In mock mode, uses MockPerceptionClient.

        Returns dict: {"present": bool, "count": int, "identity": str}
        """
        if HAS_ROS2:
            return self._check_person_ros2()
        else:
            return self._mock_client.check_person()

    def _check_person_ros2(self) -> dict:
        """Real ROS2 service call for check_person."""
        with self._lock:
            # Use cached state from visual_event for fast response
            if self._person_present:
                return {
                    "present": True,
                    "count": 1,  # Single-person constraint
                    "identity": self._active_identity,
                }

        # Fallback: try service call
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
        """Detect objects in the current frame.

        In ROS2 mode, calls /perception/perception_task with task_type="detect_objects".
        Returns list of {"label": str, "x": float, "y": float, "w": float, "h": float,
                          "confidence": float, "center_x": float, "center_y": float}
        """
        if HAS_ROS2:
            return self._detect_objects_ros2(confidence)
        else:
            return self._mock_client.detect_objects() if hasattr(self._mock_client, 'detect_objects') else []

    def _detect_objects_ros2(self, confidence: float) -> list[dict]:
        """Real ROS2 service call for detect_objects."""
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
        if HAS_ROS2:
            with self._lock:
                return self._person_present
        else:
            return self._mock_client.is_person_present()

    def get_active_identity(self) -> str:
        """Get the identity of the currently visible person."""
        if HAS_ROS2:
            with self._lock:
                return self._active_identity
        else:
            return self._mock_client.check_person().get("identity", "unknown")

    # ── Service Client Helper ────────────────────────────────────────────────

    def _call_perception_service(self, task_type: str, params_json: str) -> Optional[list]:
        """Call /perception/perception_task and parse result_json.

        Returns list of {"key": ..., "value": ...} dicts, or None on failure.
        """
        import uuid
        task_id = f"bt_{uuid.uuid4().hex[:8]}"

        # This would be the real ROS2 service call using marsdog_perception.srv.PerceptionTask
        # For now, log that we would call it
        self._logger.debug(
            f"Service call: /perception/perception_task "
            f"task_type={task_type} task_id={task_id}"
        )
        # In a real ROS2 deployment:
        # from marsdog_perception.srv import PerceptionTask
        # req = PerceptionTask.Request()
        # req.task_id = task_id
        # req.task_type = task_type
        # req.params_json = params_json
        # future = self._service_client.call_async(req)
        # rclpy.spin_until_future_complete(self._node, future, timeout_sec=2.0)
        # if future.result() and future.result().success:
        #     return json.loads(future.result().result_json)
        return None

    @staticmethod
    def _get_result_item(result: list, key: str, default: str = "") -> str:
        for item in result:
            if item.get("key") == key:
                return item.get("value", default)
        return default

    # ── Mock Control (for testing) ───────────────────────────────────────────

    def mock_set_person_present(self, present: bool, identity: str = "owner"):
        """Set mock person presence (standalone/test mode only)."""
        if not HAS_ROS2:
            self._mock_client.set_person_present(present, identity=identity)

    def mock_set_no_person(self):
        """Clear mock person presence."""
        if not HAS_ROS2:
            self._mock_client.set_no_person()
