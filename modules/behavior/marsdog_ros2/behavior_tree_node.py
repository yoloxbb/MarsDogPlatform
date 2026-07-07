"""Behavior Tree Node — /behavior_tree_node.

The central decision-making node in the MarsDog behavior stack.

Subscriptions:
  /behavior_signal    (BehaviorSignal)  — upstream behavior candidates
  /emotion_state      (JSON String)     — current emotion state from emotion_engine

Published Topics:
  /bt/emotion_feedback_event  (BehaviorFeedback) — behavior results for upstream

Action Client:
  /execute_behavior   — sends goals to action_executor_node

Internal:
  - Candidate pool: collects BehaviorSignals between ticks
  - Behavior tree: 7-level priority selector with relevance checking
  - Blackboard: shared state (emotion, need, perception)
  - Tick timer: 10Hz BT evaluation loop

Run:
  ros2 run marsdog_ros2 behavior_tree_node
"""

from __future__ import annotations

import json
import sys
import time
import uuid
import threading
from pathlib import Path
from typing import Optional

# Add project root for bionic_dog_bt imports
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bionic_dog_bt.tree_builder import build_tree
from bionic_dog_bt.blackboard import Blackboard
from bionic_dog_bt.behavior_tree_node import Status as BTStatus
from bionic_dog_bt.constants import (
    STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILURE, STATUS_CANCELED,
    PRIORITY_LEVELS, DEFAULT_IDLE_BEHAVIOR,
)
from bionic_dog_bt.datatypes import ActiveBehavior
from bionic_dog_bt.emotion_behavior_table import select_emotion_behavior, get_dominant_emotion

from bionic_dog_bt.logger import init_logging, get_logger, LogEvent
from .ros2_compat import NodeBase, HAS_ROS2
from .interfaces import (
    BehaviorSignal, BehaviorFeedback,
    ExecuteBehaviorGoal, ExecuteBehaviorFeedback, ExecuteBehaviorResult,
)
from .perception_bridge import PerceptionBridge


# ═══════════════════════════════════════════════════════════════════════════════
# Behavior Tree Node
# ═══════════════════════════════════════════════════════════════════════════════

