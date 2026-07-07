"""Mock Action Executor Node — /action_executor_node.

Provides the /execute_behavior ROS2 Action server.
Simulates long-running behavior execution with step-by-step progress.

In production, this node would be replaced by a real action executor
that drives motors, servos, speakers, etc. Here it uses the action
catalog to build randomized action sequences and simulates their
execution over time.

ROS2 API:
  Action Server: /execute_behavior
    Goal:    ExecuteBehavior_Goal    (behavior_name, params, timeout)
    Feedback: ExecuteBehavior_Feedback (progress, safe_to_interrupt, current_action)
    Result:  ExecuteBehavior_Result   (status, reason, reward, emotion/need deltas)

Run:
  ros2 run marsdog_ros2 action_executor_node
"""

from __future__ import annotations

import time
import sys
import uuid
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

# Add project root for bionic_dog_bt imports
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bionic_dog_bt.action_catalog import build_action_sequence

from .ros2_compat import NodeBase, HAS_ROS2
from .interfaces import ExecuteBehaviorGoal, ExecuteBehaviorFeedback, ExecuteBehaviorResult


# ═══════════════════════════════════════════════════════════════════════════════
# Internal goal state
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class _ActiveGoal:
    """Internal tracking for one executing goal."""
    goal: ExecuteBehaviorGoal
    action_sequence: list[dict] = field(default_factory=list)
    current_step: int = 0
    step_start_time: float = 0.0
    status: str = "RUNNING"
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.action_sequence = build_action_sequence(
            self.goal.behavior_name,
            interactive=self.goal.params.get("interactive", False),
        )
        self.step_start_time = time.time()

    @property
    def total_steps(self) -> int:
        return len(self.action_sequence)

    @property
    def progress(self) -> float:
        if self.total_steps == 0:
            return 1.0
        completed = self.current_step
        if self.current_step < self.total_steps:
            step = self.action_sequence[self.current_step]
            dur = max(step.get("duration", 1.0), 0.001)
            partial = min((time.time() - self.step_start_time) / dur, 1.0)
        else:
            partial = 0.0
        return min((completed + partial) / self.total_steps, 1.0)

    @property
    def safe_to_interrupt(self) -> bool:
        if self.current_step >= self.total_steps:
            return True
        return bool(self.action_sequence[self.current_step].get("safe_to_interrupt", True))

    @property
    def current_action(self) -> str:
        if self.current_step < self.total_steps:
            return self.action_sequence[self.current_step].get("action", "N/A")
        return "N/A"

    def advance(self) -> Optional[str]:
        """Advance to next step if duration elapsed. Returns new status or None."""
        if self.current_step >= self.total_steps:
            return "SUCCESS"

        step = self.action_sequence[self.current_step]
        dur = step.get("duration", 1.0)
        if time.time() - self.step_start_time >= dur:
            self.current_step += 1
            if self.current_step >= self.total_steps:
                self.status = "SUCCESS"
                return "SUCCESS"
            self.step_start_time = time.time()
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Mock Action Executor Node
# ═══════════════════════════════════════════════════════════════════════════════

