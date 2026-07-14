"""Behavior Tree ROS2 Node — /behavior_tree_node.

The central decision-making node in the MarsDog behavior stack.
This is a thin ROS2 shell — all logic is delegated to internal modules.

Subscriptions:
  /emotion/state             — current emotion values + levelEvents (periodic)
  /emotion/signal_event      — emotion zone change events (event-driven)
  /internal_need/state       — current need values + levelEvents (periodic)
  /internal_need/signal_event — need level change events (event-driven)

Publishers:
  /behavior/result_event     — demand behavior STARTED / COMPLETED / etc.

Action Client:
  /execute_behavior — sends goals to marsdog_action_executor

Internal delegation:
  candidate_pool.py       — candidate collection + selection
  relevance_checker.py    — string-comparison relevance checking
  interaction_resolver.py — person-presence → interactive/solo
  execution_manager.py    — goal lifecycle management
  result_event_mapper.py  — /behavior/result_event formatting
  perception_client_adapter.py — audio/visual event handling
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bionic_dog_bt.tree_builder import build_tree
from bionic_dog_bt.blackboard import Blackboard
from bionic_dog_bt.behavior_tree_node import Status as BTStatus
from bionic_dog_bt.datatypes import ActiveBehavior
from bionic_dog_bt.constants import STATUS_RUNNING, PRIORITY_LEVELS
from bionic_dog_bt.logger import init_logging, get_logger, LogEvent

from .ros2_compat import NodeBase, HAS_ROS2, is_ros2_ready, get_node_base
from .candidate_pool import CandidatePool
from .interaction_resolver import InteractionResolver
from .execution_manager import ExecutionManager
from .result_event_mapper import ResultEventMapper, should_publish_result
from .perception_client_adapter import PerceptionClientAdapter
from .intent_mapper import IntentMapper, get_emotion_name_from_event
from .state_event_refiner import StateEventRefiner


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
            config_path = str(_PROJECT_ROOT / "config" / "behaviors.yaml")

        # ── Executor setup ───────────────────────────────────────────────
        self._setup_executor(config_path)

        # ── Build behavior tree ──────────────────────────────────────────
        self._tree = build_tree(self._blackboard, self._executor)

        # ── Intent Mapper + State Event Refiner ───────────────────────────
        self._intent_mapper = IntentMapper()
        self._refiner = StateEventRefiner(self._intent_mapper)

        # ── Perception Client Adapter ────────────────────────────────────
        self._perception = PerceptionClientAdapter(self)
        self._blackboard.perception_client = self._perception
        self._perception.set_on_audio_direct(self._on_audio_direct)

        # ── Core modules ─────────────────────────────────────────────────
        self._candidate_pool = CandidatePool()
        self._interaction = InteractionResolver(self._perception)
        self._exec_mgr = ExecutionManager(self._executor)
        self._result_mapper = ResultEventMapper()

        # ── State tracking ───────────────────────────────────────────────
        self._running = True
        self._last_goal_id: str = ""
        self._emotion_heartbeat = 0
        self._need_heartbeat = 0

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

        Updates emotion values and levelEvents. Does NOT generate candidates.
        """
        try:
            data = json.loads(msg.data)
            emotions = data.get("emotions", {})
            for name, value in emotions.items():
                if isinstance(value, (int, float)):
                    self._blackboard.emotion_module.set_emotion(name, float(value))

            level_events = data.get("levelEvents", {})
            if level_events:
                self._blackboard.emotion_module.set_level_events(level_events)

            self._emotion_heartbeat += 1
            if self._emotion_heartbeat % 30 == 1:
                ev = ', '.join(
                    f"{n}={self._blackboard.emotion_module.level_events.get(n, '?')}"
                    for n in ["Joy", "Excite", "Anxiety", "Fear", "Curious", "Calm"])
                self._logger.info(f"/emotion/state heartbeat: [{ev}]")
        except Exception as e:
            self._logger.error(f"Failed to parse /emotion/state: {e}")

    def _on_emotion_signal_ros2(self, msg):
        """Handle /emotion/signal_event (event-driven).

        Generates behavior candidate with trigger_event.
        """
        try:
            data = json.loads(msg.data)
            event_type = data.get("event_type", "")
            self._logger.info(f"/emotion/signal_event: {event_type}")

            event_to_emotion = {
                "EMO_JOY": "Joy", "EMO_EXCITE": "Excite",
                "EMO_ANXIETY": "Anxiety", "EMO_FEAR": "Fear",
                "EMO_CURIOUS": "Curious", "EMO_CALM": "Calm",
            }
            signal_value = data.get("value", 80)
            for prefix, em_name in event_to_emotion.items():
                if event_type.startswith(prefix):
                    # Immediately sync levelEvents so relevance check can
                    # pass even before the next /emotion/state arrives (1Hz).
                    self._blackboard.emotion_module.level_events[em_name] = event_type
                    self._generate_emotion_candidate(
                        em_name, trigger_event=event_type,
                        signal_value=float(signal_value))
                    break
        except Exception as e:
            self._logger.error(f"Failed to parse /emotion/signal_event: {e}")

    def _on_need_state_ros2(self, msg):
        """Handle /internal_need/state (periodic, 1Hz)."""
        try:
            data = json.loads(msg.data)
            demands = data.get("demands", {})
            for need_name, need_info in demands.items():
                if isinstance(need_info, dict):
                    value = need_info.get("value", 0)
                    self._blackboard.need_module.set_need(need_name, float(value))

            level_events = data.get("levelEvents", {})
            if level_events:
                self._blackboard.need_module.set_level_events(level_events)

            self._need_heartbeat += 1
            if self._need_heartbeat % 30 == 1:
                ev = ', '.join(
                    f"{n}={self._blackboard.need_module.level_events.get(n, '?')}"
                    for n in ["Hunger", "Bladder", "Sleepiness", "Cleanliness",
                              "Energy", "Social", "Exploration"])
                self._logger.info(f"/internal_need/state heartbeat: [{ev}]")
        except Exception as e:
            self._logger.error(f"Failed to parse /internal_need/state: {e}")

    def _on_need_signal_ros2(self, msg):
        """Handle /internal_need/signal_event (event-driven)."""
        try:
            data = json.loads(msg.data)
            event_type = data.get("event_type", "")
            demand = data.get("demand", "")
            value = data.get("value", 80)
            level = data.get("level", "")

            self._logger.info(
                f"/internal_need/signal_event: {event_type} demand={demand} level={level}")

            if level in ("TRIGGERED", "OVERFLOW"):
                # Immediately sync levelEvents so relevance check can pass
                # even before the next /internal_need/state arrives (1Hz).
                self._blackboard.need_module.level_events[demand] = event_type
                self._generate_need_candidate(demand, value, trigger_event=event_type)
            else:
                self._logger.info(f"  → SKIP: level={level} (not TRIGGERED/OVERFLOW)")
        except Exception as e:
            self._logger.error(f"Failed to parse /internal_need/signal_event: {e}")

    # ── Audio Direct Handler (whitelist: EVT_VOICE_CALL_NAME, EVT_VOICE_COMMAND_KNOWN) ──

    def _on_audio_direct(self, event_type: str, data: dict) -> None:
        """Handle whitelisted audio events via intent_mapper pipeline.

        Pipeline: event_type → category → intent → action_pool → behavior_name
        """
        candidate = self._intent_mapper.map_audio_event(event_type, data)
        if candidate is not None:
            self._add_candidate(candidate)
        else:
            self._logger.debug(
                "Audio event %s → no candidate (filtered or disabled)", event_type)

    # ── Candidate Generation (via intent_mapper) ──────────────────────────

    def _generate_emotion_candidate(self, emotion_name: str,
                                     trigger_event: str = "",
                                     signal_value: float = None) -> None:
        """Generate behavior candidate from emotion signal_event via intent_mapper.

        Detects person/animal/object targets to determine interaction_mode:
        - Has valid target → interaction_mode=interactive
        - No target → interaction_mode=solo
        """
        em_state = self._blackboard.emotion_module.get_emotion(emotion_name)
        if em_state is not None:
            em_val = em_state.current_value
        elif signal_value is not None:
            em_val = float(signal_value)
            self._blackboard.emotion_module.set_emotion(emotion_name, em_val)
        else:
            self._logger.debug(f"No value for {emotion_name}, skipping candidate")
            return

        # Detect interaction target
        person_present = self._blackboard.perception_client.is_person_present()
        target = None
        if person_present:
            identity = self._blackboard.perception_client.get_active_identity()
            target = {"target_type": "human", "target_id": identity}

        candidate = self._intent_mapper.map_emotion_event(
            trigger_event, {"value": em_val},
            interactive=person_present, target=target)

        if candidate is not None:
            self._add_candidate(candidate)
        else:
            self._generate_emotion_candidate_legacy(emotion_name, em_val,
                                                     trigger_event, person_present)

    def _generate_need_candidate(self, need_name: str, value: float,
                                  trigger_event: str = "") -> None:
        """Generate behavior candidate from need signal_event.

        Social needs use state_event_refiner for fine-grained intent.
        """
        # Social needs: use refiner for fine-grained intent
        if need_name == "Social":
            person = self._blackboard.perception_client.is_person_present()
            # TODO: detect animal target from perception
            refined = self._refiner.refine_social(value, has_human_target=person)
            if refined:
                bhv = refined["behavior_name"]
                dedup_key = ("need", trigger_event, bhv, refined.get("variant", ""), "solo")
                if self._is_duplicate_or_running(bhv, dedup_key):
                    return
                pool_dict = {
                    "behavior_name": bhv,
                    "priority_level": refined["priority_level"],
                    "sub_priority": refined.get("sub_priority", 0),
                    "value": value,
                    "confidence": 0.8,
                    "need_type": "psychological",
                    "params": {
                        "source": "need",
                        "trigger_event": trigger_event,
                        "intent": refined["intent"],
                        "variant": refined["variant"],
                        "intensity": value,
                        "interactive": refined.get("interactive", False),
                        "target_required": refined.get("target_required", False),
                        "result_mapping": refined.get("result_mapping"),
                        "source_need": need_name,
                        "need_value": value,
                    },
                    "timeout_sec": 25.0,
                    "cooldown_sec": 5.0,
                    "dedup_key": dedup_key,
                }
                self._candidate_pool.add(**pool_dict)
                self._logger.info(f"Need candidate [refined]: {need_name}={value:.0f} → {bhv} ({refined['variant']})")
                return

        # Standard path via intent_mapper
        candidate = self._intent_mapper.map_need_event(
            trigger_event, {"demand": need_name, "value": value})

        if candidate is not None:
            self._add_candidate(candidate)
        else:
            self._generate_need_candidate_legacy(need_name, value, trigger_event)

    def _add_candidate(self, candidate) -> None:
        """Add a BehaviorCandidate to the pool with composite-key dedup."""
        dedup_key = candidate.dedup_key
        bhv_name = candidate.behavior_name
        if self._is_duplicate_or_running(bhv_name, dedup_key):
            return
        pool_dict = candidate.to_pool_dict()
        pool_dict.setdefault("dedup_key", dedup_key)
        self._candidate_pool.add(**pool_dict)

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

    # ── Legacy fallback (backward compatibility) ──────────────────────────

    def _generate_emotion_candidate_legacy(self, emotion_name: str, em_val: float,
                                            trigger_event: str, interactive: bool):
        """Legacy fallback using emotion_behavior_table for unmapped events."""
        from bionic_dog_bt.emotion_behavior_table import select_emotion_behavior
        bhv_name = select_emotion_behavior(emotion_name, em_val, interactive)
        if bhv_name is None or self._is_duplicate_or_running(bhv_name):
            return

        self._candidate_pool.add(
            behavior_name=bhv_name,
            priority_level=PRIORITY_LEVELS["EMOTION_EXPRESSION"],
            value=em_val, confidence=0.85,
            need_type="emotional",
            source_emotion=emotion_name,
            params={
                "source_emotion": emotion_name,
                "emotion_value": em_val,
                "interactive": interactive,
                "trigger_event": trigger_event,
            },
            timeout_sec=8.0, cooldown_sec=1.0,
        )
        self._logger.info(
            f"Emotion candidate [legacy]: {emotion_name}={em_val:.0f} → {bhv_name}")

    def _generate_need_candidate_legacy(self, need_name: str, value: float,
                                         trigger_event: str):
        """Legacy fallback using hardcoded need_behavior mapping."""
        need_behavior = {
            "Hunger": ("seek_food_or_water", "PHYSIO_NORMAL", "physiological"),
            "Bladder": ("excretion_request", "PHYSIO_URGENT", "physiological_urgent"),
            "Sleepiness": ("sleep_request", "PHYSIO_URGENT", "physiological_urgent"),
            "Cleanliness": ("clean_self", "PHYSIO_NORMAL", "physiological"),
            "Social": ("seek_social_interaction", "PSYCHOLOGICAL", "psychological"),
            "Exploration": ("explore_environment", "PSYCHOLOGICAL", "psychological"),
        }
        mapping = need_behavior.get(need_name)
        if mapping is None:
            return

        bhv_name, level_key, need_type = mapping
        if self._is_duplicate_or_running(bhv_name):
            return

        self._candidate_pool.add(
            behavior_name=bhv_name,
            priority_level=PRIORITY_LEVELS.get(level_key, 3),
            value=value, confidence=0.8,
            need_type=need_type,
            params={
                "source_need": need_name,
                "need_value": value,
                "trigger_event": trigger_event,
            },
            timeout_sec=30.0, cooldown_sec=3.0,
        )
        self._logger.info(f"Need candidate [legacy]: {need_name}={value:.0f} → {bhv_name}")

    # ── Tick Logic ───────────────────────────────────────────────────────

    def _on_tick(self):
        """Main BT evaluation loop. Called at TICK_RATE Hz."""
        bb = self._blackboard

        # 1. Drain candidate pool → select best → convert to ActiveBehavior
        # NOTE: relevance check is deferred to BehaviorRelevanceCondition
        # inside the BT tree (bionic_dog_bt/conditions.py). Checking here
        # would discard candidates before /emotion/state or /need/state
        # has had time to update levelEvents (state arrives at 1Hz async).
        candidate = self._candidate_pool.select_best(bb)
        if candidate is not None:
            active = self._candidate_to_active_behavior(candidate)
            bb.set_active_behavior(active)

        # 2. Tick behavior tree
        self._tree.reset()
        tree_status = self._tree.tick()
        bb.tick_count += 1
        bb.last_tick_time = time.time()

        # 3. Detect new behavior start → publish STARTED event
        if (bb.current_behavior is not None
                and bb.current_status == STATUS_RUNNING
                and bb.current_goal_id
                and bb.current_goal_id != self._last_goal_id):
            self._last_goal_id = bb.current_goal_id
            self._publish_started(bb.current_behavior.behavior_name)

        # 4. Check for completed behavior → publish result
        if bb.last_feedback_event:
            self._publish_result(
                bb.last_feedback_event.behavior_name,
                getattr(bb.last_feedback_event, 'status', 'SUCCESS'))
            bb.last_feedback_event = None

    def _candidate_to_active_behavior(self, candidate: dict) -> ActiveBehavior:
        """Convert a candidate dict to an ActiveBehavior dataclass."""
        return ActiveBehavior(
            behavior_id=f"bhv_{uuid.uuid4().hex[:12]}",
            behavior_name=candidate["behavior_name"],
            priority_level=candidate["priority_level"],
            value=candidate["value"],
            confidence=candidate.get("confidence", 0.8),
            need_type=candidate.get("need_type", "external"),
            interrupt_policy="immediate",
            timeout_sec=candidate.get("timeout_sec", 30.0),
            cooldown_sec=candidate.get("cooldown_sec", 0.0),
            params=dict(candidate.get("params", {})),
            style={"emotion": candidate.get("source_emotion", "")}
            if candidate.get("source_emotion") else {},
        )

    # ── Result Publishing ────────────────────────────────────────────────

    def _publish_started(self, behavior_name: str):
        """Publish STARTED event to /behavior/result_event."""
        payload = self._result_mapper.build_started_event(behavior_name)
        if payload:
            self._publish(self.RESULT_EVENT_TOPIC, payload)

    def _publish_result(self, behavior_name: str, status: str):
        """Publish result event to /behavior/result_event."""
        payload = self._result_mapper.build_result_event(behavior_name, status)
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
        """Update emotion module from a dict (standalone demo helper)."""
        emotions = emotion_data.get("emotions", emotion_data)
        for name, value in emotions.items():
            if isinstance(value, (int, float)):
                self._blackboard.emotion_module.set_emotion(name, float(value))
        dom = self._blackboard.emotion_module.get_dominant_emotion()
        if dom:
            self._generate_emotion_candidate(dom[0])

    def destroy_node(self):
        self._running = False
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
