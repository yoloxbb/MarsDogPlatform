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
import time

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
from .intent_mapper import IntentMapper
from .runtime import BehaviorRuntime


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
        self._perception = PerceptionClientAdapter(self)
        self._blackboard.perception_client = self._perception
        self._perception.set_on_audio_direct(self._on_audio_direct)

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
        self._emotion_heartbeat = 0
        self._need_heartbeat = 0
        self._emotion_visual_generation: dict[str, int] = {}
        self._need_visual_generation: dict[str, int] = {}
        self._attention_interaction_id = ""
        self._attention_mode = "face_body_centering"

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

            self._emotion_heartbeat += 1
            if self._emotion_heartbeat % 30 == 1:
                states = ', '.join(
                    f"{name}={'on' if self._blackboard.emotion_module.is_triggered(name) else 'off'}"
                    for name in (
                        "Joy", "Excite", "Anxiety",
                        "Fear", "Curious", "Calm",
                    )
                )
                self._logger.debug(f"/emotion/state heartbeat: [{states}]")
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

            self._logger.info(f"/emotion/signal_event: {event_type}")

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
                signal_value=float(signal_value),
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

            self._need_heartbeat += 1
            if self._need_heartbeat % 30 == 1:
                ev = ', '.join(
                    f"{n}={self._blackboard.need_module.level_events.get(n, '?')}"
                    for n in ["Hunger", "Bladder", "Sleepiness", "Cleanliness",
                              "Energy", "Social", "Exploration"])
                self._logger.debug(f"/internal_need/state heartbeat: [{ev}]")
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

            self._logger.info(
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

    def _on_audio_direct(self, event_type: str, data: dict) -> None:
        """Handle event-type-driven audio events via the intent pipeline.

        Pipeline: event_type → category → intent → action_pool → behavior_name
        """
        if event_type == "EVT_VOICE_CALL_NAME":
            interaction_id = str(data.get("interaction_id", "")).strip()
            if not interaction_id:
                interaction_id = "legacy-%d" % int(time.time() * 1000)
            self._attention_interaction_id = interaction_id
            self._attention_mode = "face_body_centering"
            self._publish_attention_control(True, data)
            return

        if event_type == "EVT_STATE_CHANGED":
            event_interaction_id = str(data.get("interaction_id", "")).strip()
            if (
                data.get("state") == "idle"
                and self._attention_interaction_id
                and (
                    not event_interaction_id
                    or event_interaction_id == self._attention_interaction_id
                )
            ):
                self._publish_attention_control(False, data)
                self._attention_interaction_id = ""
                self._attention_mode = "face_body_centering"
            return

        if event_type == "EVT_VOICE_COMMAND_FOLLOW":
            # Follow is a session-scoped closed-loop mode.  The formal
            # follow_owner behavior remains an acknowledgement/contract goal;
            # it must not be translated into a fixed Twist choreography.
            interaction_id = str(data.get("interaction_id", "")).strip()
            if interaction_id and not self._attention_interaction_id:
                self._attention_interaction_id = interaction_id
            self._attention_mode = "follow_owner"
            self._publish_attention_control(True, data)

        candidate = self._intent_mapper.map_audio_event(event_type, data)
        if candidate is not None:
            self._add_candidate(candidate)
        else:
            self._logger.debug(
                "Audio event %s → no candidate (unmapped event_type)", event_type)

    def _publish_attention_control(self, enabled: bool, data: dict) -> None:
        payload = {
            "schema_version": 1,
            "header": {"stamp": time.time(), "frame_id": "base_link"},
            "interaction_id": (
                self._attention_interaction_id
                or str(data.get("interaction_id", ""))
            ),
            "enabled": bool(enabled),
            "mode": self._attention_mode,
            "wake_angle": float(data.get("wake_angle", 0.0) or 0.0),
            "wake_confidence": float(
                data.get("wake_confidence", 0.0) or 0.0
            ),
            "reason": str(data.get("state_reason", "")),
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
        """Reserve the decision channel for human interaction until it ends.

        Attention tracking is session state rather than an Action goal, so it
        does not otherwise participate in normal BT priority arbitration.
        Treat an active voice session as a virtual Lv1 behavior: safety and
        explicit/external interaction work may run, while lower-priority work
        remains queued until the matching idle event closes the session.
        """
        if not self._attention_interaction_id:
            return True
        return int(candidate.get("priority_level", 6)) <= 1

    # ── Candidate Generation (via intent_mapper) ──────────────────────────

    def _invalidate_emotion_visual_request(self, emotion_name: str) -> int:
        generation = self._emotion_visual_generation.get(emotion_name, 0) + 1
        self._emotion_visual_generation[emotion_name] = generation
        return generation

    def _request_contextual_emotion_candidate(
        self,
        emotion_name: str,
        *,
        trigger_event: str,
        signal_value: float,
    ) -> None:
        """Resolve person presence before creating an emotion candidate."""
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

            self._generate_emotion_candidate(
                emotion_name,
                trigger_event=trigger_event,
                signal_value=signal_value,
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

        candidate = self._intent_mapper.map_emotion_event(
            trigger_event,
            {"value": em_val, "visual_route": visual_route},
            interactive=visual_route == "human",
            target=target,
            visual_route=visual_route,
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

    def _add_candidate(self, candidate) -> None:
        """Add a candidate unless its behavior is queued or in-flight."""
        dedup_key = candidate.dedup_key
        bhv_name = candidate.behavior_name
        if self._is_duplicate_or_running(bhv_name, dedup_key):
            self._logger.debug(
                "Candidate suppressed: %s already queued/in-flight",
                bhv_name,
            )
            return
        pool_dict = candidate.to_pool_dict()
        pool_dict.setdefault("dedup_key", dedup_key)
        if not self._candidate_pool.add(**pool_dict):
            self._logger.debug(
                "Candidate suppressed: %s already queued/in-flight",
                bhv_name,
            )

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
        self._dispatch_due_emotion_continuation()
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
                self._schedule_emotion_continuation(
                    str(current_before.params.get("source_emotion", "")),
                    str(outcome.completed_event.status),
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
        self._logger.info(
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
        self._logger.info(
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
        rclpy.init()
        node = BehaviorTreeRosNode()
        try:
            rclpy.spin(node)
        except KeyboardInterrupt:
            pass
        finally:
            node.destroy_node()
            rclpy.shutdown()
    else:
        print("ROS2 not available. Use standalone demo instead:")
        print("  uv run python -m marsdog_behavior.standalone_demo")


if __name__ == "__main__":
    main()