class MockActionExecutorNode(NodeBase):
    """ROS2 Node providing the /execute_behavior Action Server.

    Accepts behavior execution goals, simulates step-by-step progress,
    and returns results. In production, this would be replaced by a node
    that drives real hardware.
    """

    ACTION_NAME = "/execute_behavior"
    TICK_RATE = 0.1  # 10Hz internal tick

    def __init__(self, node_name: str = "action_executor_node"):
        super().__init__(node_name)
        self._goals: dict[str, _ActiveGoal] = {}
        self._lock = threading.Lock()
        self._running = True
        self._tick_thread: Optional[threading.Thread] = None

        # Always start the tick loop (drives mock execution)
        self._start_tick_thread()

        # In ROS2 mode, also set up the Action Server
        if HAS_ROS2:
            self._setup_ros2_action_server()

        self.get_logger().info("MockActionExecutorNode started "
                               f"(tick={self.TICK_RATE}s, "
                               f"has_ros2_action_server={HAS_ROS2})")

    # ── ROS2 Action Server setup ─────────────────────────────────────────────

    def _setup_ros2_action_server(self):
        """Create ROS2 Action Server for /execute_behavior.

        Uses explicit goal/feedback/result callbacks so the mock execution
        engine drives the ROS2 Action feedback and result lifecycle.
        """
        import rclpy
        from rclpy.action import ActionServer, GoalResponse

        # Try to import the action type from built package
        try:
            from marsdog_ros2.action import ExecuteBehavior
            action_type = ExecuteBehavior
        except ImportError:
            self.get_logger().warn(
                "marsdog_ros2.action.ExecuteBehavior not built yet. "
                "Run: colcon build --packages-select marsdog_ros2"
            )
            return

        self._action_server = ActionServer(
            self, action_type, self.ACTION_NAME,
            execute_callback=self._execute_callback,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            handle_accepted_callback=self._handle_accepted,
        )
        self.get_logger().info(
            f"ROS2 Action Server ready: {self.ACTION_NAME}"
        )

    def _goal_callback(self, goal_request):
        import rclpy.action
        return rclpy.action.server.GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        self.cancel_goal(goal_handle.goal_id.uuid)
        import rclpy.action
        return rclpy.action.server.CancelResponse.ACCEPT

    def _handle_accepted(self, goal_handle):
        """Start execution in background thread."""
        pass  # The tick loop handles execution; feedback sent in tick_loop

    def _execute_callback(self, goal_handle):
        """Blocking execute — not used with handle_accepted pattern."""
        pass

    # ── Tick thread ──────────────────────────────────────────────────────────

    def _start_tick_thread(self):
        self._running = True
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def _tick_loop(self):
        while self._running:
            self._tick()
            time.sleep(self.TICK_RATE)

    def _tick(self):
        """Advance all active goals by one step."""
        with self._lock:
            for goal in list(self._goals.values()):
                if goal.status != "RUNNING":
                    continue
                result = goal.advance()
                if result == "SUCCESS":
                    self.get_logger().info(
                        f"Goal {goal.goal.goal_id} completed: {goal.goal.behavior_name}"
                    )

    # ── Public API (compatible with both ROS2 and standalone) ─────────────────

    def send_goal(self, goal: ExecuteBehaviorGoal) -> str:
        """Accept a new goal. Returns goal_id."""
        with self._lock:
            active = _ActiveGoal(goal=goal)
            self._goals[goal.goal_id] = active
            actions = [s["action"] for s in active.action_sequence]
            self.get_logger().info(
                f"ACCEPTED goal={goal.goal_id} behavior={goal.behavior_name} "
                f"steps={len(actions)} actions={actions}"
            )
            return goal.goal_id

    def cancel_goal(self, goal_id: str) -> bool:
        """Cancel a running goal."""
        with self._lock:
            if goal_id in self._goals:
                goal = self._goals[goal_id]
                if goal.status == "RUNNING":
                    goal.status = "CANCELED"
                    self.get_logger().info(f"CANCELED goal={goal_id}")
                    return True
        return False

    def get_feedback(self, goal_id: str) -> Optional[ExecuteBehaviorFeedback]:
        """Get current feedback for a goal."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None
            return ExecuteBehaviorFeedback(
                goal_id=goal.goal.goal_id,
                behavior_id=goal.goal.behavior_id,
                behavior_name=goal.goal.behavior_name,
                status=goal.status,
                progress=goal.progress,
                safe_to_interrupt=goal.safe_to_interrupt,
                current_action=goal.current_action,
                message=f"Step {goal.current_step + 1}/{goal.total_steps}: "
                f"{goal.current_action}",
            )

    def get_result(self, goal_id: str) -> Optional[ExecuteBehaviorResult]:
        """Get final result for a completed/canceled goal."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None
            if goal.status not in ("SUCCESS", "CANCELED", "FAILURE"):
                return None

            status = goal.status
            reward = 1.0 if status == "SUCCESS" else -0.1
            reason = "All steps completed" if status == "SUCCESS" else "Canceled"

            return ExecuteBehaviorResult(
                goal_id=goal.goal.goal_id,
                behavior_id=goal.goal.behavior_id,
                behavior_name=goal.goal.behavior_name,
                status=status,
                result="completed" if status == "SUCCESS" else "canceled",
                reason=reason,
                reward=reward,
                emotion_delta_json='{"satisfaction": 0.1}' if status == "SUCCESS" else "{}",
                need_delta_json=(
                    f'{{"{goal.goal.behavior_name}": -0.5}}' if status == "SUCCESS" else "{}"
                ),
            )

    def remove_goal(self, goal_id: str) -> None:
        """Clean up a finished goal."""
        with self._lock:
            self._goals.pop(goal_id, None)

    def destroy_node(self):
        self._running = False
        super().destroy_node()


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    if HAS_ROS2:
        import rclpy
        rclpy.init()
        node = MockActionExecutorNode()
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