class BehaviorTreeNode(NodeBase):
    """Main behavior tree runtime as a ROS2 Node.

    Collects upstream signals into a candidate pool, runs the priority-based
    behavior tree at 10Hz, and dispatches behaviors to the action executor.
    """

    TICK_RATE = 0.1     # 10Hz BT evaluation

    # ── Subscriptions (input from upstream nodes) ────────────────────────────
    BEHAVIOR_SIGNAL_TOPIC = "/behavior_signal"
    EMOTION_STATE_TOPIC = "/emotion/state"          # emotion_engine_node (1Hz)
    EMOTION_SIGNAL_TOPIC = "/emotion/signal_event"  # emotion_engine_node (on change)
    NEED_STATE_TOPIC = "/internal_need/state"       # internal_need_node (1Hz)
    NEED_SIGNAL_TOPIC = "/internal_need/signal_event"  # internal_need_node (on change)

    # ── Publication (output to upstream) ─────────────────────────────────────
    RESULT_EVENT_TOPIC = "/behavior/result_event"  # emotion/need nodes subscribe here

    def __init__(self, node_name: str = "behavior_tree_node",
                 config_path: str = None):
        super().__init__(node_name)

        # ── Initialize logging (once per process) ───────────────────────────
        init_logging(ros2_node=self if HAS_ROS2 else None)

        # ── Lifecycle ────────────────────────────────────────────────────────
        self._running = True  # needed by both mock tick thread and destroy_node
        self._last_published_event_id: str = ""  # dedup feedback publishing
        self._logger = get_logger("bt_node")

        # ── Candidate pool (thread-safe) ────────────────────────────────────
        self._candidates: list[BehaviorSignal] = []
        self._lock = threading.Lock()

        # ── Internal runtime ─────────────────────────────────────────────────
        self._blackboard = Blackboard()

        # Create MockActionExecutor first (the BT needs it)
        from bionic_dog_bt.mock_action_executor import MockActionExecutor
        from bionic_dog_bt.yaml_loader import YAMLLoader
        if config_path is None:
            config_path = str(_PROJECT_ROOT / "config" / "behaviors.yaml")
        yaml_loader = YAMLLoader(config_path)
        self._executor = MockActionExecutor(yaml_loader)

        # Build tree with the executor
        self._tree = build_tree(self._blackboard, self._executor)

        # ── Perception Bridge (ROS2 audio_event + perception_task) ──────────
        self._perception = PerceptionBridge(self)

        # Replace blackboard's mock perception client with the bridge
        # (same interface: check_person(), is_person_present())
        self._blackboard.perception_client = self._perception

        # Wire audio commands → candidate pool
        self._perception.set_on_command(self._on_audio_command)

        # ── Action executor proxy ────────────────────────────────────────────
        self._action_executor = None  # set externally or via ROS2 Action Client

        # ── Setup ROS2 or mock ───────────────────────────────────────────────
        if HAS_ROS2:
            self._setup_ros2()
        else:
            self._setup_mock()

        self.get_logger().info(
            f"BehaviorTreeNode started (tick={self.TICK_RATE}s, "
            f"pool_capacity=unlimited)"
        )

    # ── ROS2 Setup ───────────────────────────────────────────────────────────

    def _setup_ros2(self):
        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

        qos_reliable = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        qos_besteffort = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
        )

        # ── Subscribe to upstream topics ──────────────────────────────────
        self.create_subscription(
            String, self.BEHAVIOR_SIGNAL_TOPIC, self._on_signal_ros2, qos_reliable)
        self.create_subscription(
            String, self.EMOTION_STATE_TOPIC, self._on_emotion_state_ros2, qos_besteffort)
        self.create_subscription(
            String, self.EMOTION_SIGNAL_TOPIC, self._on_emotion_signal_ros2, qos_reliable)
        self.create_subscription(
            String, self.NEED_STATE_TOPIC, self._on_need_state_ros2, qos_besteffort)
        self.create_subscription(
            String, self.NEED_SIGNAL_TOPIC, self._on_need_signal_ros2, qos_reliable)

        # ── Publisher for behavior results ────────────────────────────────
        self._result_pub = self.create_publisher(
            String, self.RESULT_EVENT_TOPIC, qos_reliable)

        # ── Timer ─────────────────────────────────────────────────────────
        self.create_timer(self.TICK_RATE, self._on_tick)

        self.get_logger().info("ROS2 subscriptions ready: "
                               "/emotion/state /emotion/signal_event "
                               "/internal_need/state /internal_need/signal_event "
                               "/behavior_signal")

    # ── ROS2 Callbacks ───────────────────────────────────────────────────────

    def _on_signal_ros2(self, msg):
        """Handle /behavior_signal (generic behavior candidate)."""
        try:
            data = json.loads(msg.data)
            signal = BehaviorSignal.from_dict(data)
            self.add_signal(signal)
        except Exception as e:
            self.get_logger().error(f"Failed to parse /behavior_signal: {e}")

    def _on_emotion_state_ros2(self, msg):
        """Handle /emotion/state from emotion_engine_node (1Hz).

        Updates emotion values AND levelEvents for string-comparison
        relevance checking. Does NOT generate candidates.
        """
        try:
            data = json.loads(msg.data)
            emotions = data.get("emotions", {})
            for name, value in emotions.items():
                if isinstance(value, (int, float)):
                    self._blackboard.emotion_module.set_emotion(name, float(value))

            # Store levelEvents for BehaviorRelevanceCondition
            level_events = data.get("levelEvents", {})
            if level_events:
                self._blackboard.emotion_module.set_level_events(level_events)

            # Periodic heartbeat
            self._emotion_heartbeat = getattr(self, '_emotion_heartbeat', 0) + 1
            if self._emotion_heartbeat % 30 == 1:
                ev = ', '.join(
                    f"{n}={self._blackboard.emotion_module.level_events.get(n, '?')}"
                    for n in ["Joy","Excite","Anxiety","Fear","Curious","Calm"]
                )
                self.get_logger().info(f"/emotion/state heartbeat: [{ev}]")
        except Exception as e:
            self.get_logger().error(f"Failed to parse /emotion/state: {e}")

    def _on_emotion_signal_ros2(self, msg):
        """Handle /emotion/signal_event from emotion_engine_node (on change).

        Generates a behavior candidate with trigger_event=event_type.
        At execution time, BehaviorRelevanceCondition compares
        /emotion/state.levelEvents[emotion] with this trigger_event.
        If they match → still in same zone → execute.
        If they differ → emotion changed → skip.
        """
        try:
            data = json.loads(msg.data)
            event_type = data.get("event_type", "")
            emotion_name = data.get("emotion", "")
            zone = data.get("zone", "")
            value = data.get("value", 0)

            self.get_logger().info(
                f"/emotion/signal_event: {event_type} "
                f"emotion={emotion_name} zone={zone} value={value}"
            )

            # Map event prefix to emotion name
            event_to_emotion = {
                "EMO_JOY": "Joy", "EMO_EXCITE": "Excite",
                "EMO_ANXIETY": "Anxiety", "EMO_FEAR": "Fear",
                "EMO_CURIOUS": "Curious", "EMO_CALM": "Calm",
            }
            for prefix, em_name in event_to_emotion.items():
                if event_type.startswith(prefix):
                    self._generate_emotion_candidate(em_name, trigger_event=event_type)
                    break
        except Exception as e:
            self.get_logger().error(f"Failed to parse /emotion/signal_event: {e}")

    def _on_need_state_ros2(self, msg):
        """Handle /internal_need/state from internal_need_node (1Hz).

        Updates need values AND levelEvents for string-comparison
        relevance checking. Does NOT generate candidates.
        """
        try:
            data = json.loads(msg.data)
            demands = data.get("demands", {})
            for need_name, need_info in demands.items():
                if isinstance(need_info, dict):
                    value = need_info.get("value", 0)
                    self._blackboard.need_module.set_need(need_name, float(value))

            # Store levelEvents for BehaviorRelevanceCondition
            level_events = data.get("levelEvents", {})
            if level_events:
                self._blackboard.need_module.set_level_events(level_events)

            # Periodic heartbeat
            self._need_heartbeat = getattr(self, '_need_heartbeat', 0) + 1
            if self._need_heartbeat % 30 == 1:
                ev = ', '.join(
                    f"{n}={self._blackboard.need_module.level_events.get(n, '?')}"
                    for n in ["Hunger","Bladder","Sleepiness","Cleanliness",
                              "Energy","Social","Exploration"]
                )
                self.get_logger().info(f"/internal_need/state heartbeat: [{ev}]")
        except Exception as e:
            self.get_logger().error(f"Failed to parse /internal_need/state: {e}")

    def _on_need_signal_ros2(self, msg):
        """Handle /internal_need/signal_event from internal_need_node (on change).

        Receives level-change events. If TRIGGERED or OVERFLOW, generates candidate.
        """
        try:
            data = json.loads(msg.data)
            event_type = data.get("event_type", "")
            demand = data.get("demand", "")
            value = data.get("value", 80)
            level = data.get("level", "")

            self.get_logger().info(
                f"/internal_need/signal_event: {event_type} "
                f"demand={demand} value={value} level={level}"
            )

            if level in ("TRIGGERED", "OVERFLOW"):
                self._generate_need_candidate(demand, value, trigger_event=event_type)
            else:
                self.get_logger().info(
                    f"  → SKIP: level={level} (not TRIGGERED/OVERFLOW)"
                )
        except Exception as e:
            self.get_logger().error(f"Failed to parse /internal_need/signal_event: {e}")

    # ── Mock Setup ───────────────────────────────────────────────────────────

    def _setup_mock(self):
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def _tick_loop(self):
        while getattr(self, '_running', True):
            self._on_tick()
            time.sleep(self.TICK_RATE)

    # ── Public API (ROS2 subscription handlers + standalone control) ─────────

    def add_signal(self, signal: BehaviorSignal) -> None:
        """Add a behavior candidate to the pool. Thread-safe.

        Skips duplicates: if the same behavior_name is already in the pool
        or currently executing, don't add it again.
        """
        with self._lock:
            # Dedup: skip if same behavior already in pool
            for existing in self._candidates:
                if existing.behavior_name == signal.behavior_name:
                    return

            # Dedup: skip if same behavior is currently executing
            if (self._blackboard.current_behavior is not None
                    and self._blackboard.current_status == STATUS_RUNNING
                    and self._blackboard.current_behavior.behavior_name == signal.behavior_name):
                return

            self._candidates.append(signal)
            self.get_logger().debug(
                f"Signal received: {signal.behavior_name} "
                f"Lv{signal.priority_level} val={signal.value:.0f}"
            )

    def _on_audio_command(self, command_id: str, behavior_name: str,
                          confidence: float, params: dict) -> None:
        """Handle EVT_VOICE_COMMAND_KNOWN from /perception/audio_event.

        Called by PerceptionBridge when a known voice command is detected.
        Generates a BehaviorSignal and adds it to the candidate pool.
        """
        priority = PRIORITY_LEVELS.get("EXTERNAL_INTERACTION", 2)
        # Emergency stop commands get system-level priority
        if behavior_name == "emergency_stop":
            priority = PRIORITY_LEVELS["SYSTEM"]

        signal = BehaviorSignal(
            behavior_name=behavior_name,
            priority_level=priority,
            value=min(confidence * 100, 100.0),
            confidence=confidence,
            need_type="external",
            params_json=json.dumps(params),
            timeout_sec=8.0,
            cooldown_sec=1.0,
        )
        self.add_signal(signal)
        self.get_logger().info(
            f"Audio command: {command_id} → {behavior_name} "
            f"(confidence={confidence:.2f}, Lv{priority})"
        )

    def update_emotion_state(self, emotion_data: dict) -> None:
        """Update emotion module from a dict (used by standalone demo).

        Accepts simple format: {"Joy": 85, "Fear": 20, ...}.
        """
        emotions = emotion_data.get("emotions", emotion_data)
        for name, value in emotions.items():
            if isinstance(value, (int, float)):
                self._blackboard.emotion_module.set_emotion(name, float(value))
        # Generate candidate if dominant emotion is overflowing
        dom = self._blackboard.emotion_module.get_dominant_emotion()
        if dom:
            self._generate_emotion_candidate(dom[0])

    # ── Candidate Generation Helpers ─────────────────────────────────────────

    def _generate_emotion_candidate(self, emotion_name: str,
                                      trigger_event: str = "") -> None:
        """Generate a behavior candidate for an emotion signal_event.

        trigger_event is the event_type from /emotion/signal_event
        (e.g. "EMO_JOY_HIGH"). BehaviorRelevanceCondition compares
        /emotion/state.levelEvents[emotion] with this at execution time.
        """
        em_state = self._blackboard.emotion_module.get_emotion(emotion_name)
        if em_state is None:
            return
        em_val = em_state.current_value

        interactive = self._blackboard.perception_client.is_person_present()
        bhv_name = select_emotion_behavior(emotion_name, em_val, interactive)
        if bhv_name is None:
            return

        if self._is_duplicate(bhv_name):
            return

        signal = BehaviorSignal(
            behavior_name=bhv_name,
            priority_level=PRIORITY_LEVELS["EMOTION_EXPRESSION"],
            value=em_val,
            confidence=0.85,
            need_type="emotional",
            source_emotion=emotion_name,
            params_json=json.dumps({
                "source_emotion": emotion_name,
                "emotion_value": em_val,
                "interactive": interactive,
                "trigger_event": trigger_event,
            }),
            timeout_sec=8.0,
            cooldown_sec=1.0,
        )
        self.add_signal(signal)
        self.get_logger().info(
            f"Emotion candidate: {emotion_name}={em_val:.0f} → {bhv_name} "
            f"trigger={trigger_event} {'interactive' if interactive else 'solo'}"
        )

    def _generate_need_candidate(self, need_name: str, value: float,
                                   trigger_event: str = "") -> None:
        """Generate a behavior candidate for a need signal_event.

        trigger_event is the event_type from /internal_need/signal_event
        (e.g. "NEED_HUNGER_TRIGGERED"). BehaviorRelevanceCondition compares
        /internal_need/state.levelEvents[need] with this at execution time.
        """
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
            self.get_logger().debug(f"No behavior mapping for need: {need_name}")
            return

        bhv_name, level_key, need_type = mapping

        if self._is_duplicate(bhv_name):
            return

        signal = BehaviorSignal(
            behavior_name=bhv_name,
            priority_level=PRIORITY_LEVELS.get(level_key, 3),
            value=value,
            confidence=0.8,
            need_type=need_type,
            source_emotion="",
            params_json=json.dumps({
                "source_need": need_name,
                "need_value": value,
                "trigger_event": trigger_event,
            }),
            timeout_sec=30.0,
            cooldown_sec=3.0,
        )
        self.add_signal(signal)
        self.get_logger().info(
            f"Need candidate: {need_name}={value:.0f} → {bhv_name} (Lv{signal.priority_level})"
        )

    def _is_duplicate(self, behavior_name: str) -> bool:
        """Check if a behavior is already in the pool or currently executing."""
        with self._lock:
            for existing in self._candidates:
                if existing.behavior_name == behavior_name:
                    return True
        if (self._blackboard.current_behavior is not None
                and self._blackboard.current_status == STATUS_RUNNING
                and self._blackboard.current_behavior.behavior_name == behavior_name):
            return True
        return False

    def add_signal_dict(self, d: dict) -> None:
        """Add a signal from a plain dict (convenience for standalone demo)."""
        signal = BehaviorSignal.from_dict(d)
        self.add_signal(signal)

    def set_action_executor(self, executor) -> None:
        """Set the action executor proxy (mock or ROS2 Action Client)."""
        self._action_executor = executor

    # ── Tick Logic ───────────────────────────────────────────────────────────

    def _on_tick(self):
        """Main BT evaluation loop. Called at TICK_RATE Hz."""
        bb = self._blackboard

        # 1. Drain candidate pool → select best
        signal = self._select_candidate()
        if signal is not None:
            active = self._signal_to_active_behavior(signal)
            bb.set_active_behavior(active)

        # 2. Upstream processing is handled by real nodes:
        #    emotion_engine_node → /emotion/state (decay done upstream)
        #    internal_need_node → /internal_need/state (natural update done upstream)
        #    We just read their published state via subscriptions.
        #    (In mock mode, select() ticks these internally.)

        # 3. Tick the behavior tree
        self._tree.reset()
        tree_status = self._tree.tick()
        bb.tick_count += 1
        bb.last_tick_time = time.time()

        # 4. If tree wants to execute, send goal to action executor
        if bb.active_behavior is None and bb.current_goal_id is None and \
           bb.current_status not in (STATUS_RUNNING,):
            # Tree consumed the signal and sent a goal (handled inside ExecuteActiveBehavior)
            pass

        # 5. Check for completed goals → publish feedback (once per event)
        if bb.last_feedback_event:
            event_id = getattr(bb.last_feedback_event, 'behavior_id', '')
            if event_id != self._last_published_event_id:
                self._publish_feedback(bb.last_feedback_event)
                self._last_published_event_id = event_id
            # Clear stale feedback if current behavior has changed
            if (bb.current_behavior is not None
                    and bb.last_feedback_event.behavior_id != bb.current_behavior.behavior_id):
                bb.last_feedback_event = None

        # 6. Advance executor and collect feedback/results
        #    (uses internal mock executor; in ROS2 prod this is replaced
        #     by an Action Client that receives feedback via ROS2 callbacks)
        if self._executor:
            self._executor.tick()
            if bb.current_goal_id:
                fb = self._executor.get_feedback(bb.current_goal_id)
                if fb:
                    bb.executor_feedback = fb
                result = self._executor.get_result(bb.current_goal_id)
                if result:
                    from bionic_dog_bt.datatypes import BehaviorFeedbackEvent
                    bb.last_feedback_event = BehaviorFeedbackEvent(
                        behavior_id=result.behavior_id,
                        behavior_name=result.behavior_name,
                        status=result.status,
                        result=result.result,
                        reason=result.reason,
                        reward=result.reward,
                        timestamp=time.time(),
                    )
                    self._publish_feedback(bb.last_feedback_event)

    def _select_candidate(self) -> Optional[BehaviorSignal]:
        """Select the best candidate from the pool.

        Rules (same as MockInputProvider.select()):
        1. Sort by (priority_level asc, value desc)
        2. Skip cooldown-blocked behaviors
        """
        with self._lock:
            if not self._candidates:
                return None

            self._candidates.sort(key=lambda s: (s.priority_level, -s.value))
            best = self._candidates[0]

            # Skip cooldown
            for cand in self._candidates:
                if not self._blackboard.is_in_cooldown(cand.behavior_name):
                    best = cand
                    break

            self._candidates.clear()
            return best

    def _signal_to_active_behavior(self, signal: BehaviorSignal) -> ActiveBehavior:
        """Convert a BehaviorSignal to an ActiveBehavior for the BT."""
        return ActiveBehavior(
            behavior_id=signal.behavior_id,
            behavior_name=signal.behavior_name,
            priority_level=signal.priority_level,
            value=signal.value,
            confidence=signal.confidence,
            need_type=signal.need_type,
            interrupt_policy="immediate",
            timeout_sec=signal.timeout_sec,
            cooldown_sec=signal.cooldown_sec,
            params=signal.params,
            style={"emotion": signal.source_emotion} if signal.source_emotion else {},
        )

    def _publish_feedback(self, event) -> None:
        """Publish behavior result to /behavior/result_event.

        Emotion engine and internal need nodes subscribe to this topic.
        The result_type field maps behavior outcomes to emotion/need deltas:
          SUCCESS → COMPLETED → DemandSatisfied (Joy↑, Calm↑, Anxiety↓)
          FAILURE/TIMEOUT → DemandUnsatisfied (Anxiety↑)
          CANCELED/INTERRUPTED → ActionInterrupted (Anxiety↑)
        """
        status = getattr(event, 'status', 'SUCCESS')
        result = getattr(event, 'result', 'completed')

        # Map BT status to result_type expected by emotion/need nodes
        result_type_map = {
            "SUCCESS": "COMPLETED",
            "FAILURE": "FAILED",
            "TIMEOUT": "TIMEOUT",
            "CANCELED": "INTERRUPTED",
        }
        result_type = result_type_map.get(status, "COMPLETED")

        # Extract source_event from current behavior params (set by signal_event / audio command)
        source_event = ""
        cb = self._blackboard.current_behavior
        if cb is not None:
            source_event = cb.params.get("trigger_event",
                          cb.params.get("command_id", ""))

        fb = BehaviorFeedback(
            behavior_id=getattr(event, 'behavior_id', ''),
            behavior_name=getattr(event, 'behavior_name', ''),
            status=status,
            result=result_type,
            source_event=source_event,
            reason=getattr(event, 'reason', ''),
            reward=getattr(event, 'reward', 0.0),
        )

        if HAS_ROS2 and hasattr(self, '_result_pub'):
            from std_msgs.msg import String
            msg = String()
            msg.data = json.dumps(fb.to_dict())
            self._result_pub.publish(msg)
            self.get_logger().info(
                f"Published /behavior/result_event: "
                f"{fb.behavior_name} → {result_type} (status={status})"
            )
        else:
            self.get_logger().info(
                f"FEEDBACK: {fb.behavior_name} → {result_type} ({fb.reason})"
            )

    def destroy_node(self):
        self._running = False
        # Stop mock tick thread if running
        if hasattr(self, '_tick_thread') and self._tick_thread:
            pass  # daemon thread will exit when _running is False
        if hasattr(self, '_result_pub'):
            self._result_pub = None
        super().destroy_node()


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    if HAS_ROS2:
        import rclpy
        rclpy.init()
        node = BehaviorTreeNode()
        try:
            rclpy.spin(node)
        except KeyboardInterrupt:
            pass
        finally:
            node.destroy_node()
            rclpy.shutdown()
    else:
        print("ROS2 not available. Use marsdog_ros2.standalone_demo instead.")
        print("  uv run python -m marsdog_ros2.standalone_demo")


if __name__ == "__main__":
    main()
