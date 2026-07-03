"""Core data types for the bionic dog behavior tree framework."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ActiveBehavior:
    """A behavior candidate injected by the input provider (upstream perception/needs).

    This is the input signal that the behavior tree consumes each tick.
    """

    behavior_id: str
    behavior_name: str
    priority_level: int
    value: float
    confidence: float
    need_type: str
    interrupt_policy: str = "immediate"
    preempt_current: bool = False
    target_id: Optional[str] = None
    params: dict = field(default_factory=dict)
    style: dict = field(default_factory=dict)
    timeout_sec: float = 30.0
    cooldown_sec: float = 0.0
    created_at: float = field(default_factory=time.time)


@dataclass
class BehaviorSpec:
    """Static specification for a behavior loaded from YAML config."""

    name: str
    priority_level: int
    base_priority: int
    interrupt_policy: str = "immediate"
    timeout_sec: float = 30.0
    cooldown_sec: float = 0.0
    action_sequence: list[dict] = field(default_factory=list)
    default_params: dict = field(default_factory=dict)
    style_modifiers: dict = field(default_factory=dict)


@dataclass
class BehaviorFeedbackEvent:
    """Emitted when a behavior completes (success, failure, or cancellation)."""

    behavior_id: str
    behavior_name: str
    status: str  # SUCCESS, FAILURE, CANCELED
    result: str
    reason: str
    reward: float = 0.0
    emotion_delta: dict = field(default_factory=dict)
    need_delta: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class EmotionState:
    """Current state of an emotion channel with decay dynamics.

    Emotions are set by upstream modules when they overflow a threshold.
    They naturally decay over time. The behavior tree checks current values
    before executing emotion-triggered behaviors to avoid acting on stale signals.
    """

    name: str
    current_value: float = 0.0  # 0..100
    overflow_threshold: float = 70.0
    decay_rate: float = 5.0  # units per second
    last_update: float = field(default_factory=time.time)


@dataclass
class NeedState:
    """Current state of an internal need channel.

    Modeled after ROS2 /internal_need/state messages. Each need has:
    - current_value: current intensity (0-100)
    - trigger_threshold / trigger_operator: crossing this fires TRIGGERED
    - overflow_threshold / overflow_operator: crossing this fires OVERFLOW
    - level: "NORMAL" | "TRIGGERED" | "OVERFLOW"
    """

    name: str
    current_value: float = 0.0  # 0..100
    trigger_threshold: float = 70.0
    trigger_operator: str = "gt"  # "gt" or "lt"
    overflow_threshold: float = 90.0
    overflow_operator: str = "gt"
    level: str = "NORMAL"  # NORMAL, TRIGGERED, OVERFLOW
    previous_level: str = "NORMAL"
    last_update: float = field(default_factory=time.time)


@dataclass
class ExecutorFeedback:
    """Periodic feedback from the action executor about goal progress."""

    behavior_id: str
    behavior_name: str
    status: str  # RUNNING, SUCCESS, FAILURE, CANCELED
    progress: float = 0.0  # 0.0 .. 1.0
    safe_to_interrupt: bool = False
    message: str = ""
