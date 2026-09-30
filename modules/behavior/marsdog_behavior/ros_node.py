"""Behavior Tree ROS2 Node — /behavior_tree_node.

The central decision-making node in the MarsDog behavior stack.
This is a thin ROS2 shell — all logic is delegated to internal modules.

Subscriptions:
  /emotion/state             — V2 values + triggered booleans (periodic)
  /emotion/signal_event      — V2 threshold rising-edge events
  /internal_need/state       — V2 current need states (periodic)
  /internal_need/signal_event — V2 need level-change events (event-driven)

Publishers:
  /behavior/result_event     — demand behavior STARTED / COMPLETED / etc.

Action Client:
  /execute_behavior — sends goals to marsdog_action_executor

Internal delegation:
  candidate_pool.py       — candidate collection + selection
  relevance_checker.py    — current-state relevance checking
  interaction_resolver.py — person-presence → interactive/solo
  execution_manager.py    — goal lifecycle management
  result_event_mapper.py  — /behavior/result_event formatting
  perception_client_adapter.py — audio/visual event handling
"""

from __future__ import annotations

import json
import math
import time
from collections import deque

import yaml

from bionic_dog_bt.blackboard import Blackboard
from bionic_dog_bt.constants import (
    EMOTION_PRIORITY,
    EMOTION_V2_EVENT_TO_NAME,
    NEED_LEVEL_NORMAL,
    NEED_LEVEL_URGENT,
    NEED_LEVEL_OVERFLOW,
    NEED_V2_ACTIVE_LEVELS,
    NEED_V2_EVENT_TO_STATE,
    STATUS_RUNNING,
)
from bionic_dog_bt.logger import init_logging, get_logger

from .ros2_compat import NodeBase, HAS_ROS2, is_ros2_ready
from .config_paths import get_config_file
from .result_event_mapper import ResultEventMapper
from .perception_client_adapter import PerceptionClientAdapter
from .intent_mapper import IntentMapper, BehaviorCandidate
from .runtime import BehaviorRuntime
from .voice_interaction_session import (
    ACQUIRING_TARGET,
    APPROACHING,
    AWAITING_IDENTITY,
    CLOSED,
    ORIENTING,
    WAITING,
    VoiceInteractionSession,
)
from .voice_session_client_adapter import VoiceSessionClientAdapter
from .audio_contract import WAKE_ANGLE_FRAME_ID, validate_wake_event

# ── 直驱式特殊音频事件（硬编码处理，不在 event_intent_map 白名单内）──────

# 词库社交反应：非动作命令，但允许一次性行为表达。
_AUDIO_REACTION_EVENTS = {
    "EVT_VOICE_COMMAND_PRAISE",
    "EVT_VOICE_COMMAND_SCOLD",
}

# 饮食查询分流 / 打断 / PLAY 绑兴奋（control=DO）
_SPECIAL_AUDIO_EVENTS = {
    "EVT_VOICE_COMMAND_RESPOND_HUNGRY_QUERY",
    "EVT_VOICE_COMMAND_RESPOND_WANT_EAT_QUERY",
    "EVT_VOICE_COMMAND_RESPOND_EATING_QUERY",
    "EVT_VOICE_COMMAND_PLAY",
}

# 情绪名 → V2 事件类型（社交事件/PLAY 绑情绪用）
_EMOTION_NAME_TO_EVENT = {
    name: event for event, name in EMOTION_V2_EVENT_TO_NAME.items()
}

# 饮食查询分流阈值（Hunger > 70 视为「饿」）—— 待与产品确认
_HUNGER_ROUTE_THRESHOLD = 70.0

# 视为「进食中」的行为名
_EATING_BEHAVIORS = {
    "eatNormally",
    "eatExcitedly",
    "eat_meal",
    "eat_snack",
    "eat_canned_food",
}

_OWNER_TARGET_AUDIO_BEHAVIORS = frozenset({
    "unhappy",
    "miss_owner",
    "farewell_leave",
})

_OWNER_NAV_AUDIO_BEHAVIORS = frozenset({
    "approach_owner",
    "come_to_owner",
    "return_to_owner",
})


def _is_json_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _need_level_event(demand: str, level: str) -> str:
    suffix = "RECOVERED" if level == NEED_LEVEL_NORMAL else level
    return f"NEED_{demand.upper()}_{suffix}"


def _need_level_from_value(
    value: float,
    *,
    trigger_threshold: float,
    urgent_threshold: float | None,
    overflow_threshold: float | None,
) -> str:
    """Derive a V2 need level; every V2 comparison is strict ``gt``."""
    if overflow_threshold is not None and value > overflow_threshold:
        return NEED_LEVEL_OVERFLOW
    if urgent_threshold is not None and value > urgent_threshold:
        return NEED_LEVEL_URGENT
    if value > trigger_threshold:
        return "TRIGGERED"
    return NEED_LEVEL_NORMAL


def _parse_need_thresholds(
    payload: dict,
    context: str,
    *,
    require_overflow_operator: bool,
) -> tuple[float, str, float | None, str | None, float | None, str | None]:
    """Validate and return the V2 threshold metadata."""
    required_fields = {
        "triggerThreshold",
        "triggerOperator",
        "urgentThreshold",
        "urgentOperator",
        "overflowThreshold",
    }
    if require_overflow_operator:
        required_fields.add("overflowOperator")
    missing = sorted(required_fields - payload.keys())
    if missing:
        raise ValueError(
            f"{context} missing V2 threshold fields: {', '.join(missing)}"
        )

    trigger_threshold = payload.get("triggerThreshold")
    trigger_operator = payload.get("triggerOperator")
    if not _is_json_number(trigger_threshold):
        raise ValueError(f"{context}.triggerThreshold must be numeric")
    if trigger_operator != "gt":
        raise ValueError(f"{context}.triggerOperator must be 'gt'")

    urgent_threshold = payload.get("urgentThreshold")
    urgent_operator = payload.get("urgentOperator")
    if urgent_threshold is None and urgent_operator is None:
        pass
    elif (
        not _is_json_number(urgent_threshold)
        or urgent_operator != "gt"
    ):
        raise ValueError(
            f"{context}.urgentThreshold/urgentOperator must be null/null "
            "or numeric/'gt'"
        )

    overflow_threshold = payload.get("overflowThreshold")
    overflow_operator = payload.get("overflowOperator")
    if overflow_threshold is None:
        if overflow_operator is not None:
            raise ValueError(
                f"{context}.overflowOperator requires overflowThreshold"
            )
    else:
        if not _is_json_number(overflow_threshold):
            raise ValueError(f"{context}.overflowThreshold must be numeric or null")
        if overflow_operator is None and not require_overflow_operator:
            overflow_operator = "gt"
        if overflow_operator != "gt":
            raise ValueError(f"{context}.overflowOperator must be 'gt'")

    normalized_trigger = float(trigger_threshold)
    normalized_urgent = (
        float(urgent_threshold) if urgent_threshold is not None else None
    )
    normalized_overflow = (
        float(overflow_threshold) if overflow_threshold is not None else None
    )
    if (
        normalized_urgent is not None
        and normalized_urgent <= normalized_trigger
    ):
        raise ValueError(f"{context}.urgentThreshold must exceed triggerThreshold")
    previous_threshold = (
        normalized_urgent
        if normalized_urgent is not None
        else normalized_trigger
    )
    if (
        normalized_overflow is not None
        and normalized_overflow <= previous_threshold
    ):
        raise ValueError(
            f"{context}.overflowThreshold must exceed earlier thresholds"
        )

    return (
        normalized_trigger,
        trigger_operator,
        normalized_urgent,
        urgent_operator,
        normalized_overflow,
        overflow_operator,
    )


