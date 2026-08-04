"""Action Client Adapter — bridges the BT's ExecutorInterface to /execute_behavior.

Implements ExecutorInterface so ExecuteActiveBehavior can use a real
ROS2 Action Client without changing its code. When marsdog_action_executor
is running, this adapter replaces MockActionExecutor.

Usage:
    self._executor = ActionClientAdapter(self, "/execute_behavior")

Requires:
    colcon build --packages-select marsdog_interfaces  (to compile ExecuteBehavior.action)
    marsdog_action_executor node running               (Action Server)
"""

from __future__ import annotations

import json
import time
import threading
from typing import Optional

from .ros2_compat import HAS_ROS2


class ActionClientAdapter:
    """Wraps a ROS2 Action Client to implement ExecutorInterface.

    Feedback and results arrive via ROS2 callbacks and are cached for
    synchronous polling by the BT tick loop.
    """

    def __init__(self, node, action_name: str = "/execute_behavior"):
        self._node = node
        self._action_name = action_name
        self._lock = threading.Lock()

        # goal_id → latest feedback
        self._feedback_cache: dict[str, dict] = {}
        # goal_id → result
        self._result_cache: dict[str, dict] = {}
        # goal_id → goal_handle (for cancel)
        self._goal_handles: dict[str, object] = {}
        # behavior_id → goal_id mapping
        self._bhv_to_goal: dict[str, str] = {}
        # goal_id → behavior_name, retained until the result is consumed
        self._behavior_names: dict[str, str] = {}
        # Goals canceled before their asynchronous response arrives.
        self._canceled_goal_ids: set[str] = set()

        if HAS_ROS2:
            self._init_action_client()

    def _init_action_client(self):
        """Create rclpy Action Client for /execute_behavior."""
        from rclpy.action import ActionClient
        try:
            # Prefer marsdog_interfaces (public interface package)
            from marsdog_interfaces.action import ExecuteBehavior
        except ImportError:
            try:
                # Fallback: try marsdog_action_executor
                from marsdog_action_executor.action import ExecuteBehavior
            except ImportError:
                self._node.get_logger().warn(
                    "ExecuteBehavior action not found. "
                    "Build marsdog_interfaces first: "
                    "colcon build --packages-select marsdog_interfaces")
                self._action_type = None
                return

        self._action_type = ExecuteBehavior
        self._client = ActionClient(
            self._node, ExecuteBehavior, self._action_name)

        self._node.get_logger().info(
            f"ActionClientAdapter: waiting for {self._action_name}...")

    def _wait_for_server(self, timeout_sec: float = 5.0) -> bool:
        if self._action_type is None:
            return False
        return self._client.wait_for_server(timeout_sec=timeout_sec)

    # ── ExecutorInterface implementation ─────────────────────────────────────

    def send_goal(self, active) -> str:
        """Send goal via Action Client. Returns goal_id."""
        if not HAS_ROS2 or self._action_type is None:
            return active.behavior_id

        if (
            not self._client.server_is_ready()
            and not self._wait_for_server(3.0)
        ):
            self._cache_failure(
                active.behavior_id,
                active.behavior_name,
                "action server unavailable",
            )
            return active.behavior_id

        goal_msg = self._action_type.Goal()
        goal_msg.goal_id = active.behavior_id
        goal_msg.behavior_name = self._executor_behavior_name(active)
        goal_msg.priority_level = active.priority_level
        goal_msg.params_json = json.dumps(active.params)
        goal_msg.timeout_sec = active.timeout_sec

        with self._lock:
            self._bhv_to_goal[active.behavior_id] = active.behavior_id
            self._behavior_names[active.behavior_id] = active.behavior_name

        send_goal_future = self._client.send_goal_async(
            goal_msg,
            feedback_callback=lambda fb: self._on_feedback(active.behavior_id, fb),
        )
        send_goal_future.add_done_callback(
            lambda fut: self._on_goal_response(active.behavior_id, fut))

        return active.behavior_id

    def cancel_goal(self, goal_id: str) -> bool:
        """Cancel a running goal."""
        with self._lock:
            handle = self._goal_handles.pop(goal_id, None)
            known_goal = goal_id in self._bhv_to_goal
            self._canceled_goal_ids.add(goal_id)
            self._bhv_to_goal.pop(goal_id, None)
            self._feedback_cache.pop(goal_id, None)
            self._result_cache.pop(goal_id, None)
        if handle is not None:
            handle.cancel_goal_async()
            return True
        # A send_goal_async response may still be pending. Marking it canceled
        # lets _on_goal_response cancel it as soon as a handle exists.
        return known_goal

    def tick(self) -> None:
        """No-op: feedback/results arrive asynchronously via ROS2 callbacks."""
        pass

    def get_feedback(self, goal_id: str) -> Optional[object]:
        """Get latest cached feedback for a goal."""
        with self._lock:
            fb = self._feedback_cache.pop(goal_id, None)
        if fb is None:
            return None

        return type('FB', (), {
            'behavior_id': fb.get('behavior_id', ''),
            'behavior_name': fb.get('behavior_name', ''),
            'status': fb.get('status', 'RUNNING'),
            'progress': fb.get('progress', 0.0),
            'safe_to_interrupt': fb.get('safe_to_interrupt', False),
            'message': fb.get('message', ''),
        })()

    def get_result(self, goal_id: str) -> Optional[object]:
        """Get cached result for a completed goal."""
        with self._lock:
            result = self._result_cache.pop(goal_id, None)
        if result is None:
            return None

        from bionic_dog_bt.datatypes import BehaviorFeedbackEvent
        return BehaviorFeedbackEvent(
            behavior_id=result.get('goal_id', goal_id),
            behavior_name=result.get('behavior_name', ''),
            status=result.get('status', ''),
            result=result.get('result', ''),
            reason=result.get('reason', ''),
            reward=result.get('reward', 0.0),
            metadata=result.get('metadata', {}),
            timestamp=time.time(),
        )

    def remove_goal(self, goal_id: str) -> None:
        """Clean up a finished goal."""
        with self._lock:
            self._goal_handles.pop(goal_id, None)
            self._bhv_to_goal.pop(goal_id, None)
            self._behavior_names.pop(goal_id, None)
            self._feedback_cache.pop(goal_id, None)
            self._result_cache.pop(goal_id, None)
            self._canceled_goal_ids.discard(goal_id)

    def has_goal(self, goal_id: str) -> bool:
        """Check if a goal is still active."""
        with self._lock:
            return goal_id in self._bhv_to_goal

    # ── ROS2 callbacks ───────────────────────────────────────────────────────

    def _on_goal_response(self, goal_id: str, future):
        try:
            goal_handle = future.result()
        except Exception as exc:
            self._cache_failure(
                goal_id,
                self._behavior_name(goal_id),
                f"goal request failed: {exc}",
            )
            return

        if not goal_handle.accepted:
            self._node.get_logger().warn(f"Goal rejected: {goal_id}")
            self._cache_failure(
                goal_id,
                self._behavior_name(goal_id),
                "goal rejected",
            )
            return

        with self._lock:
            canceled = goal_id in self._canceled_goal_ids
            if not canceled:
                self._goal_handles[goal_id] = goal_handle

        if canceled:
            goal_handle.cancel_goal_async()
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(
                lambda fut: self._on_result(goal_id, fut)
            )
            return

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda fut: self._on_result(goal_id, fut))

    def _on_feedback(self, goal_id: str, feedback_msg):
        fb = feedback_msg.feedback
        requested_name = self._behavior_name(goal_id)
        with self._lock:
            if goal_id in self._canceled_goal_ids:
                return
            self._feedback_cache[goal_id] = {
                'goal_id': fb.goal_id,
                'behavior_name': requested_name or fb.behavior_name,
                'status': fb.status,
                'progress': fb.progress,
                'safe_to_interrupt': fb.safe_to_interrupt,
                'message': fb.message,
            }

    def _on_result(self, goal_id: str, future):
        with self._lock:
            if goal_id in self._canceled_goal_ids:
                self._canceled_goal_ids.discard(goal_id)
                self._behavior_names.pop(goal_id, None)
                self._goal_handles.pop(goal_id, None)
                return

        try:
            result = future.result().result
        except Exception as exc:
            self._cache_failure(
                goal_id,
                self._behavior_name(goal_id),
                f"result request failed: {exc}",
            )
            return

        with self._lock:
            self._result_cache[goal_id] = {
                'goal_id': result.goal_id,
                # The executor may receive a compatibility template name
                # (e.g. inspectKnownObject), but behavior lifecycle/results
                # remain keyed by the behavior tree's six precise names.
                'behavior_name': (
                    self._behavior_names.get(goal_id)
                    or result.behavior_name
                ),
                'status': result.status,
                'result': result.result,
                'reason': result.reason,
                'reward': result.reward,
                'metadata': _parse_result_metadata(
                    getattr(result, 'metadata_json', '{}')
                ),
            }
            self._goal_handles.pop(goal_id, None)

    def _behavior_name(self, goal_id: str) -> str:
        with self._lock:
            return self._behavior_names.get(goal_id, "")

    @staticmethod
    def _executor_behavior_name(active) -> str:
        """Return an optional downstream compatibility template name."""
        params = active.params if isinstance(active.params, dict) else {}
        return str(
            params.get("executor_behavior_name")
            or active.behavior_name
        )

    def _cache_failure(
        self,
        goal_id: str,
        behavior_name: str,
        reason: str,
    ) -> None:
        """Expose asynchronous transport failures through ExecutorInterface."""
        with self._lock:
            self._result_cache[goal_id] = {
                "goal_id": goal_id,
                "behavior_name": behavior_name,
                "status": "FAILURE",
                "result": "",
                "reason": reason,
                "reward": 0.0,
            }
            self._goal_handles.pop(goal_id, None)
        self._node.get_logger().error(
            f"Action goal failed: {goal_id} ({reason})"
        )


def _parse_result_metadata(metadata_json: str) -> dict:
    """Safely parse executor-reported result metadata."""
    if not metadata_json:
        return {}
    try:
        parsed = json.loads(metadata_json)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
