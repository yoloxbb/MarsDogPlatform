"""ROS2 interface definitions as Python dataclasses.

Mirrors the .msg and .action files. Can be used both in ROS2 mode
(via rclpy message serialization) and standalone (direct dataclass).

ROS2 message files:
  msg/BehaviorSignal.msg   — behavior candidate from upstream
  msg/BehaviorFeedback.msg — behavior result feedback to upstream
  action/ExecuteBehavior.action — long-running behavior execution
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# BehaviorSignal — published to /behavior_signal
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BehaviorSignal:
    """A behavior candidate signal from an upstream node.

    Upstream nodes (audio_perception, internal_need, emotion_engine) publish
    these to /behavior_signal. The behavior_tree_node collects them into
    its candidate pool.

    ROS2 msg fields:
      string behavior_id
      string behavior_name
      int32  priority_level
      float64 value
      float64 confidence
      string need_type
      string source_emotion
      string params_json
      float64 timeout_sec
      float64 cooldown_sec
    """

    behavior_name: str
    priority_level: int
    value: float = 50.0
    behavior_id: str = ""
    confidence: float = 0.8
    need_type: str = "external"
    source_emotion: str = ""
    params_json: str = "{}"
    timeout_sec: float = 30.0
    cooldown_sec: float = 0.0

    def __post_init__(self):
        if not self.behavior_id:
            self.behavior_id = f"sig_{uuid.uuid4().hex[:12]}"

    @property
    def params(self) -> dict:
        return json.loads(self.params_json) if self.params_json else {}

    @params.setter
    def params(self, d: dict):
        self.params_json = json.dumps(d)

    def to_dict(self) -> dict:
        return {
            "behavior_id": self.behavior_id,
            "behavior_name": self.behavior_name,
            "priority_level": self.priority_level,
            "value": self.value,
            "confidence": self.confidence,
            "need_type": self.need_type,
            "source_emotion": self.source_emotion,
            "params_json": self.params_json,
            "timeout_sec": self.timeout_sec,
            "cooldown_sec": self.cooldown_sec,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BehaviorSignal":
        return cls(
            behavior_id=d.get("behavior_id", ""),
            behavior_name=d["behavior_name"],
            priority_level=d.get("priority_level", 5),
            value=d.get("value", 50.0),
            confidence=d.get("confidence", 0.8),
            need_type=d.get("need_type", "external"),
            source_emotion=d.get("source_emotion", ""),
            params_json=d.get("params_json", "{}"),
            timeout_sec=d.get("timeout_sec", 30.0),
            cooldown_sec=d.get("cooldown_sec", 0.0),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BehaviorFeedback — published to /bt/emotion_feedback_event
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BehaviorFeedback:
    """Behavior result feedback published by behavior_tree_node.

    Upstream nodes (emotion_engine, internal_need) subscribe to this
    to update emotion/need states based on behavior outcomes.

    ROS2 msg fields:
      string behavior_id
      string behavior_name
      string status          # SUCCESS / FAILURE / CANCELED / TIMEOUT
      string result          # completed / canceled / timeout
      string reason
      float64 reward
      string emotion_delta_json
      string need_delta_json
      float64 timestamp
    """

    behavior_id: str
    behavior_name: str
    status: str = "SUCCESS"
    result: str = "completed"
    source_event: str = ""          # trigger_event from signal (e.g. "EMO_JOY_HIGH", "NEED_HUNGER_TRIGGERED", "CMD_SIT")
    reason: str = ""
    reward: float = 0.0
    emotion_delta_json: str = "{}"
    need_delta_json: str = "{}"
    timestamp: float = field(default_factory=time.time)

    @property
    def emotion_delta(self) -> dict:
        return json.loads(self.emotion_delta_json) if self.emotion_delta_json else {}

    @emotion_delta.setter
    def emotion_delta(self, d: dict):
        self.emotion_delta_json = json.dumps(d)

    @property
    def need_delta(self) -> dict:
        return json.loads(self.need_delta_json) if self.need_delta_json else {}

    @need_delta.setter
    def need_delta(self, d: dict):
        self.need_delta_json = json.dumps(d)

    def to_dict(self) -> dict:
        return {
            "behavior_id": self.behavior_id,
            "behavior_name": self.behavior_name,
            "status": self.status,
            "result": self.result,
            "source_event": self.source_event,
            "reason": self.reason,
            "reward": self.reward,
            "emotion_delta_json": self.emotion_delta_json,
            "need_delta_json": self.need_delta_json,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BehaviorFeedback":
        return cls(
            behavior_id=d.get("behavior_id", ""),
            behavior_name=d.get("behavior_name", ""),
            status=d.get("status", "SUCCESS"),
            result=d.get("result", "completed"),
            source_event=d.get("source_event", ""),
            reason=d.get("reason", ""),
            reward=d.get("reward", 0.0),
            emotion_delta_json=d.get("emotion_delta_json", "{}"),
            need_delta_json=d.get("need_delta_json", "{}"),
            timestamp=d.get("timestamp", time.time()),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ExecuteBehavior Action — /execute_behavior
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExecuteBehaviorGoal:
    """Goal for the /execute_behavior Action.

    Sent by behavior_tree_node to action_executor_node.
    """
    goal_id: str = ""
    behavior_id: str = ""
    behavior_name: str = ""
    priority_level: int = 5
    params_json: str = "{}"
    timeout_sec: float = 30.0

    def __post_init__(self):
        if not self.goal_id:
            self.goal_id = f"goal_{uuid.uuid4().hex[:12]}"

    @property
    def params(self) -> dict:
        return json.loads(self.params_json) if self.params_json else {}

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "behavior_id": self.behavior_id,
            "behavior_name": self.behavior_name,
            "priority_level": self.priority_level,
            "params_json": self.params_json,
            "timeout_sec": self.timeout_sec,
        }


@dataclass
class ExecuteBehaviorFeedback:
    """Periodic feedback during behavior execution."""
    goal_id: str = ""
    behavior_id: str = ""
    behavior_name: str = ""
    status: str = "RUNNING"
    progress: float = 0.0
    safe_to_interrupt: bool = False
    current_action: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "behavior_id": self.behavior_id,
            "behavior_name": self.behavior_name,
            "status": self.status,
            "progress": self.progress,
            "safe_to_interrupt": self.safe_to_interrupt,
            "current_action": self.current_action,
            "message": self.message,
        }


@dataclass
class ExecuteBehaviorResult:
    """Final result of a behavior execution."""
    goal_id: str = ""
    behavior_id: str = ""
    behavior_name: str = ""
    status: str = "SUCCESS"
    result: str = "completed"
    reason: str = ""
    reward: float = 0.0
    emotion_delta_json: str = "{}"
    need_delta_json: str = "{}"

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "behavior_id": self.behavior_id,
            "behavior_name": self.behavior_name,
            "status": self.status,
            "result": self.result,
            "reason": self.reason,
            "reward": self.reward,
            "emotion_delta_json": self.emotion_delta_json,
            "need_delta_json": self.need_delta_json,
        }