class BehaviorTreeRosNode(NodeBase):
    """Main behavior tree runtime as a ROS2 Node.

    Collects upstream signals into a candidate pool, runs the
    priority-based behavior tree at 10Hz, and dispatches behaviors
    to the action executor via Action Client.

    Set force_mock=True to use mock mode even when ROS2 is importable
    (useful for standalone_demo and testing).
    """

    TICK_RATE = 0.1  # 10Hz

    # ── Topic constants ──────────────────────────────────────────────────
    EMOTION_STATE_TOPIC = "/emotion/state"
    EMOTION_SIGNAL_TOPIC = "/emotion/signal_event"
    NEED_STATE_TOPIC = "/internal_need/state"
    NEED_SIGNAL_TOPIC = "/internal_need/signal_event"
    RESULT_EVENT_TOPIC = "/behavior/result_event"
    ATTENTION_TRACKING_TOPIC = "/behavior/attention_tracking"
    GOAL_LEASE_TOPIC = "/behavior/goal_lease"

    def __init__(self, node_name: str = "behavior_tree_node",
                 config_path: str = None, force_mock: bool = False):
        self._ros2_ready = HAS_ROS2 and is_ros2_ready() and not force_mock
        if self._ros2_ready:
            super().__init__(node_name)
        else:
            # Use mock base directly
            from .ros2_compat import _MockNode
            _MockNode.__init__(self, node_name)

        init_logging(ros2_node=self if HAS_ROS2 else None)
        self._logger = get_logger("bt_node")

        # ── Internal runtime ─────────────────────────────────────────────
        self._blackboard = Blackboard()

        # ── Config path ──────────────────────────────────────────────────
        if config_path is None:
            config_path = str(get_config_file("behaviors.yaml"))

        # ── Executor setup ───────────────────────────────────────────────
        self._setup_executor(config_path)

        # ── Exact event_type → intent → behavior mapper ─────────────────
        self._intent_mapper = IntentMapper()
        continuation = self._intent_mapper.get_emotion_continuation_config()
        self._emotion_continuation_enabled = bool(
            continuation.get("enabled", True)
        )
        self._emotion_continuation_interval_sec = max(
            0.0, float(continuation.get("interval_sec", 0.8))
        )
        self._emotion_continuation_max_cycles = max(
            1, int(continuation.get("max_cycles", 4))
        )
        self._emotion_continuation_max_duration_sec = max(
            1.0, float(continuation.get("max_duration_sec", 15.0))
        )
        configured_emotions = continuation.get(
            "emotions", ["Fear", "Anxiety", "Excite", "Joy", "Curious"]
        )
        self._emotion_continuation_emotions = {
            str(name)
            for name in configured_emotions
            if str(name) in EMOTION_V2_EVENT_TO_NAME.values()
        }
        self._emotion_continuations: dict[str, dict[str, float | int]] = {}
        self._emotion_continuation_requests: set[str] = set()

        # ── Perception Client Adapter ────────────────────────────────────
        vision_task_timeout_sec = PerceptionClientAdapter.VISION_TASK_TIMEOUT_SEC
        if self._ros2_ready:
            self.declare_parameter(
                "vision_task_timeout_sec",
                vision_task_timeout_sec,
            )
            vision_task_timeout_sec = float(
                self.get_parameter("vision_task_timeout_sec").value
            )
        self._perception = PerceptionClientAdapter(
            self,
            vision_task_timeout_sec=vision_task_timeout_sec,
        )
        self._blackboard.perception_client = self._perception
        self._perception.set_on_audio_direct(self._on_audio_direct)
        self._perception.set_on_visual_event(self._on_visual_direct)
        self._voice_session_client = VoiceSessionClientAdapter(self)
        self._voice_engagement = self._load_voice_engagement_config()

        # ── Transport-independent decision runtime ───────────────────────
        self._runtime = BehaviorRuntime(
            self._executor,
            blackboard=self._blackboard,
            candidate_gate=self._candidate_allowed_during_interaction,
        )
        # Compatibility aliases for standalone tools and existing callers.
        self._tree = self._runtime.tree
        self._candidate_pool = self._runtime.candidate_pool
        self._result_mapper = ResultEventMapper()

        # ── State tracking ───────────────────────────────────────────────
        self._running = True
        self._last_logged_emotion_state: (
            tuple[tuple[str, bool], ...] | None
        ) = None
        self._last_logged_need_state: (
            tuple[tuple[str, str], ...] | None
        ) = None
        self._emotion_visual_generation: dict[str, int] = {}
        # An emotion edge may outlive a voice attention phase. Keep its intent,
        # then resolve a fresh target once expression is safe again.
        self._pending_emotion_edges: dict[str, str] = {}
        self._pending_emotion_retry_at: dict[str, float] = {}
        self._need_visual_generation: dict[str, int] = {}
        self._audio_target_generation = 0
        self._voice_session_generation = 0
        self._voice_session: VoiceInteractionSession | None = None
        self._seen_audio_event_keys: set[tuple[str, str, str]] = set()
        self._seen_audio_event_order: deque[tuple[str, str, str]] = deque()
        self._attention_interaction_id = ""
        self._attention_mode = "face_body_centering"
        self._eating_resume: dict | None = None

        # ── Setup I/O ────────────────────────────────────────────────────
        if self._ros2_ready:
            self._setup_ros2()
        else:
            self._setup_mock()

        self._logger.info(
            f"BehaviorTreeRosNode started (tick={self.TICK_RATE}s)")

    # ── Executor Setup ───────────────────────────────────────────────────

    def _setup_executor(self, config_path: str):
        """Create the executor: ActionClientAdapter (ROS2) or MockActionExecutor."""
        from bionic_dog_bt.yaml_loader import YAMLLoader
        yaml_loader = YAMLLoader(config_path)

        if self._ros2_ready:
            # Prefer marsdog_interfaces (public), fallback to marsdog_action_executor
            action_type = None
            action_pkg = None
            import traceback as _tb
            try:
                from marsdog_interfaces.action import ExecuteBehavior as EB1
                action_type = EB1
                action_pkg = "marsdog_interfaces"
            except Exception as _e:
                self._logger.warn(f"marsdog_interfaces.action import failed: {_e}")
            if action_type is None:
                try:
                    from marsdog_action_executor.action import ExecuteBehavior as EB2
                    action_type = EB2
                    action_pkg = "marsdog_action_executor"
                except Exception as _e:
                    self._logger.warn(f"marsdog_action_executor.action import failed: {_e}")

            if action_type is not None:
                from .action_client_adapter import ActionClientAdapter
                self._executor = ActionClientAdapter(self, "/execute_behavior")
                self._using_real_executor = True
                self._logger.info(
                    f"Executor: ActionClientAdapter → /execute_behavior "
                    f"(via {action_pkg}.action)")
                return  # Success — skip fallback

            self._logger.warn(
                "ExecuteBehavior action type not found; "
                "falling back to MockActionExecutor. "
                "Build: colcon build --packages-select marsdog_interfaces")

        # Fallback: use MockActionExecutor
        from bionic_dog_bt.mock_action_executor import MockActionExecutor
        self._executor = MockActionExecutor(yaml_loader)
        self._using_real_executor = False
        self._logger.info("Executor: MockActionExecutor (standalone/fallback mode)")

    @staticmethod
    def _load_voice_engagement_config() -> dict:
        with open(
            get_config_file("voice_engagement.yaml"),
            "r",
            encoding="utf-8",
        ) as stream:
            value = yaml.safe_load(stream) or {}
        configured = value.get("voice_engagement", {})
        return dict(configured) if isinstance(configured, dict) else {}

    # ── ROS2 Setup ───────────────────────────────────────────────────────

    def _setup_ros2(self):
        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

        qos_reliable = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST, depth=10)
        qos_besteffort = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST, depth=5)

        # Subscribe to upstream topics
        self.create_subscription(
            String, self.EMOTION_STATE_TOPIC,
            self._on_emotion_state_ros2, qos_besteffort)
        self.create_subscription(
            String, self.EMOTION_SIGNAL_TOPIC,
            self._on_emotion_signal_ros2, qos_reliable)
        self.create_subscription(
            String, self.NEED_STATE_TOPIC,
            self._on_need_state_ros2, qos_besteffort)
        self.create_subscription(
            String, self.NEED_SIGNAL_TOPIC,
            self._on_need_signal_ros2, qos_reliable)

        # Publisher: only /behavior/result_event
        self._result_pub = self.create_publisher(
            String, self.RESULT_EVENT_TOPIC, qos_reliable)
        self._attention_pub = self.create_publisher(
            String, self.ATTENTION_TRACKING_TOPIC, qos_reliable)
        self._goal_lease_pub = self.create_publisher(
            String, self.GOAL_LEASE_TOPIC, qos_reliable)

        self.create_timer(self.TICK_RATE, self._on_tick)

        self._logger.info(
            "ROS2 subscriptions ready: "
            "/emotion/state /emotion/signal_event "
            "/internal_need/state /internal_need/signal_event")

    def _setup_mock(self):
        import threading
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def _tick_loop(self):
        while getattr(self, '_running', True):
            self._on_tick()
            time.sleep(self.TICK_RATE)

    # ── ROS2 Callbacks ───────────────────────────────────────────────────

    def _on_emotion_state_ros2(self, msg):
        """Handle /emotion/state (periodic, 1Hz).

        V2 state is authoritative for both current values and recovery. It
        never generates candidates; only /emotion/signal_event does that.
        """
        try:
            data = json.loads(msg.data)
            if data.get("schema_version") != "2.0":
                raise ValueError(
                    "unsupported emotion schema_version "
                    f"{data.get('schema_version')!r}; expected '2.0'"
                )

            emotions = data.get("emotions")
            if not isinstance(emotions, dict):
                raise ValueError("emotions must be an object")

            # Validate the entire snapshot before mutating the blackboard.
            updates = []
            for name, emotion_info in emotions.items():
                if name not in EMOTION_V2_EVENT_TO_NAME.values():
                    raise ValueError(f"unknown emotion {name!r}")
                if not isinstance(emotion_info, dict):
                    raise ValueError(f"emotions.{name} must be an object")

                value = emotion_info.get("value")
                triggered = emotion_info.get("triggered")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"emotions.{name}.value must be numeric")
                if not isinstance(triggered, bool):
                    raise ValueError(f"emotions.{name}.triggered must be boolean")

                trigger_threshold = emotion_info.get("triggerThreshold")
                if (
                    trigger_threshold is not None
                    and (
                        isinstance(trigger_threshold, bool)
                        or not isinstance(trigger_threshold, (int, float))
                    )
                ):
                    raise ValueError(
                        f"emotions.{name}.triggerThreshold must be numeric"
                    )
                trigger_operator = emotion_info.get("triggerOperator")
                if trigger_operator is not None and not isinstance(
                    trigger_operator, str
                ):
                    raise ValueError(
                        f"emotions.{name}.triggerOperator must be a string"
                    )
                updates.append(
                    (
                        name,
                        float(value),
                        triggered,
                        trigger_threshold,
                        trigger_operator,
                    )
                )

            for update in updates:
                self._blackboard.emotion_module.update_state(*update)
                emotion_name, _, triggered, _, _ = update
                if not triggered:
                    self._invalidate_emotion_visual_request(emotion_name)
                    self._candidate_pool.discard_emotion(emotion_name)
                    self._stop_emotion_continuation(emotion_name)
                    self._pending_emotion_edges.pop(emotion_name, None)
                    self._pending_emotion_retry_at.pop(emotion_name, None)

            emotion_names = (
                "Joy", "Excite", "Anxiety", "Fear", "Curious", "Calm",
            )
            log_state = tuple(
                (
                    name,
                    self._blackboard.emotion_module.is_triggered(name),
                )
                for name in emotion_names
            )
            if log_state != self._last_logged_emotion_state:
                states = ", ".join(
                    f"{name}={'on' if triggered else 'off'}"
                    for name, triggered in log_state
                )
                self._logger.debug(f"/emotion/state changed: [{states}]")
                self._last_logged_emotion_state = log_state
        except Exception as e:
            self._logger.error(f"Failed to parse /emotion/state: {e}")

    def _on_emotion_signal_ros2(self, msg):
        """Handle /emotion/signal_event (event-driven).

        Accepts only V2 single-threshold upward-edge events.
        """
        try:
            data = json.loads(msg.data)
            if data.get("schema_version") != "2.0":
                raise ValueError(
                    "unsupported emotion schema_version "
                    f"{data.get('schema_version')!r}; expected '2.0'"
                )

            event_type = data.get("event_type")
            expected_emotion = EMOTION_V2_EVENT_TO_NAME.get(event_type)
            if expected_emotion is None:
                raise ValueError(f"unsupported V2 emotion event {event_type!r}")

            emotion_name = data.get("emotion")
            if emotion_name != expected_emotion:
                raise ValueError(
                    f"event {event_type} requires emotion={expected_emotion!r}, "
                    f"got {emotion_name!r}"
                )

            signal_value = data.get("value")
            if (
                isinstance(signal_value, bool)
                or not isinstance(signal_value, (int, float))
            ):
                raise ValueError("emotion signal value must be numeric")
            trigger_threshold = data.get("triggerThreshold")
            if (
                trigger_threshold is not None
                and (
                    isinstance(trigger_threshold, bool)
                    or not isinstance(trigger_threshold, (int, float))
                )
            ):
                raise ValueError("emotion signal triggerThreshold must be numeric")
            trigger_operator = data.get("triggerOperator")
            if trigger_operator is not None and not isinstance(
                trigger_operator,
                str,
            ):
                raise ValueError("emotion signal triggerOperator must be a string")

            # candidate_inject/select/start are the INFO-level audit trail. The
            # raw ingress record remains available at DEBUG for contract checks.
            self._logger.debug(f"/emotion/signal_event: {event_type}")

            # Bridge the gap before the next 1Hz state snapshot. Recovery is
            # still authoritative from /emotion/state.triggered=false.
            self._blackboard.emotion_module.update_state(
                emotion_name,
                float(signal_value),
                True,
                trigger_threshold,
                trigger_operator,
            )
            self._start_emotion_continuation(emotion_name)
            self._invalidate_emotion_visual_request(emotion_name)
            self._request_contextual_emotion_candidate(
                emotion_name,
                trigger_event=event_type,
            )
        except Exception as e:
            self._logger.error(f"Failed to parse /emotion/signal_event: {e}")

    def _on_need_state_ros2(self, msg):
        """Handle authoritative ``/internal_need/state`` V2 snapshots."""
        try:
            data = json.loads(msg.data)
            if data.get("schema_version") != "2.0":
                raise ValueError(
                    "unsupported internal need schema_version "
                    f"{data.get('schema_version')!r}; expected '2.0'"
                )

            demands = data.get("demands")
            if not isinstance(demands, dict):
                raise ValueError("demands must be an object")

            updates = []
            for need_name, need_info in demands.items():
                if need_name not in NEED_V2_ACTIVE_LEVELS:
                    raise ValueError(f"unknown demand {need_name!r}")
                if not isinstance(need_info, dict):
                    raise ValueError(f"demands.{need_name} must be an object")

                context = f"demands.{need_name}"
                value = need_info.get("value")
                if not _is_json_number(value):
                    raise ValueError(f"{context}.value must be numeric")
                if not 0 <= float(value) <= 100:
                    raise ValueError(f"{context}.value must be within 0..100")

                thresholds = _parse_need_thresholds(
                    need_info,
                    context,
                    require_overflow_operator=False,
                )
                (
                    trigger_threshold,
                    trigger_operator,
                    urgent_threshold,
                    urgent_operator,
                    overflow_threshold,
                    overflow_operator,
                ) = thresholds

                level = need_info.get("level")
                allowed_levels = (
                    {NEED_LEVEL_NORMAL}
                    | set(NEED_V2_ACTIVE_LEVELS[need_name])
                )
                if level not in allowed_levels:
                    raise ValueError(
                        f"{context}.level {level!r} is not configured"
                    )
                computed_level = _need_level_from_value(
                    float(value),
                    trigger_threshold=trigger_threshold,
                    urgent_threshold=urgent_threshold,
                    overflow_threshold=overflow_threshold,
                )
                if level != computed_level:
                    raise ValueError(
                        f"{context}.level must be {computed_level!r} "
                        f"for value {value!r}"
                    )

                expected_event = _need_level_event(need_name, level)
                level_event = need_info.get("levelEvent")
                if level_event != expected_event:
                    raise ValueError(
                        f"{context}.levelEvent must be {expected_event!r}"
                    )

                expected_triggered = level != NEED_LEVEL_NORMAL
                expected_urgent = (
                    urgent_threshold is not None
                    and level in (NEED_LEVEL_URGENT, NEED_LEVEL_OVERFLOW)
                )
                expected_overflow = level == NEED_LEVEL_OVERFLOW
                flags = {
                    "triggered": expected_triggered,
                    "urgent": expected_urgent,
                    "overflow": expected_overflow,
                    "levelActive": expected_triggered,
                }
                for field, expected in flags.items():
                    actual = need_info.get(field)
                    if not isinstance(actual, bool) or actual is not expected:
                        raise ValueError(
                            f"{context}.{field} must be {expected!r}"
                        )

                # A configured level and its threshold metadata must agree.
                has_urgent_level = NEED_LEVEL_URGENT in NEED_V2_ACTIVE_LEVELS[
                    need_name
                ]
                has_overflow_level = (
                    NEED_LEVEL_OVERFLOW in NEED_V2_ACTIVE_LEVELS[need_name]
                )
                if has_urgent_level != (urgent_threshold is not None):
                    raise ValueError(
                        f"{context} urgent threshold configuration mismatch"
                    )
                if has_overflow_level != (overflow_threshold is not None):
                    raise ValueError(
                        f"{context} overflow threshold configuration mismatch"
                    )

                updates.append({
                    "name": need_name,
                    "value": float(value),
                    "trigger_threshold": trigger_threshold,
                    "trigger_operator": trigger_operator,
                    "urgent_threshold": urgent_threshold,
                    "urgent_operator": urgent_operator,
                    "overflow_threshold": overflow_threshold,
                    "overflow_operator": overflow_operator,
                    "triggered": expected_triggered,
                    "urgent": expected_urgent,
                    "overflow": expected_overflow,
                    "level": level,
                    "level_event": level_event,
                    "level_active": expected_triggered,
                })

            # Validate the full snapshot before applying any entry.
            for update in updates:
                existing = self._blackboard.need_module.get_need(update["name"])
                existing_event = existing.level_event if existing else None
                self._blackboard.need_module.update_state(**update)
                if existing_event != update["level_event"]:
                    self._invalidate_need_visual_request(update["name"])
                self._candidate_pool.discard_need_except(
                    update["name"],
                    update["level_event"],
                )

            need_names = (
                "Hunger", "Bladder", "Sleepiness", "Cleanliness",
                "Energy", "Social", "Exploration",
            )
            log_state = tuple(
                (
                    name,
                    self._blackboard.need_module.level_events.get(name, "?"),
                )
                for name in need_names
            )
            if log_state != self._last_logged_need_state:
                events = ", ".join(
                    f"{name}={event}" for name, event in log_state
                )
                self._logger.debug(
                    f"/internal_need/state changed: [{events}]"
                )
                self._last_logged_need_state = log_state
        except Exception as e:
            self._logger.error(f"Failed to parse /internal_need/state: {e}")

    def _on_need_signal_ros2(self, msg):
        """Handle exact V2 need level-change events."""
        try:
            data = json.loads(msg.data)
            if data.get("schema_version") != "2.0":
                raise ValueError(
                    "unsupported internal need schema_version "
                    f"{data.get('schema_version')!r}; expected '2.0'"
                )

            event_type = data.get("event_type")
            expected_state = NEED_V2_EVENT_TO_STATE.get(event_type)
            if expected_state is None:
                raise ValueError(f"unsupported V2 need event {event_type!r}")

            demand = data.get("demand")
            level = data.get("level")
            expected_demand, expected_level = expected_state
            if demand != expected_demand or level != expected_level:
                raise ValueError(
                    f"event {event_type} requires demand={expected_demand!r}, "
                    f"level={expected_level!r}; got {demand!r}/{level!r}"
                )

            value = data.get("value")
            if not _is_json_number(value):
                raise ValueError("need signal value must be numeric")
            if not 0 <= float(value) <= 100:
                raise ValueError("need signal value must be within 0..100")

            previous_level = data.get("previousLevel")
            if previous_level not in {
                NEED_LEVEL_NORMAL,
                *NEED_V2_ACTIVE_LEVELS[demand],
            }:
                raise ValueError(
                    f"invalid previousLevel {previous_level!r} for {demand}"
                )
            if previous_level == level:
                raise ValueError(
                    "need signal previousLevel must differ from current level"
                )
            if data.get("trigger") != "LEVEL_CHANGED":
                raise ValueError("need signal trigger must be 'LEVEL_CHANGED'")

            thresholds = _parse_need_thresholds(
                data,
                "need signal",
                require_overflow_operator=True,
            )
            (
                trigger_threshold,
                trigger_operator,
                urgent_threshold,
                urgent_operator,
                overflow_threshold,
                overflow_operator,
            ) = thresholds

            has_urgent_level = NEED_LEVEL_URGENT in NEED_V2_ACTIVE_LEVELS[demand]
            has_overflow_level = (
                NEED_LEVEL_OVERFLOW in NEED_V2_ACTIVE_LEVELS[demand]
            )
            if has_urgent_level != (urgent_threshold is not None):
                raise ValueError("need signal urgent threshold configuration mismatch")
            if has_overflow_level != (overflow_threshold is not None):
                raise ValueError("need signal overflow threshold configuration mismatch")
            computed_level = _need_level_from_value(
                float(value),
                trigger_threshold=trigger_threshold,
                urgent_threshold=urgent_threshold,
                overflow_threshold=overflow_threshold,
            )
            if level != computed_level:
                raise ValueError(
                    f"need signal level must be {computed_level!r} "
                    f"for value {value!r}"
                )

            self._logger.debug(
                f"/internal_need/signal_event: {event_type} demand={demand} level={level}")

            triggered = level != NEED_LEVEL_NORMAL
            urgent = (
                urgent_threshold is not None
                and level in (NEED_LEVEL_URGENT, NEED_LEVEL_OVERFLOW)
            )
            overflow = level == NEED_LEVEL_OVERFLOW
            self._blackboard.need_module.update_state(
                demand,
                value=float(value),
                trigger_threshold=trigger_threshold,
                trigger_operator=trigger_operator,
                urgent_threshold=urgent_threshold,
                urgent_operator=urgent_operator,
                overflow_threshold=overflow_threshold,
                overflow_operator=overflow_operator,
                triggered=triggered,
                urgent=urgent,
                overflow=overflow,
                level=level,
                level_event=event_type,
                level_active=triggered,
                previous_level=previous_level,
            )
            self._invalidate_need_visual_request(demand)
            self._candidate_pool.discard_need_except(demand, event_type)

            if triggered:
                if demand in ("Hunger", "Social", "Exploration"):
                    self._request_contextual_need_candidate(
                        demand,
                        float(value),
                        trigger_event=event_type,
                        level=level,
                    )
                else:
                    self._generate_need_candidate(
                        demand,
                        float(value),
                        trigger_event=event_type,
                        level=level,
                    )
        except Exception as e:
            self._logger.error(f"Failed to parse /internal_need/signal_event: {e}")

    # ── Audio Direct Handler ──────────────────────────────────────────────

    def _on_visual_direct(self, event_type: str, data: dict) -> None:
        """Map a whitelisted visual event into the candidate pipeline."""
        candidate = self._intent_mapper.map_visual_event(event_type, data)
        if candidate is not None:
            self._add_candidate(candidate)
        else:
            self._logger.debug(
                "Visual event %s → no candidate (unmapped event_type)",
                event_type,
            )

    def _on_audio_direct(self, event_type: str, data: dict) -> None:
        """Handle event-type-driven audio events via the intent pipeline.

        Pipeline: event_type → category → intent → action_pool → behavior_name
        """
        if event_type == "EVT_VOICE_WAKE_SPEAKER_RESULT":
            if (not isinstance(data, dict)
                    or type(data.get("schema_version")) is not int
                    or data["schema_version"] != 2
                    or data.get("event_type") != event_type):
                return
            session = self._voice_session
            interaction_id = str(data.get("interaction_id", "")).strip()
            wake_id = str(data.get("wake_id", "")).strip()
            if (session is None or not session.matches(interaction_id)
                    or not wake_id or wake_id != session.metadata.get("wake_id")):
                return
            role = str(data.get("speaker_role", ""))
            status = str(data.get("speaker_status", ""))
            speaker_id = str(data.get("speaker_id", "unknown"))
            valid = (
                (role == "owner" and status == "matched" and speaker_id == "owner")
                or (role == "family" and status == "matched"
                    and speaker_id in {"family_member_1", "family_member_2",
                                       "family_member_3", "family_member_4"})
                or (role == "stranger" and status == "no_match"
                    and speaker_id == "unknown")
                or (role == "undetermined" and status in {
                    "ambiguous", "insufficient_audio", "unavailable"
                } and speaker_id == "unknown")
            )
            if not valid:
                return
            session.metadata["wake_speaker_role"] = role
            session.metadata["wake_speaker_status"] = status
            session.metadata["wake_speaker_id"] = speaker_id
            if session.phase == AWAITING_IDENTITY and not session.command_received:
                self._continue_wake_after_identity(session)
            return

        if event_type == "EVT_VOICE_WAKEUP":
            wake = self._validate_wake_event(data)
            if wake is None:
                return
            interaction_id = wake["interaction_id"]
            wake_id = wake["wake_id"]
            event_key = (interaction_id, wake_id, event_type)

            session = self._voice_session
            if self._audio_event_seen(event_key):
                return
            if session is not None and session.matches(interaction_id) and (
                not wake_id or wake_id == session.metadata.get("wake_id", "")
            ):
                self._remember_audio_event(event_key)
                return

            if session is not None and session.active:
                self._close_voice_session(
                    session.interaction_id,
                    reason="replaced_by_new_wake",
                )

            self._voice_session_generation += 1
            session = VoiceInteractionSession(
                interaction_id=interaction_id,
                generation=self._voice_session_generation,
                phase=ORIENTING,
                wake_event_stamp=wake["wake_event_stamp"],
                wake_angle_deg=wake["wake_angle_deg"],
                wake_frame_id=wake["wake_frame_id"],
                wake_confidence=wake["wake_confidence"],
                hold_token="wake-engagement:%s" % interaction_id,
            )
            self._voice_session = session
            if wake_id:
                session.metadata["wake_id"] = wake_id
                session.metadata["wake_speaker_role"] = "undetermined"
                session.metadata["wake_speaker_status"] = "pending"
                session.metadata["wake_speaker_id"] = "unknown"
            self._remember_audio_event(event_key)
            self._attention_interaction_id = ""
            self._attention_mode = "face_body_centering"
            self._request_voice_hold(session)

            candidate = self._intent_mapper.map_audio_event(event_type, data)
            if candidate is not None:
                if not self._add_candidate(candidate):
                    # A new wake can replace a still-running sound turn.  Its
                    # replacement is queued only after that Goal's real Result.
                    session.metadata["pending_wake_candidate"] = candidate
            return

        if event_type == "EVT_STATE_CHANGED":
            if (
                not isinstance(data, dict)
                or type(data.get("schema_version")) is not int
                or data["schema_version"] != 2
                or data.get("event_type") != event_type
            ):
                self._logger.warn(
                    "Voice state event rejected: invalid schema/event_type"
                )
                return
            event_interaction_id = str(data.get("interaction_id", "")).strip()
            if data.get("state") == "idle":
                session = self._voice_session
                if (
                    session is not None
                    and session.matches(event_interaction_id)
                ):
                    self._close_voice_session(
                        event_interaction_id,
                        reason=str(data.get("state_reason", "voice_idle")),
                    )
            return

        # ── 直驱式特殊音频事件（硬编码，不走 intent 白名单）─────────────
        if event_type in _AUDIO_REACTION_EVENTS:
            self._on_audio_reaction(event_type, data)
            return

        if event_type in _SPECIAL_AUDIO_EVENTS:
            self._on_special_audio_event(event_type, data)
            return

        # Exact mapping and the v2 execution-authority fields are validated
        # before this event may mutate the active voice session.
        candidate = self._intent_mapper.map_audio_event(event_type, data)
        if candidate is None:
            self._logger.debug(
                "Audio event %s → rejected or unmapped", event_type
            )
            return
        if not self._audio_need_gate_allows(candidate):
            return

        interaction_id = str(data.get("interaction_id", "")).strip()
        utterance_id = str(data.get("utterance_id", "")).strip()
        event_key = (interaction_id, utterance_id, event_type)
        if interaction_id and self._audio_event_seen(event_key):
            return

        session = self._voice_session
        if (
            session is not None
            and session.active
            and not session.matches(interaction_id)
        ):
            # A late command from an older Voice session must never drive the
            # current interaction.  Voice owns the interaction ID; BT only
            # accepts an exact match while a wake session is active.
            if interaction_id:
                self._remember_audio_event(event_key)
            self._logger.warn(
                "Voice command ignored: stale/missing interaction_id=%r "
                "current=%r" % (interaction_id, session.interaction_id)
            )
            return
        if (
            session is not None
            and session.matches(interaction_id)
        ):
            self._consume_voice_session_turn(session, "command")
        if interaction_id:
            self._remember_audio_event(event_key)

        # Every newer accepted command invalidates an older asynchronous owner
        # lookup.  A late Vision response must not enqueue movement after the
        # user has already issued another command.
        self._audio_target_generation = (
            getattr(self, "_audio_target_generation", 0) + 1
        )
        audio_target_generation = self._audio_target_generation

        behavior_name = (
            candidate.get("behavior_name", "")
            if isinstance(candidate, dict)
            else str(getattr(candidate, "behavior_name", ""))
        )
        if behavior_name == "follow_owner":
            # The long-running follow Goal owns UWB and the chassis.  End any
            # voice-only attention control before dispatching that Goal.
            self._attention_mode = "face_body_centering"
            self._publish_attention_control(False, data)
            self._attention_interaction_id = ""

        if behavior_name in _OWNER_TARGET_AUDIO_BEHAVIORS:
            self._request_owner_target_audio_candidate(
                candidate,
                interaction_id=interaction_id,
                generation=audio_target_generation,
            )
            return

        if behavior_name in _OWNER_NAV_AUDIO_BEHAVIORS:
            # Action binds a fresh human track from /perception/visual_event
            # immediately before its one-shot Vision/SLAM localization.
            # Visual face recognition is not required for these commands.
            candidate.target = None
            candidate.target_required = False
            candidate.interactive = False
            candidate.interaction_mode = "solo"
            candidate.params.pop("target_track_id", None)
            candidate.params.pop("target_identity", None)
            candidate.params.update({
                "target_resolution": "action_visual_event",
                "strict_target_lock": True,
                "allow_target_switch": False,
                "stand_off_distance_m": 1.5,
                "lifecycle_scope": "behavior",
                "cancel_on_voice_idle": False,
            })

        self._add_candidate(candidate)

    def _request_owner_target_audio_candidate(
        self,
        candidate: BehaviorCandidate,
        *,
        interaction_id: str,
        generation: int,
    ) -> None:
        """Bind an owner-only Vision target for social response behaviors."""
        event_type = candidate.trigger_event

        def _resolved(target: dict | None) -> None:
            if generation != self._audio_target_generation:
                self._logger.debug(
                    "Ignoring stale owner target for %s/%s",
                    event_type,
                    interaction_id,
                )
                return
            current = self._voice_session
            if (
                current is not None
                and current.active
                and not current.matches(interaction_id)
            ):
                self._logger.debug(
                    "Ignoring owner target from old voice session %s/%s",
                    event_type,
                    interaction_id,
                )
                return

            identity = (
                str(target.get("identity", "")).strip().lower()
                if isinstance(target, dict)
                else ""
            )
            target_id = (
                str(target.get("target_id", "")).strip()
                if isinstance(target, dict)
                else ""
            )
            vision_epoch = (
                str(target.get("vision_epoch", "")).strip()
                if isinstance(target, dict)
                else ""
            )
            if (
                identity != "owner"
                or target.get("identity_state") != "confirmed_known"
                or target.get("tracking_state") != "tracking"
                or not target_id
                or not vision_epoch
            ):
                self._logger.warn(
                    "Voice behavior %s not queued: current owner visual "
                    "target unavailable (%s)",
                    candidate.behavior_name,
                    event_type,
                )
                return

            bound_target = dict(target)
            bound_target.update({
                "target_type": "human",
                "identity": "owner",
            })
            candidate.target = bound_target
            candidate.target_required = True
            candidate.interactive = True
            candidate.interaction_mode = "interactive"
            candidate.params.update({
                "visual_route": "human",
                "target_identity": "owner",
                "target_track_id": bound_target.get("track_id"),
                "target_resolution": "vision_query_targets",
            })
            self._add_candidate(candidate)

        self._perception.request_owner_target(_resolved)

    def _on_audio_reaction(self, event_type: str, data: dict) -> None:
        """Consume one voice turn and enqueue a bounded PRAISE/SCOLD reaction."""
        if not self._intent_mapper.validate_audio_reaction_event(
            event_type,
            data,
        ):
            return

        interaction_id = str(data.get("interaction_id", "")).strip()
        utterance_id = str(data.get("utterance_id", "")).strip()
        event_key = (interaction_id, utterance_id, event_type)
        if self._audio_event_seen(event_key):
            return

        session = self._voice_session
        if (
            session is not None
            and session.active
            and not session.matches(interaction_id)
        ):
            self._remember_audio_event(event_key)
            self._logger.warn(
                "Voice reaction ignored: stale interaction_id=%r current=%r"
                % (interaction_id, session.interaction_id)
            )
            return

        active_voice_session = bool(
            session is not None and session.matches(interaction_id)
        )
        if active_voice_session:
            self._consume_voice_session_turn(session, "social_reaction")
        self._remember_audio_event(event_key)

        def _resolved(context: dict) -> None:
            current = self._voice_session
            if (
                current is not None
                and current.active
                and not current.matches(interaction_id)
            ):
                self._logger.debug(
                    "Ignoring stale visual result for audio reaction %s/%s",
                    event_type,
                    interaction_id,
                )
                return
            candidate = self._intent_mapper.map_audio_reaction(
                event_type,
                data,
                visual_route=str(context.get("route", "solo")),
                target=context.get("target"),
                active_voice_session=active_voice_session,
            )
            if candidate is not None:
                self._add_candidate(candidate)

        self._perception.request_emotion_context(_resolved)

    def _consume_voice_session_turn(self, session, kind: str) -> None:
        """Give one accepted command/reaction ownership of the voice turn."""
        session.consume_turn(kind)
        session.metadata["command_goal_terminal"] = False
        session.generation += 1
        self._voice_session_generation = max(
            self._voice_session_generation,
            session.generation,
        )
        interaction_id = session.interaction_id
        self._defer_queued_voice_emotions(interaction_id)
        self._candidate_pool.discard_where(
            lambda queued: (
                queued.get("params", {}).get("interaction_id")
                == interaction_id
                and queued.get("params", {}).get("session_role") in {
                    "wake_approach",
                    "voice_waiting_emotion",
                }
            )
        )
        self._release_voice_hold(session, reset_idle_timer=False)

    def _emit_social_emotion(self, emotion_name: str, trigger_event: str) -> None:
        """按视觉路由生成情绪候选（不污染情绪 state）。"""
        emo_event = _EMOTION_NAME_TO_EVENT.get(emotion_name)
        if emo_event is None:
            return

        def _resolved(context: dict) -> None:
            route = str(context.get("route", "solo"))
            target = context.get("target")
            candidate = self._intent_mapper.map_emotion_event(
                emo_event,
                {"value": 80.0, "visual_route": route},
                interactive=route == "human",
                target=target,
                visual_route=route,
            )
            if candidate is not None:
                candidate.params["social_trigger"] = trigger_event
                self._add_candidate(candidate)

        self._perception.request_emotion_context(_resolved)

    def _on_special_audio_event(self, event_type: str, data: dict) -> None:
        """直驱式特殊事件：饮食查询分流 / 打断 / PLAY 绑兴奋。"""
        if event_type == "EVT_VOICE_COMMAND_PLAY":
            # PLAY 绑定兴奋
            self._emit_social_emotion("Excite", event_type)
            return
        if event_type in (
            "EVT_VOICE_COMMAND_RESPOND_HUNGRY_QUERY",
            "EVT_VOICE_COMMAND_RESPOND_WANT_EAT_QUERY",
        ):
            self._route_hunger_query(event_type)
            return
        if event_type == "EVT_VOICE_COMMAND_RESPOND_EATING_QUERY":
            self._route_eating_query(event_type)
            return

    def _route_hunger_query(self, event_type: str) -> None:
        """按饥饿状态分流：饿→表示饿/想吃，不饿→表示不饿/不想吃。

        阈值 _HUNGER_ROUTE_THRESHOLD 为建议值，待与产品确认。
        """
        hunger = self._blackboard.need_module.get_need("Hunger")
        value = (
            float(hunger.current_value)
            if hunger is not None
            else float("nan")
        )
        hungry = math.isfinite(value) and value > _HUNGER_ROUTE_THRESHOLD
        if event_type == "EVT_VOICE_COMMAND_RESPOND_HUNGRY_QUERY":
            behavior_name = (
                "respond_hungry_yes" if hungry else "respond_hungry_no"
            )
        else:
            behavior_name = (
                "respond_want_eat_yes" if hungry else "respond_want_eat_no"
            )
        self._add_direct_behavior(behavior_name, event_type, timeout_sec=5.0)

    def _route_eating_query(self, event_type: str) -> None:
        """判定是否在执行进食行为：有则打断（记录恢复），再看主人。

        look_at_owner_brief 为 Lv1，会抢占 Lv3 进食；完成后由 _on_tick
        根据 self._eating_resume 重新入池被中断的进食行为。
        """
        current = self._blackboard.current_behavior
        eating = (
            current is not None
            and self._blackboard.current_status == STATUS_RUNNING
            and current.behavior_name in _EATING_BEHAVIORS
        )
        if eating:
            self._eating_resume = {"behavior_name": current.behavior_name}
        else:
            self._eating_resume = None
        self._add_direct_behavior("look_at_owner_brief", event_type, timeout_sec=5.0)

    def _add_direct_behavior(
        self,
        behavior_name: str,
        trigger_event: str,
        timeout_sec: float = 5.0,
    ) -> None:
        """直接构造一个 Lv1 直驱候选并入池（不经过 intent 白名单）。"""
        candidate = BehaviorCandidate(
            behavior_name=behavior_name,
            source="audio_direct",
            trigger_event=trigger_event,
            intent="",
            priority_level=1,
            sub_priority=1,
            intensity=80.0,
            confidence=0.9,
            ttl_sec=8.0,
            timeout_sec=timeout_sec,
            cooldown_sec=1.0,
            interrupt_policy="immediate",
            params={
                "source": "audio_direct",
                "trigger_event": trigger_event,
                "intent": "",
            },
        )
        self._add_candidate(candidate)

    def _publish_attention_control(self, enabled: bool, data: dict) -> None:
        session = self._voice_session
        session_id = (
            session.interaction_id
            if session is not None and session.active
            else ""
        )
        payload = {
            "schema_version": 1,
            "header": {"stamp": time.time(), "frame_id": "base_link"},
            "interaction_id": (
                self._attention_interaction_id
                or session_id
                or str(data.get("interaction_id", ""))
            ),
            "enabled": bool(enabled),
            "mode": self._attention_mode,
            "wake_angle": float(data.get("wake_angle", 0.0) or 0.0),
            "wake_confidence": float(
                data.get("wake_confidence", 0.0) or 0.0
            ),
            "reason": str(data.get("state_reason", "")),
            "phase": session.phase if session is not None else CLOSED,
            "target_ref": (
                dict(session.selected_target)
                if session is not None
                and isinstance(session.selected_target, dict)
                else None
            ),
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        if self._ros2_ready and hasattr(self, "_attention_pub"):
            from std_msgs.msg import String
            message = String()
            message.data = encoded
            self._attention_pub.publish(message)
        else:
            self._logger.info(
                "PUB %s: %s", self.ATTENTION_TRACKING_TOPIC, encoded
            )

    def _candidate_allowed_during_interaction(self, candidate: dict) -> bool:
        """Protect active voice motion while permitting safe emotion expression.

        Attention tracking is session state rather than an Action goal, so it
        does not otherwise participate in normal BT priority arbitration.
        Treat the motion-bearing voice phases as a virtual Lv1 behavior.  Once
        the session is WAITING, a visually resolved InPlaceWithHuman emotion
        may run so a silent wake/pose interaction does not leave the robot
        inert.
        Commands and safety work still win through normal priority. A command
        does not make the rest of its voice session an emotion embargo.
        """
        session = self._voice_session
        if not (
            (session is not None and session.active)
            or self._attention_interaction_id
        ):
            return True

        if int(candidate.get("priority_level", 6)) <= 1:
            return True

        params = candidate.get("params", {})
        return bool(
            self._voice_engagement.get("waiting_emotion_enabled", False)
            and session is not None
            and session.active
            and (
                not session.command_received
                or session.metadata.get("command_goal_terminal", False)
            )
            and (
                session.phase == WAITING
                or (
                    session.command_received
                    and session.metadata.get("command_goal_terminal", False)
                )
            )
            and self._attention_mode != "follow_owner"
            and isinstance(params, dict)
            and params.get("source") == "emotion"
            and params.get("interaction_mode") == "interactive"
            and params.get("interaction_variant") == "voice_waiting"
            and params.get("session_role") == "voice_waiting_emotion"
            and params.get("mobility_policy") == "in_place"
            and params.get("interaction_id") == session.interaction_id
            and params.get("visual_route") == "human"
            and isinstance(params.get("target"), dict)
            and str(candidate.get("behavior_name", "")).endswith(
                "InPlaceWithHuman"
            )
        )

    def _validate_wake_event(self, data: dict) -> dict | None:
        """Validate the formal audio wake contract before any side effect."""
        return validate_wake_event(data, logger=self._logger, now=time.time)

    def _audio_need_gate_allows(self, candidate) -> bool:
        """Apply a configured strict internal-need gate before side effects."""
        params = getattr(candidate, "params", None)
        if not isinstance(params, dict):
            return True
        gate = params.get("need_gate")
        if gate is None:
            return True
        if not isinstance(gate, dict):
            self._logger.error(
                "Voice command rejected: malformed need_gate for %s",
                getattr(candidate, "trigger_event", ""),
            )
            return False

        demand = str(gate.get("demand", "")).strip()
        operator = str(gate.get("operator", "")).strip()
        try:
            threshold = float(gate["threshold"])
        except (KeyError, TypeError, ValueError):
            threshold = float("nan")
        if (
            not demand
            or operator != "gt"
            or not math.isfinite(threshold)
            or not 0.0 <= threshold <= 100.0
        ):
            self._logger.error(
                "Voice command rejected: invalid need_gate for %s",
                getattr(candidate, "trigger_event", ""),
            )
            return False

        state = self._blackboard.need_module.get_need(demand)
        if state is None:
            self._logger.warn(
                "Voice command rejected: need %s is not initialized (%s)",
                demand,
                getattr(candidate, "trigger_event", ""),
            )
            return False
        value = float(state.current_value)
        if not math.isfinite(value) or not value > threshold:
            self._logger.info(
                "Voice command gated: %s=%.1f must be > %.1f (%s)",
                demand,
                value,
                threshold,
                getattr(candidate, "trigger_event", ""),
            )
            return False

        gate.update({
            "observed_value": value,
            "observed_level": str(state.level),
            "observed_at": float(state.last_update),
            "passed": True,
        })
        self._logger.info(
            "Voice command need gate passed: %s=%.1f > %.1f (%s)",
            demand,
            value,
            threshold,
            getattr(candidate, "trigger_event", ""),
        )
        return True

    def _audio_event_seen(self, key: tuple[str, str, str]) -> bool:
        return key in self._seen_audio_event_keys

    def _remember_audio_event(self, key: tuple[str, str, str]) -> None:
        if key in self._seen_audio_event_keys:
            return
        while len(self._seen_audio_event_order) >= 256:
            expired = self._seen_audio_event_order.popleft()
            self._seen_audio_event_keys.discard(expired)
        self._seen_audio_event_order.append(key)
        self._seen_audio_event_keys.add(key)

    def _request_voice_hold(self, session: VoiceInteractionSession) -> None:
        # An empty token is the local tombstone written by
        # _release_voice_hold().  Once an explicit voice command supersedes
        # wake engagement, that released lease must never be recreated.
        if (
            self._voice_session is not session
            or not session.active
            or session.hold_request_pending
            or session.command_received
            or session.phase not in (
                ORIENTING, AWAITING_IDENTITY, ACQUIRING_TARGET, APPROACHING
            )
            or not str(session.hold_token).strip()
        ):
            return
        lease_sec = float(self._voice_engagement.get("hold_lease_sec", 6.0))
        generation = session.generation
        interaction_id = session.interaction_id
        hold_token = str(session.hold_token).strip()
        session.hold_request_pending = True
        session.last_hold_attempted_at = time.monotonic()

        def _held(result: dict | None) -> None:
            current = self._voice_session
            hold_succeeded = bool(
                isinstance(result, dict) and result.get("ok", True)
            )
            request_is_current = bool(
                current is session
                and current.matches(interaction_id, generation)
                and not current.command_received
                and current.hold_request_pending
                and str(current.hold_token).strip() == hold_token
                and current.phase in (
                    ORIENTING, ACQUIRING_TARGET, APPROACHING
                )
            )
            if not request_is_current:
                # The release that ended wake engagement may have reached
                # Voice before this older hold request.  If the older request
                # then succeeds, release the captured token once more so a
                # stale lease cannot delay the session's idle transition.
                if hold_succeeded:
                    reset_idle_timer = bool(
                        current is session
                        and current.phase == WAITING
                        and not current.command_received
                    )
                    if not self._voice_session_client.release(
                        interaction_id,
                        hold_token,
                        reset_idle_timer=reset_idle_timer,
                    ):
                        self._logger.warn(
                            "Late Voice hold cleanup unavailable: "
                            "interaction_id=%s" % interaction_id
                        )
                return
            current.hold_request_pending = False
            current.hold_active = hold_succeeded
            if current.hold_active:
                current.last_hold_renewed_at = time.monotonic()
            else:
                self._logger.warn(
                    "Voice hold rejected: interaction_id=%s"
                    % current.interaction_id
                )

        scheduled = self._voice_session_client.hold(
            interaction_id,
            hold_token,
            lease_sec=lease_sec,
            callback=_held,
        )
        if not scheduled:
            session.hold_request_pending = False
            session.hold_active = False
            self._logger.warn(
                "Voice hold unavailable: interaction_id=%s"
                % session.interaction_id
            )

    def _renew_voice_hold_if_due(self) -> None:
        session = self._voice_session
        if (
            session is None
            or not session.active
            or session.command_received
            or not str(session.hold_token).strip()
            or session.phase not in (
                ORIENTING, ACQUIRING_TARGET, APPROACHING
            )
        ):
            return
        interval = float(
            self._voice_engagement.get("hold_renew_interval_sec", 2.0)
        )
        last_attempt_or_success = max(
            session.last_hold_attempted_at,
            session.last_hold_renewed_at,
        )
        if (
            not session.hold_request_pending
            and time.monotonic() - last_attempt_or_success >= interval
        ):
            self._request_voice_hold(session)

    def _expire_wake_target_query_if_due(self) -> None:
        """Fail a hung visual query closed and resume the voice idle timer."""
        session = self._voice_session
        if session is None or session.phase != ACQUIRING_TARGET:
            return
        started_at = session.metadata.get("target_query_started_at")
        if not isinstance(started_at, (int, float)):
            return
        timeout_sec = max(
            0.1,
            float(self._voice_engagement.get("acquire_timeout_sec", 2.0)),
        )
        if time.monotonic() - float(started_at) < timeout_sec:
            return

        # Invalidate the captured service callback before changing phase.  A
        # late Vision response must not enqueue motion after we started
        # waiting for speech.
        session.generation += 1
        self._voice_session_generation = max(
            self._voice_session_generation,
            session.generation,
        )
        session.metadata.pop("target_query_started_at", None)
        self._enter_voice_waiting(session, reason="visual_query_timeout")

    def _expire_wake_identity_if_due(self) -> None:
        session = self._voice_session
        if session is None or session.phase != AWAITING_IDENTITY:
            return
        started_at = session.metadata.get("identity_wait_started_at")
        if not isinstance(started_at, (int, float)):
            return
        timeout_sec = max(0.1, float(
            self._voice_engagement.get("wake_identity_timeout_sec", 3.0)
        ))
        if time.monotonic() - float(started_at) >= timeout_sec:
            self._enter_voice_waiting(session, reason="wake_identity_timeout")

    def _continue_wake_after_identity(self, session: VoiceInteractionSession) -> None:
        if session.phase != AWAITING_IDENTITY or session.command_received:
            return
        role = session.metadata.get("wake_speaker_role")
        status = session.metadata.get("wake_speaker_status")
        if role in ("owner", "family") and status == "matched":
            self._request_wake_speaker(session)
        elif status != "pending":
            self._enter_voice_waiting(session, reason="wake_identity_%s" % status)

    def _release_voice_hold(
        self,
        session: VoiceInteractionSession,
        *,
        reset_idle_timer: bool,
    ) -> None:
        if not session.hold_token:
            return
        hold_token = session.hold_token
        session.hold_token = ""
        session.hold_active = False
        session.hold_request_pending = False
        if not self._voice_session_client.release(
            session.interaction_id,
            hold_token,
            reset_idle_timer=reset_idle_timer,
        ):
            self._logger.warn(
                "Voice hold release unavailable: interaction_id=%s"
                % session.interaction_id
            )

    def _close_voice_session(self, interaction_id: str, *, reason: str) -> None:
        session = self._voice_session
        if session is None or not session.matches(interaction_id):
            return
        session.phase = CLOSED
        session.generation += 1
        self._voice_session_generation = max(
            self._voice_session_generation, session.generation
        )
        self._release_voice_hold(session, reset_idle_timer=False)
        self._defer_queued_voice_emotions(interaction_id)
        removed = self._candidate_pool.discard_session(interaction_id)
        self._runtime.discard_pending_interaction(interaction_id)
        canceled = self._runtime.cancel_current_interaction(
            interaction_id,
            reason="voice_session_closed:%s" % reason,
        )
        self._publish_attention_control(False, {
            "interaction_id": interaction_id,
            "state_reason": reason,
        })
        self._attention_interaction_id = ""
        self._attention_mode = "face_body_centering"
        self._pending_emotion_retry_at.clear()
        self._flush_pending_emotions()
        self._logger.info(
            "Voice session closed: id=%s reason=%s queued_removed=%d running=%s"
            % (interaction_id, reason, removed, bool(canceled))
        )

    def _enter_voice_waiting(
        self,
        session: VoiceInteractionSession,
        *,
        reason: str,
    ) -> None:
        current = self._voice_session
        if current is None or not current.matches(
            session.interaction_id, session.generation
        ):
            return
        current.phase = WAITING
        # Unknown and stranger wakes remain stationary after the sound turn.
        approach_finished = reason == "arrived"
        self._attention_interaction_id = (
            current.interaction_id if approach_finished else ""
        )
        self._attention_mode = "face_body_centering"
        self._publish_attention_control(approach_finished, {
            "interaction_id": current.interaction_id,
            # respond_owner_call already consumed the microphone bearing.  A
            # second fallback turn here would rotate the chassis twice.
            "wake_angle": 0.0,
            "wake_confidence": current.wake_confidence,
            "state_reason": reason,
        })
        self._release_voice_hold(current, reset_idle_timer=True)
        self._pending_emotion_retry_at.clear()
        self._flush_pending_emotions()
        self._logger.info(
            "Voice session waiting: id=%s reason=%s target=%s"
            % (
                current.interaction_id,
                reason,
                (
                    current.selected_target.get("target_id")
                    if isinstance(current.selected_target, dict) else "none"
                ),
            )
        )

    def _request_wake_speaker(
        self,
        session: VoiceInteractionSession,
    ) -> None:
        session.phase = ACQUIRING_TARGET
        session.metadata["target_query_started_at"] = time.monotonic()
        generation = session.generation
        self._perception.request_wake_speaker(
            lambda target: self._on_wake_speaker_resolved(
                session.interaction_id,
                generation,
                target,
            ),
            # respond_owner_call already turned the camera toward the source.
            reference_bearing_deg=0.0,
            min_confidence=float(
                self._voice_engagement.get("target_min_confidence", 0.3)
            ),
            max_age_ms=float(
                self._voice_engagement.get("target_max_age_ms", 300.0)
            ),
            max_bearing_error_deg=float(
                self._voice_engagement.get(
                    "target_max_bearing_error_deg", 25.0
                )
            ),
            max_snapshot_age_ms=float(
                self._voice_engagement.get(
                    "snapshot_max_age_ms", 500.0
                )
            ),
        )

    def _on_wake_speaker_resolved(
        self,
        interaction_id: str,
        generation: int,
        target: dict | None,
    ) -> None:
        session = self._voice_session
        if (
            session is None
            or not session.matches(interaction_id, generation)
            or session.phase != ACQUIRING_TARGET
            or session.command_received
        ):
            return
        session.metadata.pop("target_query_started_at", None)
        if not isinstance(target, dict):
            self._enter_voice_waiting(session, reason="no_visual_target")
            return

        session.selected_target = dict(target)
        target_id = str(target.get("target_id", ""))
        if (target.get("target_type") != "human"
                or not str(target.get("vision_epoch", ""))
                or not target_id.startswith(str(target["vision_epoch"]) + ":human:")):
            self._enter_voice_waiting(session, reason="invalid_visual_target")
            return
        # Existing Vision identity can veto a definite contradiction.  An
        # unknown face remains eligible because Vision confirmation is optional.
        if target.get("identity_state") == "confirmed_known":
            visual_identity = str(target.get("identity", ""))
            if visual_identity != session.metadata.get("wake_speaker_id"):
                self._enter_voice_waiting(session, reason="identity_conflict")
                return

        candidate = self._intent_mapper.build_voice_approach_candidate(
            interaction_id=interaction_id,
            target=target,
            wake_id=str(session.metadata.get("wake_id", "")),
            speaker_id=str(session.metadata.get("wake_speaker_id", "")),
            speaker_role=str(session.metadata.get("wake_speaker_role", "")),
            speaker_status=str(session.metadata.get("wake_speaker_status", "")),
            stand_off_distance_m=float(
                self._voice_engagement.get("stand_off_distance_m", 1.5)
            ),
            timeout_sec=float(
                self._voice_engagement.get("approach_timeout_sec", 160.0)
            ),
            ttl_sec=float(
                self._voice_engagement.get(
                    "approach_candidate_ttl_sec", 3.0
                )
            ),
        )
        if self._add_candidate(candidate):
            session.phase = APPROACHING
        else:
            self._enter_voice_waiting(
                session, reason="approach_candidate_suppressed"
            )

    def _handle_voice_behavior_terminal(
        self,
        active,
        completed,
    ) -> None:
        session = self._voice_session
        if session is None or not session.active:
            return
        interaction_id = str(active.params.get("interaction_id", "")).strip()
        active_wake_id = str(active.params.get("wake_id", ""))
        current_wake_id = str(session.metadata.get("wake_id", ""))
        if (active.behavior_name == "respond_owner_call"
                and (interaction_id != session.interaction_id
                     or active_wake_id != current_wake_id)):
            replacement = session.metadata.pop("pending_wake_candidate", None)
            if replacement is not None and session.phase == ORIENTING:
                self._add_candidate(replacement)
            return
        if not session.matches(interaction_id):
            return
        if (active.behavior_name in ("respond_owner_call", "approach_voice_caller")
                and active_wake_id != current_wake_id):
            return
        if active.params.get("session_role") in {
            "voice_command", "voice_social_reaction",
        }:
            session.metadata["command_goal_terminal"] = True
            self._pending_emotion_retry_at.clear()
            self._flush_pending_emotions()
        status = str(getattr(completed, "status", "")).upper()
        if active.behavior_name == "respond_owner_call":
            if session.command_received:
                return
            if status in ("SUCCESS", "COMPLETED"):
                session.phase = AWAITING_IDENTITY
                session.metadata["identity_wait_started_at"] = time.monotonic()
                self._continue_wake_after_identity(session)
            else:
                self._enter_voice_waiting(
                    session, reason="wake_orientation_%s" % status.lower()
                )
        elif active.behavior_name == "approach_voice_caller":
            if session.command_received:
                return
            reason = str(getattr(completed, "reason", "")).strip()
            self._enter_voice_waiting(
                session,
                reason=(
                    "arrived" if status in ("SUCCESS", "COMPLETED")
                    else "approach_%s%s" % (
                        status.lower(),
                        ":%s" % reason if reason else "",
                    )
                ),
            )

    # ── Candidate Generation (via intent_mapper) ──────────────────────────

    def _invalidate_emotion_visual_request(self, emotion_name: str) -> int:
        generation = self._emotion_visual_generation.get(emotion_name, 0) + 1
        self._emotion_visual_generation[emotion_name] = generation
        return generation

    def _voice_emotion_can_resolve(self) -> bool:
        """Whether a fresh emotion target may be resolved for this voice phase."""
        current = self._blackboard.current_behavior
        if (
            current is not None
            and self._blackboard.current_status == STATUS_RUNNING
            and current.priority_level < 5
        ):
            return False
        if any(
            item["priority_level"] < 5
            and self._candidate_allowed_during_interaction(item)
            for item in self._candidate_pool.candidates
        ):
            return False
        session = getattr(self, "_voice_session", None)
        if session is None or not session.active:
            return True
        if (
            (
                session.command_received
                and not session.metadata.get("command_goal_terminal", False)
            )
            or not (
                session.phase == WAITING
                or (
                    session.command_received
                    and session.metadata.get("command_goal_terminal", False)
                )
            )
            or self._attention_mode == "follow_owner"
            or not self._voice_engagement.get("waiting_emotion_enabled", False)
        ):
            return False
        return True

    def _defer_queued_voice_emotions(self, interaction_id: str) -> None:
        """Keep state-backed emotions before queued or reserved work is cleared."""
        pending = getattr(self, "_pending_emotion_edges", None)
        if pending is None:
            return
        for candidate in getattr(self._candidate_pool, "candidates", ()):
            params = candidate.get("params", {})
            if (
                params.get("interaction_id") != interaction_id
                or params.get("session_role") != "voice_waiting_emotion"
            ):
                continue
            emotion_name = str(params.get("source_emotion", ""))
            if self._blackboard.emotion_module.is_triggered(emotion_name):
                pending[emotion_name] = str(params.get("trigger_event", ""))

        # A selected replacement can wait behind another Goal's real cancel
        # Result. It is no longer in CandidatePool, but has not been sent yet.
        blackboard = getattr(self, "_blackboard", None)
        reserved = getattr(blackboard, "active_behavior", None)
        if reserved is None:
            return
        params = reserved.params
        if (
            params.get("interaction_id") != interaction_id
            or params.get("session_role") != "voice_waiting_emotion"
        ):
            return
        emotion_name = str(params.get("source_emotion", ""))
        if blackboard.emotion_module.is_triggered(emotion_name):
            pending[emotion_name] = str(params.get("trigger_event", ""))
        blackboard.active_behavior = None
        self._candidate_pool.release_inflight(
            reserved.behavior_name, reserved.behavior_id,
        )

    def _flush_pending_emotions(self) -> None:
        """Recheck authoritative state and resolve fresh context after a hold."""
        pending = getattr(self, "_pending_emotion_edges", None)
        if not pending or not self._voice_emotion_can_resolve():
            return
        now = time.monotonic()
        for emotion_name, trigger_event in list(pending.items()):
            if now < self._pending_emotion_retry_at.get(emotion_name, 0.0):
                continue
            pending.pop(emotion_name, None)
            self._pending_emotion_retry_at.pop(emotion_name, None)
            if self._blackboard.emotion_module.is_triggered(emotion_name):
                self._request_contextual_emotion_candidate(
                    emotion_name,
                    trigger_event=trigger_event,
                )

    def _request_contextual_emotion_candidate(
        self,
        emotion_name: str,
        *,
        trigger_event: str,
    ) -> None:
        """Resolve person presence before creating an emotion candidate."""
        if not self._voice_emotion_can_resolve():
            self._pending_emotion_edges[emotion_name] = trigger_event
            return
        generation = self._emotion_visual_generation.get(emotion_name, 0)

        def _resolved(context: dict) -> None:
            stale = (
                generation
                != self._emotion_visual_generation.get(emotion_name, 0)
                or not self._blackboard.emotion_module.is_triggered(
                    emotion_name
                )
            )
            if stale:
                self._logger.debug(
                    "Ignoring stale visual result for %s/%s"
                    % (emotion_name, trigger_event)
                )
                return

            session = getattr(self, "_voice_session", None)
            if session is not None and session.active and (
                not self._voice_emotion_can_resolve()
                or context.get("route") != "human"
                or not isinstance(context.get("target"), dict)
            ):
                self._pending_emotion_edges[emotion_name] = trigger_event
                self._pending_emotion_retry_at[emotion_name] = (
                    time.monotonic() + 2.0
                )
                return

            self._pending_emotion_edges.pop(emotion_name, None)
            self._pending_emotion_retry_at.pop(emotion_name, None)
            self._generate_emotion_candidate(
                emotion_name,
                trigger_event=trigger_event,
                signal_value=self._blackboard.emotion_module.get_value(
                    emotion_name
                ),
                visual_route=str(context["route"]),
                target=context.get("target"),
            )

        self._perception.request_emotion_context(_resolved)

    def _generate_emotion_candidate(
        self,
        emotion_name: str,
        trigger_event: str = "",
        signal_value: float = None,
        visual_route: str = "solo",
        target: dict | None = None,
        continuation: bool = False,
    ) -> None:
        """Generate behavior candidate from emotion signal_event via intent_mapper.

        Person presence has already been resolved asynchronously by the visual
        service. ``human`` selects the interactive action pool; ``solo``
        selects the no-person pool.
        """
        if signal_value is not None:
            em_val = float(signal_value)
            self._blackboard.emotion_module.set_emotion(emotion_name, em_val)
        else:
            em_state = self._blackboard.emotion_module.get_emotion(emotion_name)
            if em_state is None:
                self._logger.debug(f"No value for {emotion_name}, skipping candidate")
                return
            em_val = em_state.current_value

        behavior_context = ""
        context_params: dict = {}
        session = getattr(self, "_voice_session", None)
        voice_engagement = getattr(self, "_voice_engagement", {})
        if session is not None and session.active:
            if (
                not voice_engagement.get("waiting_emotion_enabled", False)
                or (
                    session.command_received
                    and not session.metadata.get("command_goal_terminal", False)
                )
                or not (
                    session.phase == WAITING
                    or (
                        session.command_received
                        and session.metadata.get("command_goal_terminal", False)
                    )
                )
                or self._attention_mode == "follow_owner"
                or visual_route != "human"
                or not isinstance(target, dict)
            ):
                return
            behavior_context = "voice_waiting"
            context_params = {
                "interaction_variant": "voice_waiting",
                "interaction_id": session.interaction_id,
                "session_role": "voice_waiting_emotion",
                "mobility_policy": "in_place",
                "lifecycle_scope": "behavior",
            }

        candidate = self._intent_mapper.map_emotion_event(
            trigger_event,
            {"value": em_val, "visual_route": visual_route},
            interactive=visual_route == "human",
            target=target,
            visual_route=visual_route,
            behavior_context=behavior_context,
            context_params=context_params,
        )

        if candidate is not None:
            if continuation:
                candidate.params["emotion_continuation"] = True
            self._add_candidate(candidate)
        else:
            self._logger.debug(
                "Emotion event %s → no candidate (unmapped event_type)",
                trigger_event,
            )

    def _invalidate_need_visual_request(self, need_name: str) -> int:
        generation = self._need_visual_generation.get(need_name, 0) + 1
        self._need_visual_generation[need_name] = generation
        return generation

    def _request_contextual_need_candidate(
        self,
        need_name: str,
        value: float,
        *,
        trigger_event: str,
        level: str,
    ) -> None:
        """Ask vision to route Hunger/Social/Exploration candidates."""
        generation = self._need_visual_generation.get(need_name, 0)

        def _resolved(context: dict | None) -> None:
            state = self._blackboard.need_module.get_need(need_name)
            stale = (
                generation != self._need_visual_generation.get(need_name, 0)
                or state is None
                or not state.triggered
                or state.level_event != trigger_event
            )
            if stale:
                self._logger.debug(
                    "Ignoring stale visual result for %s/%s"
                    % (need_name, trigger_event)
                )
                return
            if not context or not context.get("route"):
                self._logger.info(
                    "%s suppressed: vision found no eligible target"
                    % trigger_event
                )
                return
            self._generate_need_candidate(
                need_name,
                value,
                trigger_event=trigger_event,
                level=level,
                visual_route=str(context["route"]),
                target=context.get("target"),
            )

        if need_name == "Hunger":
            self._perception.request_hunger_context(_resolved)
        elif need_name == "Social":
            self._perception.request_social_target(_resolved)
        else:
            self._perception.request_exploration_context(_resolved)

    def _generate_need_candidate(
        self,
        need_name: str,
        value: float,
        trigger_event: str = "",
        level: str = "",
        visual_route: str | None = None,
        target: dict | None = None,
    ) -> None:
        """Generate a need candidate from an exact signal ``event_type``."""
        candidate = self._intent_mapper.map_need_event(
            trigger_event,
            {
                "demand": need_name,
                "value": value,
                "level": level,
                "visual_route": visual_route,
                "target": target,
            },
        )

        if candidate is not None:
            self._add_candidate(candidate)
        else:
            self._logger.debug(
                "Need event %s → no candidate (unmapped event_type)",
                trigger_event,
            )

    def _add_candidate(self, candidate) -> bool:
        """Add a candidate unless its behavior is queued or in-flight."""
        dedup_key = candidate.dedup_key
        bhv_name = candidate.behavior_name
        if self._is_duplicate_or_running(bhv_name, dedup_key):
            self._logger.debug(
                "Candidate suppressed: %s already queued/in-flight",
                bhv_name,
            )
            return False
        pool_dict = candidate.to_pool_dict()
        pool_dict.setdefault("dedup_key", dedup_key)
        added = self._candidate_pool.add(**pool_dict)
        if not added:
            self._logger.debug(
                "Candidate suppressed: %s already queued/in-flight",
                bhv_name,
            )
        return added

    def _is_duplicate_or_running(self, behavior_name: str,
                                  dedup_key: tuple = None) -> bool:
        """Check for duplicates in pool or currently executing."""
        if self._candidate_pool.is_duplicate(behavior_name, dedup_key):
            return True
        if (self._blackboard.current_behavior is not None
                and self._blackboard.current_status == STATUS_RUNNING
                and self._blackboard.current_behavior.behavior_name == behavior_name):
            return True
        return False

    # ── Tick Logic ───────────────────────────────────────────────────────

    def _on_tick(self):
        """Run one transport-independent decision cycle."""
        self._renew_action_goal_lease()
        self._expire_wake_identity_if_due()
        self._expire_wake_target_query_if_due()
        self._renew_voice_hold_if_due()
        self._dispatch_due_emotion_continuation()
        self._flush_pending_emotions()
        current_before = self._blackboard.current_behavior
        outcome = self._runtime.tick()

        if outcome.started_behavior is not None:
            source_emotion = str(
                outcome.started_behavior.params.get("source_emotion", "")
            )
            session = self._emotion_continuations.get(source_emotion)
            if session is not None:
                session["cycles"] = int(session.get("cycles", 0)) + 1

        if outcome.completed_event is not None and current_before is not None:
            if current_before.behavior_id == outcome.completed_event.behavior_id:
                self._handle_voice_behavior_terminal(
                    current_before,
                    outcome.completed_event,
                )
                self._schedule_emotion_continuation(
                    str(current_before.params.get("source_emotion", "")),
                    str(outcome.completed_event.status),
                )
            self._flush_pending_emotions()

        # RESPOND_EATING_QUERY 打断进食后，看向主人完成时恢复进食。
        if (
            outcome.completed_event is not None
            and current_before is not None
            and current_before.behavior_name == "look_at_owner_brief"
            and self._eating_resume
        ):
            resume = self._eating_resume
            self._eating_resume = None
            self._add_direct_behavior(
                resume["behavior_name"],
                "EVT_VOICE_COMMAND_RESPOND_EATING_QUERY",
                timeout_sec=30.0,
            )

        # A preemption can produce an INTERRUPTED result and a new STARTED
        # event in the same tick. Publish the old terminal event first.
        if outcome.completed_event is not None:
            self._publish_result(
                outcome.completed_event.behavior_name,
                getattr(outcome.completed_event, "status", "SUCCESS"),
                metadata=getattr(outcome.completed_event, "metadata", {}),
            )

        if outcome.started_behavior is not None:
            self._publish_started(outcome.started_behavior.behavior_name)

    def _renew_action_goal_lease(self):
        """Renew the active long Goal using its independent behavior ID."""
        active = self._blackboard.current_behavior
        if (not self._ros2_ready or not hasattr(self, "_goal_lease_pub")
                or active is None
                or active.behavior_name not in ("follow_owner", "play_alone")):
            return
        from std_msgs.msg import String
        message = String()
        message.data = json.dumps({
            "schema_version": 1,
            "goal_id": active.behavior_id,
            "behavior_id": active.behavior_id,
        })
        self._goal_lease_pub.publish(message)

    def _start_emotion_continuation(self, emotion_name: str) -> None:
        """Open a bounded continuation session for a new emotion edge."""
        if (
            not self._emotion_continuation_enabled
            or emotion_name not in self._emotion_continuation_emotions
        ):
            return
        self._emotion_continuations[emotion_name] = {
            "started_at": time.monotonic(),
            "cycles": 0,
            # Wait for the initial edge-triggered action to finish.
            "next_at": float("inf"),
        }

    def _stop_emotion_continuation(self, emotion_name: str) -> None:
        self._emotion_continuations.pop(emotion_name, None)
        self._emotion_continuation_requests.discard(emotion_name)

    def _schedule_emotion_continuation(
        self,
        emotion_name: str,
        status: str,
    ) -> None:
        """Schedule another expression after a successful/interrupted cycle."""
        session = self._emotion_continuations.get(emotion_name)
        if session is None:
            return
        if status not in ("SUCCESS", "COMPLETED", "CANCELED", "INTERRUPTED"):
            self._logger.info(
                "Emotion continuation stopped: %s status=%s",
                emotion_name,
                status,
            )
            self._stop_emotion_continuation(emotion_name)
            return
        if not self._blackboard.emotion_module.is_triggered(emotion_name):
            self._stop_emotion_continuation(emotion_name)
            return

        now = time.monotonic()
        elapsed = now - float(session.get("started_at", now))
        cycles = int(session.get("cycles", 0))
        if (
            cycles >= self._emotion_continuation_max_cycles
            or elapsed >= self._emotion_continuation_max_duration_sec
        ):
            self._logger.info(
                "Emotion continuation limit reached: %s cycles=%d elapsed=%.1fs",
                emotion_name,
                cycles,
                elapsed,
            )
            self._stop_emotion_continuation(emotion_name)
            return
        session["next_at"] = now + self._emotion_continuation_interval_sec
        self._logger.debug(
            "Emotion continuation scheduled: %s cycle=%d/%d delay=%.1fs",
            emotion_name,
            cycles + 1,
            self._emotion_continuation_max_cycles,
            self._emotion_continuation_interval_sec,
        )

    def _dispatch_due_emotion_continuation(self) -> None:
        """Enqueue the highest-priority due emotion while the executor is idle."""
        if not self._emotion_continuation_enabled:
            return
        if (
            self._blackboard.current_behavior is not None
            and self._blackboard.current_status == STATUS_RUNNING
        ):
            return

        now = time.monotonic()
        due: list[str] = []
        for emotion_name, session in list(self._emotion_continuations.items()):
            if not self._blackboard.emotion_module.is_triggered(emotion_name):
                self._stop_emotion_continuation(emotion_name)
                continue
            elapsed = now - float(session.get("started_at", now))
            if elapsed >= self._emotion_continuation_max_duration_sec:
                self._stop_emotion_continuation(emotion_name)
                continue
            if (
                emotion_name not in self._emotion_continuation_requests
                and now >= float(session.get("next_at", float("inf")))
            ):
                due.append(emotion_name)
        if not due:
            return

        emotion_name = min(
            due,
            key=lambda name: (
                EMOTION_PRIORITY.get(name, 50),
                -self._blackboard.emotion_module.get_value(name),
            ),
        )
        session = self._emotion_continuations[emotion_name]
        session["next_at"] = float("inf")
        self._emotion_continuation_requests.add(emotion_name)
        self._logger.debug(
            "Emotion continuation resolving context: %s value=%.1f",
            emotion_name,
            self._blackboard.emotion_module.get_value(emotion_name),
        )
        trigger_event = next(
            event
            for event, name in EMOTION_V2_EVENT_TO_NAME.items()
            if name == emotion_name
        )

        def _resolved(context: dict) -> None:
            self._emotion_continuation_requests.discard(emotion_name)
            if (
                emotion_name not in self._emotion_continuations
                or not self._blackboard.emotion_module.is_triggered(
                    emotion_name
                )
            ):
                return
            self._generate_emotion_candidate(
                emotion_name,
                trigger_event=trigger_event,
                signal_value=self._blackboard.emotion_module.get_value(
                    emotion_name
                ),
                visual_route=str(context["route"]),
                target=context.get("target"),
                continuation=True,
            )

        self._perception.request_emotion_context(_resolved)

    # ── Result Publishing ────────────────────────────────────────────────

    def _publish_started(self, behavior_name: str):
        """Publish STARTED event to /behavior/result_event."""
        payload = self._result_mapper.build_started_event(behavior_name)
        if payload:
            self._publish(self.RESULT_EVENT_TOPIC, payload)

    def _publish_result(self, behavior_name: str, status: str,
                        metadata: dict | None = None):
        """Publish result event to /behavior/result_event."""
        payload = self._result_mapper.build_result_event(
            behavior_name, status, metadata=metadata)
        if payload:
            self._publish(self.RESULT_EVENT_TOPIC, payload)

    def _publish(self, topic: str, payload: str):
        """Publish a string message. Uses ROS2 if available, prints otherwise."""
        if HAS_ROS2 and hasattr(self, '_result_pub') and topic == self.RESULT_EVENT_TOPIC:
            from std_msgs.msg import String
            msg = String()
            msg.data = payload
            self._result_pub.publish(msg)
        else:
            self._logger.info(f"PUB {topic}: {payload}")

    # ── Public API (for standalone demo) ──────────────────────────────────

    def add_signal(self, behavior_name: str, priority_level: int,
                   value: float = 50.0, need_type: str = "external",
                   source_emotion: str = "", params: dict = None,
                   timeout_sec: float = 30.0, cooldown_sec: float = 0.0):
        """Add a behavior candidate signal (used by standalone demo)."""
        self._candidate_pool.add(
            behavior_name=behavior_name,
            priority_level=priority_level,
            value=value, need_type=need_type,
            source_emotion=source_emotion,
            params=params or {},
            timeout_sec=timeout_sec, cooldown_sec=cooldown_sec,
        )

    def update_emotion_state(self, emotion_data: dict):
        """Update emotion state without generating a behavior candidate."""
        emotions = emotion_data.get("emotions", emotion_data)
        for name, emotion_info in emotions.items():
            value = (
                emotion_info.get("value")
                if isinstance(emotion_info, dict)
                else emotion_info
            )
            if isinstance(value, (int, float)):
                self._blackboard.emotion_module.set_emotion(name, float(value))
            if (
                isinstance(emotion_info, dict)
                and isinstance(emotion_info.get("triggered"), bool)
            ):
                self._blackboard.emotion_module.set_triggered(
                    name,
                    emotion_info["triggered"],
                )

    def destroy_node(self):
        self._running = False
        session = getattr(self, "_voice_session", None)
        if session is not None and session.active:
            self._close_voice_session(
                session.interaction_id,
                reason="behavior_tree_shutdown",
            )
        self._runtime.cancel_current_for_shutdown()
        tick_thread = getattr(self, "_tick_thread", None)
        if tick_thread is not None and tick_thread.is_alive():
            import threading
            if tick_thread is not threading.current_thread():
                tick_thread.join(timeout=self.TICK_RATE * 2)
        if hasattr(self, '_result_pub'):
            self._result_pub = None
        if self._ros2_ready:
            super().destroy_node()

    # ── Accessors for standalone demo ────────────────────────────────────

    @property
    def blackboard(self):
        return self._blackboard

    @property
    def candidate_pool(self):
        return self._candidate_pool

    @property
    def perception(self):
        return self._perception


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    if HAS_ROS2:
        import rclpy
        import signal
        from rclpy.signals import SignalHandlerOptions
        # Session release and goal cancellation need a live ROS context during
        # destroy_node. Python handles SIGINT before context shutdown here.
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        def interrupt(_signum, _frame):
            raise KeyboardInterrupt
        previous_term = signal.signal(signal.SIGTERM, interrupt)
        node = None
        try:
            node = BehaviorTreeRosNode()
            rclpy.spin(node)
        except KeyboardInterrupt:
            pass
        finally:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
            signal.signal(signal.SIGTERM, previous_term)
    else:
        print("ROS2 not available. Use standalone demo instead:")
        print("  uv run python -m marsdog_behavior.standalone_demo")


if __name__ == "__main__":
    main()
