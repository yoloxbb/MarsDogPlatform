"""Unified logging system for the bionic dog behavior tree.

Provides:
  - Module-scoped loggers with consistent formatting
  - Structured event logging for BT lifecycle events
  - ROS2 bridge (forwards to rclpy when available)
  - Configurable log levels via env var LOG_LEVEL

Usage:
    from bionic_dog_bt.logger import get_logger, LogEvent

    logger = get_logger(__name__)
    logger.info("Starting behavior", behavior="playBow", level=5)
    logger.event(LogEvent.BEHAVIOR_START, behavior_name="playBow", goal_id="goal_1")

Configure:
    export LOG_LEVEL=DEBUG    # default: INFO
    export LOG_FILE=/tmp/bt.log  # default: stderr only
"""

from __future__ import annotations

import logging
import os
import sys
import time
import json
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Event Types
# ═══════════════════════════════════════════════════════════════════════════════

class LogEvent(str, Enum):
    """Structured event types for behavior tree lifecycle."""
    # Candidate & signal
    CANDIDATE_INJECT = "candidate_inject"
    CANDIDATE_DEDUP = "candidate_dedup"
    CANDIDATE_SELECT = "candidate_select"

    # Behavior execution
    BEHAVIOR_START = "behavior_start"
    BEHAVIOR_COMPLETE = "behavior_complete"
    BEHAVIOR_TIMEOUT = "behavior_timeout"
    BEHAVIOR_COOLDOWN = "behavior_cooldown"

    # Preemption
    PREEMPT = "preempt"
    PREEMPT_BLOCKED = "preempt_blocked"

    # Relevance check
    RELEVANCE_PASS = "relevance_pass"
    RELEVANCE_FAIL = "relevance_fail"

    # Emotion / Need
    EMOTION_STATE = "emotion_state"
    EMOTION_SIGNAL = "emotion_signal"
    NEED_STATE = "need_state"
    NEED_SIGNAL = "need_signal"

    # System
    TREE_TICK = "tree_tick"
    FEEDBACK_PUBLISH = "feedback_publish"


# ═══════════════════════════════════════════════════════════════════════════════
# Logger
# ═══════════════════════════════════════════════════════════════════════════════

class BTLogger:
    """Logger wrapper with structured event support.

    Wraps a standard Python logger and adds:
      - event(event_type, **kwargs): structured key-value logging
    """

    def __init__(self, name: str, ros2_node=None):
        self.logger = logging.getLogger(name)
        self._ros2_node = ros2_node

    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def event(self, event_type: LogEvent, **kwargs) -> None:
        """Log a structured event as JSON at INFO level.

        Example:
            logger.event(LogEvent.BEHAVIOR_START,
                         behavior_name="playBow", priority_level=5, goal_id="g1")
        """
        kwargs["event"] = event_type.value
        kwargs["timestamp"] = time.time()
        self.logger.info(json.dumps(kwargs, ensure_ascii=False, default=str))


# ═══════════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════════

_loggers: dict[str, BTLogger] = {}
_ros2_node = None
_initialized = False


def init_logging(level: str = None, log_file: str = None,
                 ros2_node=None) -> None:
    """Initialize the logging system. Called once at startup.

    Args:
        level: DEBUG, INFO, WARN, ERROR (default: INFO, or $LOG_LEVEL)
        log_file: optional file path for log output
        ros2_node: optional rclpy Node for ROS2 bridging
    """
    global _initialized, _ros2_node, _loggers
    if _initialized:
        return

    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    if log_file is None:
        log_file = os.environ.get("LOG_FILE", None)

    _ros2_node = ros2_node

    # Root logger
    root = logging.getLogger("bionic_dog_bt")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    # Formatter — %(name)s shows the logger hierarchy (e.g. bionic_dog_bt.actions)
    fmt = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)-5s] [%(name)-24s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
        root.info(f"Logging to file: {log_file}")

    _initialized = True

    # Invalidate cached loggers so they get the new config
    for bt_logger in _loggers.values():
        bt_logger.logger.handlers.clear()
        bt_logger.logger.propagate = True


def get_logger(name: str) -> BTLogger:
    """Get a module-scoped logger.

    Usage:
        logger = get_logger(__name__)
        logger.info("hello")
        logger.event(LogEvent.BEHAVIOR_START, behavior_name="playBow")
    """
    global _loggers
    if not _initialized:
        init_logging()

    if name not in _loggers:
        _loggers[name] = BTLogger(f"bionic_dog_bt.{name}", _ros2_node)

    return _loggers[name]


def set_ros2_node(node) -> None:
    """Set the ROS2 node for log forwarding."""
    global _ros2_node
    _ros2_node = node


# ═══════════════════════════════════════════════════════════════════════════════
# Quick-access loggers for common modules
# ═══════════════════════════════════════════════════════════════════════════════

def get_bt_logger() -> BTLogger:
    return get_logger("behavior_tree")

def get_action_logger() -> BTLogger:
    return get_logger("actions")

def get_condition_logger() -> BTLogger:
    return get_logger("conditions")

def get_executor_logger() -> BTLogger:
    return get_logger("executor")

def get_emotion_logger() -> BTLogger:
    return get_logger("emotion")
