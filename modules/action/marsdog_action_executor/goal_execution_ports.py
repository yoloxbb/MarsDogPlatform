"""Explicit dependencies for the transport-independent orchestration.

Mutable state has one owner. Adapters provide live views; policy never receives
a ROS node or a generic attribute forwarding facade.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Protocol


class ExecutionState(Protocol):
    current_priority: int
    reserved_goal_id: str | None
    long_goal_id: str | None


@dataclass
class MemoryExecutionState:
    current_priority: int = 0
    reserved_goal_id: str | None = None
    long_goal_id: str | None = None


@dataclass(frozen=True)
class ExecutionPorts:
    approach_adapters: Any
    approach_navigation_adapter: Any
    behavior_execution_lock: Any
    behavior_resolver: Any
    behavior_sounds: Any
    chassis_backend: Any
    config: Any
    controller_routes: Any
    debug: Any
    execute_behavior: Callable[..., Any]
    execute_emergency_stop: Callable[..., Any]
    execute_long_behavior: Callable[..., Any]
    goal_parser: Any
    goal_reservation_lock: Any
    interrupt: Any
    lease_expired: Callable[..., Any]
    lease_lock: Any
    lease_seen: Any
    local_motion_adapter: Any
    mobility_adapter: Any
    person_nav_approach_adapter: Any
    posture: Any
    publish_feedback: Callable[..., Any]
    result_evaluator: Any
    stage_executor: Any
    stationary_expression_adapter: Any
    target_approach_adapter: Any
    uwb_follow_adapter: Any
    uwb_roam_adapter: Any
    visual_target_approach_adapter: Any
    wake_orientation_adapter: Any
    waypoint_nav_client: Any
    get_logger: Callable[..., Any]
    preempt_lock_wait_sec: Callable[[], float]
    motion_ownership: Any
    motion_lease_for: Callable[..., Any]
    forget_motion_lease: Callable[..., Any]
    stop_motion: Callable[[], None]
    unresolved_motion: Callable[[], tuple[str, ...]]


@dataclass(frozen=True)
class ExecutionRuntime:
    state: ExecutionState
    ports: ExecutionPorts
