"""ROS2 compatibility layer.

When ROS2 (rclpy) is installed, exports real ROS2 classes.
When not, exports mock base classes so the code can run standalone.

Usage:
    from marsdog_ros2.ros2_compat import NodeBase, HAS_ROS2

    class MyNode(NodeBase):
        def __init__(self, name):
            super().__init__(name)
            if HAS_ROS2:
                self.create_subscription(...)
            else:
                self._mock_init(...)
"""

from __future__ import annotations

import time
import json
import threading
from typing import Any, Callable, Optional

try:
    import rclpy  # noqa: F401
    from rclpy.node import Node as _RosNode
    HAS_ROS2 = True
except ImportError:
    _RosNode = None
    HAS_ROS2 = False


# ═══════════════════════════════════════════════════════════════════════════════
# Mock ROS2 primitives
# ═══════════════════════════════════════════════════════════════════════════════

class _MockSubscription:
    """Stand-in for rclpy Subscription. Stores topic + callback."""
    def __init__(self, topic: str, msg_type: type, callback: Callable):
        self.topic = topic
        self.msg_type = msg_type
        self.callback = callback


class _MockPublisher:
    """Stand-in for rclpy Publisher. publish() calls on_publish hooks."""
    def __init__(self, topic: str, msg_type: type):
        self.topic = topic
        self.msg_type = msg_type
        self._hooks: list[Callable] = []

    def publish(self, msg):
        for hook in self._hooks:
            hook(msg)

    def on_publish(self, hook: Callable):
        self._hooks.append(hook)


class _MockTimer:
    """Stand-in for rclpy Timer. Fire callback at intervals in background."""
    def __init__(self, period_sec: float, callback: Callable):
        self.period_sec = period_sec
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while self._running:
            time.sleep(self.period_sec)
            if self._running:
                self.callback()

    def cancel(self):
        self._running = False


# ═══════════════════════════════════════════════════════════════════════════════
# Node base class
# ═══════════════════════════════════════════════════════════════════════════════

class _MockNode:
    """Mock ROS2 Node for standalone execution.

    Provides the same interface as rclpy.Node but stores subscriptions,
    publishers, and timers in-memory. Callbacks can be triggered manually
    via _mock_deliver(subscription, msg) for testing.
    """

    def __init__(self, name: str):
        self._node_name = name
        self._subscriptions: list[_MockSubscription] = []
        self._publishers: dict[str, _MockPublisher] = {}
        self._timers: list[_MockTimer] = []

    def get_name(self) -> str:
        return self._node_name

    def get_logger(self):
        class _Logger:
            def info(self_, msg): print(f"[{self._node_name}] INFO: {msg}")
            def warn(self_, msg): print(f"[{self._node_name}] WARN: {msg}")
            def error(self_, msg): print(f"[{self._node_name}] ERROR: {msg}")
            def debug(self_, msg): print(f"[{self._node_name}] DEBUG: {msg}")
        return _Logger()

    # ── Mock subscribe / publish / timer ─────────────────────────────────────

    def create_subscription(self, msg_type: type, topic: str,
                            callback: Callable, qos: Any = None):
        sub = _MockSubscription(topic, msg_type, callback)
        self._subscriptions.append(sub)
        return sub

    def create_publisher(self, msg_type: type, topic: str, qos: Any = None):
        pub = _MockPublisher(topic, msg_type)
        self._publishers[topic] = pub
        return pub

    def create_timer(self, period_sec: float, callback: Callable):
        timer = _MockTimer(period_sec, callback)
        self._timers.append(timer)
        timer.start()
        return timer

    # ── Mock delivery (for standalone testing) ────────────────────────────────

    def _mock_deliver(self, topic: str, msg) -> None:
        """Deliver a message to all subscriptions on a topic."""
        for sub in self._subscriptions:
            if sub.topic == topic:
                sub.callback(msg)

    def _mock_get_published(self, topic: str) -> list:
        """Get all messages published to a topic (collect via on_publish hook)."""
        results: list = []
        if topic in self._publishers:
            self._publishers[topic].on_publish(lambda m: results.append(m))
        return results

    def destroy_node(self):
        for t in self._timers:
            t.cancel()


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_ROS2:
    NodeBase = _RosNode
    MockSubscription = None
    MockPublisher = None
    MockTimer = None
else:
    NodeBase = _MockNode
    MockSubscription = _MockSubscription
    MockPublisher = _MockPublisher
    MockTimer = _MockTimer
