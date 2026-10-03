"""ROS2 Action Server node for the MarsDog action executor.

Provides the ``/execute_behavior`` Action Server and optional debug topics.

Architecture (v2)::

    ROS2 Action goal
        │
        ▼
    GoalParser         ← params_json → ExecutionContext
        │
        ▼
    BehaviorResolver   ← exact behavior-name validation
        │
        ▼
    StageExecutor      ← filter candidates → select → execute units / stage
        │
        ▼
    ResultEvaluator    ← behavior-level success condition

Key interfaces:
  - Action Server: ``/execute_behavior`` (marsdog_interfaces/action/ExecuteBehavior)
  - Debug topics:   ``/debug/execute_behavior/goal|feedback|result``

Run via::

    ros2 run marsdog_action_executor action_executor_node
"""

from __future__ import annotations

from marsdog_observability import configure, bind_context, emit, get_logger

from .telemetry import goal_fields
from . import goal_execution

from . import goal_lifecycle

from . import action_messages

from .goal_contract import _normalise_goal_timeout, _outer_runtime_deadline, _navigation_cancel_won, _debug_goal_from_request

from .perception_dispatch import _dispatch_visual_event, _dispatch_object_detection

import json
import logging
import math
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from .adapters.velocity import TwistCommand
from .adapters.go2_sport_backend import (
    Go2ChassisBackend,
    Ros2Go2SportPublisher,
)
from .adapters.lite3_backend import (
    Lite3ChassisBackend,
    Ros2Lite3StatusSubscriber,
    make_ros2_lite3_backend,
)
from .adapters.attention_tracking_controller import (
    AttentionTrackingController,
)
from .adapters.navigation_adapter import (
    BehaviorMobilityAdapter,
    Ros2Nav2Client,
)
from .adapters.waypoint_nav_adapter import (
    Ros2WaypointNavClient,
    WaypointNavStatus,
)
from .adapters.wake_orientation_adapter import (
    Ros2Nav2SpinClient,
    WakeOrientationAdapter,
)
from .adapters.target_approach_adapter import TargetApproachAdapter
from .adapters.person_nav_approach_adapter import (
    PersonNavApproachAdapter,
    Ros2PersonApproachTransport,
)
from .adapters.visual_target_approach_adapter import (
    VisualTargetApproachAdapter,
)
from .adapters.stationary_expression_adapter import (
    StationaryExpressionAdapter,
)
from .adapters.uwb_follow_adapter import UwbFollowAdapter
from .adapters.uwb_follow_action_adapter import UwbFollowActionAdapter
from .adapters.uwb_roam_adapter import UwbRoamAdapter
from .behavior_resolver import BehaviorResolver
from .config_loader import ConfigLoader, installed_config_dir
from .debug_publishers import DebugPublishers
from .eligibility_checker import EligibilityChecker
from .execution_context import ExecutionContext, parse_params_json_object
from .goal_parser import GoalParser
from .interrupt_manager import InterruptManager
from .models import BehaviorGoal, ExecutionFeedback, ExecutionResult
from .posture_manager import PostureManager
from .result_evaluator import ResultEvaluator
from .ros2_compat import HAS_ROS2, get_execute_behavior_action, get_action_source
from .sound_player import BehaviorSoundController
from .stage_executor import StageExecutor, StageResult
from .stationary_policy import (
    INPLACE_WITH_HUMAN_BEHAVIORS,
    validate_inplace_plan,
)

logger = logging.getLogger(__name__)
_ExecuteBehavior = get_execute_behavior_action()








def _follow_is_driving(adapter) -> bool:
    """Whether a UWB controller currently owns chassis motion."""
    return adapter is not None and bool(adapter.active)








def _shutdown_rclpy_if_ok(
    rclpy_module,
    rcl_error_type: type[BaseException],
) -> bool:
    """Shut down one ROS context once, tolerating only the shutdown race.

    Returns ``True`` only when this call performed the shutdown.  A signal
    handler may close the default context between ``ok()`` and ``shutdown()``;
    that specific ``RCLError`` is an idempotent success path.  Other exception
    types deliberately propagate.
    """
    try:
        if not rclpy_module.ok():
            return False
        rclpy_module.shutdown()
    except rcl_error_type:
        return False
    return True

# ═══════════════════════════════════════════════════════════════════════════════
# ROS2-dependent class
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_ROS2:
    import rclpy
    from rclpy._rclpy_pybind11 import RCLError
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.utilities import get_rmw_implementation_identifier

    try:
        from marsdog_vision_interaction.srv import VisionTask
    except ImportError:
        VisionTask = None  # type: ignore[assignment,misc]

    class _VisionObjectDetectionLeaseClient:
        """Bounded synchronous facade over the asynchronous VisionTask service."""

        def __init__(
            self,
            node,
            *,
            service_name: str,
            timeout_sec: float,
            confidence: float,
            callback_group,
        ) -> None:
            self._node = node
            self._timeout_sec = max(0.1, float(timeout_sec))
            self._confidence = min(1.0, max(0.0, float(confidence)))
            self._client = (
                node.create_client(
                    VisionTask,
                    service_name,
                    callback_group=callback_group,
                )
                if VisionTask is not None
                else None
            )

        @property
        def available(self) -> bool:
            return self._client is not None

        def start(
            self,
            session_id: str,
            labels: list[str],
            rate_hz: float,
            lease_sec: float,
        ) -> tuple[bool, str]:
            return self._call({
                "enabled": True,
                "session_id": session_id,
                "target_labels": labels,
                "rate_hz": float(rate_hz),
                "confidence": self._confidence,
                "lease_sec": float(lease_sec),
            })

        def stop(self, session_id: str) -> None:
            ok, reason = self._call({
                "enabled": False,
                "session_id": session_id,
            })
            if not ok:
                self._node.get_logger().warning(
                    "Object detection stream stop failed: "
                    f"session={session_id} reason={reason}"
                )

        def _call(self, params: dict) -> tuple[bool, str]:
            client = self._client
            if client is None:
                return False, "vision_task_interface_unavailable"
            if not client.wait_for_service(timeout_sec=self._timeout_sec):
                return False, "vision_task_service_unavailable"
            request = VisionTask.Request()
            request.task_id = f"action-object-{uuid.uuid4().hex}"
            request.task_type = "set_object_detection"
            request.params_json = json.dumps(params, ensure_ascii=False)
            future = client.call_async(request)
            completed = threading.Event()
            future.add_done_callback(lambda _future: completed.set())
            if not completed.wait(self._timeout_sec):
                future.cancel()
                return False, "vision_task_service_timeout"
            try:
                response = future.result()
            except Exception as exc:
                return False, f"vision_task_service_error:{exc}"
            if response is None:
                return False, "vision_task_empty_response"
            try:
                result = json.loads(response.result_json or "{}")
            except (json.JSONDecodeError, TypeError):
                result = {}
            ok = bool(response.success) and bool(result.get("ok", False))
            reason = str(
                result.get("error")
                or response.error_message
                or ("" if ok else "vision_task_rejected")
            )
            return ok, reason

    class ActionExecutorNode(Node):
        """ROS2 node wrapping the v2 execution pipeline.

        Action Server: ``/execute_behavior``
        Debug Topics:  ``/debug/execute_behavior/goal|feedback|result``
        """

        def __init__(self) -> None:
            super().__init__("action_executor_node")
            configure("action")
            self.get_logger().info(
                "ROS transport: "
                f"domain_id={os.environ.get('ROS_DOMAIN_ID', '0')}, "
                f"rmw={get_rmw_implementation_identifier()}, "
                f"localhost_only={os.environ.get('ROS_LOCALHOST_ONLY', '0')}"
            )

            # ── Load configuration ──────────────────────────────────────
            self.declare_parameter("config_dir", "")
            explicit_config = str(self.get_parameter("config_dir").value)
            config_dir = Path(explicit_config) if explicit_config else self._resolve_config_dir()
            self.get_logger().info(f"Loading configs from: {config_dir}")
            self._config = ConfigLoader(config_dir)
            self._config.load_all()
            self.get_logger().info(
                f"Strict behavior-tree contract loaded: "
                f"{len(self._config.behavior_tree_templates)} behaviors, "
                f"{len(self._config.action_catalog)} actions"
            )

            # ── Build v2 pipeline ───────────────────────────────────────
            self._goal_parser = GoalParser()
            self._behavior_resolver = BehaviorResolver(
                canonical_behaviors=self._config.get_behavior_names(),
            )
            self._eligibility = EligibilityChecker(
                action_catalog=self._config.action_catalog,
            )
            self._posture = PostureManager()
            self._interrupt = InterruptManager()

            # ── Select the Go2 or Lite3 chassis backend ────────────────
            go2_config = self._config.go2_sport_config
            go2_limits = go2_config.get("limits", {})
            lite3_config = self._config.lite3_action_config
            lite3_limits = lite3_config.get("limits", {})
            self.declare_parameter("recharge_result_energy_value", 100.0)
            self.declare_parameter("chassis_type", "go2")
            self.declare_parameter("lite3_simulated_io", False)
            self.declare_parameter(
                "go2_enabled", bool(go2_config.get("enabled", False))
            )
            self.declare_parameter(
                "go2_request_topic",
                str(go2_config.get("request_topic", "/api/sport/request")),
            )
            self.declare_parameter(
                "go2_publish_rate_hz",
                float(go2_config.get("publish_rate_hz", 10.0)),
            )
            self.declare_parameter(
                "go2_max_linear_x",
                float(go2_limits.get("max_linear_x", 0.30)),
            )
            self.declare_parameter(
                "go2_min_linear_x",
                float(go2_limits.get("min_linear_x", 0.0)),
            )
            self.declare_parameter(
                "go2_max_linear_y",
                float(go2_limits.get("max_linear_y", 0.20)),
            )
            self.declare_parameter(
                "go2_max_angular_z",
                float(go2_limits.get("max_angular_z", 1.20)),
            )
            self.declare_parameter(
                "lite3_enabled", bool(lite3_config.get("enabled", False))
            )
            self.declare_parameter(
                "lite3_simple_cmd_topic",
                str(lite3_config.get("simple_cmd_topic", "/simple_cmd")),
            )
            self.declare_parameter(
                "lite3_status_topic",
                str(lite3_config.get("status_topic", "/robot_status")),
            )
            self.declare_parameter(
                "lite3_cmd_vel_topic",
                str(lite3_config.get("cmd_vel_topic", "/cmd_vel")),
            )
            self.declare_parameter(
                "lite3_allow_proxies",
                bool(lite3_config.get("allow_proxies", False)),
            )
            self.declare_parameter(
                "lite3_allow_unverified",
                bool(lite3_config.get("allow_unverified", False)),
            )
            self.declare_parameter(
                "lite3_publish_rate_hz",
                float(lite3_config.get("publish_rate_hz", 20.0)),
            )
            self.declare_parameter(
                "lite3_max_linear_x",
                float(lite3_limits.get("max_linear_x", 0.20)),
            )
            self.declare_parameter(
                "lite3_max_linear_y",
                float(lite3_limits.get("max_linear_y", 0.15)),
            )
            self.declare_parameter(
                "lite3_max_angular_z",
                float(lite3_limits.get("max_angular_z", 0.80)),
            )

            self._twist_publisher = None
            self._go2_publisher: Ros2Go2SportPublisher | None = None
            self._lite3_command_publisher = None
            self._lite3_status_subscriber: Ros2Lite3StatusSubscriber | None = None
            self._chassis_backend: (
                Go2ChassisBackend | Lite3ChassisBackend | None
            ) = None
            controller_adapters = {}
            chassis_type = str(
                self.get_parameter("chassis_type").value
            ).strip().lower()
            if chassis_type not in {"go2", "lite3"}:
                raise RuntimeError(
                    f"Unsupported chassis_type={chassis_type!r}; "
                    "expected 'go2' or 'lite3'"
                )

            rate_parameter = {
                "go2": "go2_publish_rate_hz",
                "lite3": "lite3_publish_rate_hz",
            }[chassis_type]
            linear_parameter = {
                "go2": "go2_max_linear_x",
                "lite3": "lite3_max_linear_x",
            }[chassis_type]
            angular_parameter = {
                "go2": "go2_max_angular_z",
                "lite3": "lite3_max_angular_z",
            }[chassis_type]
            chassis_publish_rate = float(
                self.get_parameter(rate_parameter).value
            )
            chassis_max_linear = float(
                self.get_parameter(linear_parameter).value
            )
            chassis_max_angular = float(
                self.get_parameter(angular_parameter).value
            )
            backend_config = {
                "go2": go2_config,
                "lite3": lite3_config,
            }[chassis_type]
            chassis_stop_count = int(backend_config.get("stop_publish_count", 3))

            if (
                chassis_type == "go2"
                and bool(self.get_parameter("go2_enabled").value)
            ):
                self._go2_publisher = Ros2Go2SportPublisher(
                    self,
                    str(self.get_parameter("go2_request_topic").value),
                )
                self._chassis_backend = Go2ChassisBackend(
                    request_publisher=self._go2_publisher,
                    action_sequences=self._config.get_go2_action_sequences(),
                    publish_rate_hz=chassis_publish_rate,
                    max_linear_x=chassis_max_linear,
                    min_linear_x=float(
                        self.get_parameter("go2_min_linear_x").value
                    ),
                    max_linear_y=float(
                        self.get_parameter("go2_max_linear_y").value
                    ),
                    max_angular_z=chassis_max_angular,
                    stop_publish_count=chassis_stop_count,
                    should_stop=lambda: self._interrupt.cancel_requested,
                )
                self._twist_publisher = self._chassis_backend.twist_publisher
                controller_adapters["go2"] = self._chassis_backend
                self.get_logger().info(
                    "Go2 SportMode backend enabled: "
                    f"topic={self.get_parameter('go2_request_topic').value}, "
                    f"rate={chassis_publish_rate}Hz, "
                    f"mapped_actions={len(self._chassis_backend.mapped_actions)}"
                )
            elif (
                chassis_type == "lite3"
                and bool(self.get_parameter("lite3_enabled").value)
            ):
                simulated_io = bool(self.get_parameter("lite3_simulated_io").value)
                backend_factory = make_ros2_lite3_backend
                if simulated_io:
                    from .adapters.simulated_lite3 import make_simulated_lite3_backend
                    backend_factory = make_simulated_lite3_backend
                (
                    self._chassis_backend,
                    self._lite3_command_publisher,
                    _lite3_twist_publisher,
                ) = backend_factory(
                    self,
                    simple_cmd_topic=str(
                        self.get_parameter("lite3_simple_cmd_topic").value
                    ),
                    cmd_vel_topic=str(
                        self.get_parameter("lite3_cmd_vel_topic").value
                    ),
                    action_plans=self._config.get_lite3_action_plans(),
                    # The follow adapter is built further down in this same
                    # branch, so the lambda has to defer the lookup: the
                    # checker runs on the first ownership preflight, long
                    # after __init__.  It tells a *driving* follow from an
                    # idle one, which is what lets a wake turn or Nav2 take
                    # /cmd_vel back between follow goals.
                    uwb_driving=lambda: _follow_is_driving(
                        getattr(self, "_uwb_follow_adapter", None)
                    ) or bool(getattr(getattr(self, "_uwb_roam_adapter", None), "active", False)),
                    allow_proxies=bool(
                        self.get_parameter("lite3_allow_proxies").value
                    ),
                    allow_unverified=bool(
                        self.get_parameter("lite3_allow_unverified").value
                    ),
                    accepted_unverified_actions=list(
                        lite3_config.get("accepted_unverified_actions", [])
                    ),
                    status_timeout_sec=float(
                        lite3_config.get("status_timeout_sec", 1.0)
                    ),
                    min_battery_percent=float(
                        lite3_config.get("min_battery_percent", 25.0)
                    ),
                    minimum_backward_clearance_m=float(
                        lite3_config.get(
                            "minimum_backward_clearance_m", 0.60
                        )
                    ),
                    mode_settle_sec=float(
                        lite3_config.get("mode_settle_sec", 0.10)
                    ),
                    navigation_settle_timeout_sec=float(
                        lite3_config.get(
                            "navigation_settle_timeout_sec", 2.0
                        )
                    ),
                    navigation_stable_samples=int(
                        lite3_config.get("navigation_stable_samples", 5)
                    ),
                    posture_recovery_timeout_sec=float(
                        lite3_config.get("posture_recovery_timeout_sec", 6.0)
                    ),
                    publish_rate_hz=chassis_publish_rate,
                    max_linear_x=chassis_max_linear,
                    max_linear_y=float(
                        self.get_parameter("lite3_max_linear_y").value
                    ),
                    max_angular_z=chassis_max_angular,
                    stop_publish_count=chassis_stop_count,
                    command_repeat=int(lite3_config.get("command_repeat", 1)),
                    command_repeat_interval_sec=float(
                        lite3_config.get("command_repeat_interval_sec", 0.05)
                    ),
                    should_stop=lambda: self._interrupt.cancel_requested,
                )
                self._lite3_status_subscriber = None
                if not simulated_io:
                    self._lite3_status_subscriber = Ros2Lite3StatusSubscriber(
                        self,
                        self._chassis_backend.update_status,
                        str(self.get_parameter("lite3_status_topic").value),
                    )
                self._twist_publisher = self._chassis_backend.twist_publisher
                controller_adapters["lite3"] = self._chassis_backend
                self.get_logger().info(
                    "Lite3 chassis backend enabled: "
                    f"cmd_vel={self.get_parameter('lite3_cmd_vel_topic').value}, "
                    f"simple_cmd={self.get_parameter('lite3_simple_cmd_topic').value}, "
                    f"status={self.get_parameter('lite3_status_topic').value}, "
                    f"mapped_actions={len(self._chassis_backend.mapped_actions)}, "
                    f"enabled_actions={len(self._chassis_backend.enabled_actions)}, "
                    f"navigation_settle="
                    f"{lite3_config.get('navigation_stable_samples', 5)} samples/"
                    f"{lite3_config.get('navigation_settle_timeout_sec', 2.0)}s"
                )
            else:
                enabled_parameter = {
                    "go2": "go2_enabled",
                    "lite3": "lite3_enabled",
                }[chassis_type]
                self.get_logger().info(
                    f"{chassis_type.upper()} chassis backend disabled; set "
                    f"{enabled_parameter}:=true"
                )

            self._controller_routes = self._config.get_controller_routes(
                chassis_type
            )

            # Always install the fail-closed stationary route. With a chassis
            # backend it publishes redundant stop commands; in simulation the
            # publisher is a no-op while cancel/timing semantics stay equal.
            self._stationary_expression_adapter = StationaryExpressionAdapter(
                publish_twist=self._twist_publisher,
                publish_rate_hz=chassis_publish_rate,
                stop_publish_count=chassis_stop_count,
                should_stop=lambda: self._interrupt.cancel_requested,
            )
            controller_adapters["stationary_expression"] = (
                self._stationary_expression_adapter
            )

            # ── Session-scoped UWB owner following ───────────────────
            uwb_config = self._config.uwb_follow_config
            self.declare_parameter(
                "uwb_follow_enabled", bool(uwb_config.get("enabled", True))
            )
            self.declare_parameter(
                "uwb_follow_setup_script",
                str(uwb_config.get("setup_script", "")),
            )
            self.declare_parameter(
                "uwb_follow_serial_device",
                str(uwb_config.get("serial_device", "")),
            )
            self.declare_parameter(
                "uwb_follow_cmd_vel_topic",
                str(uwb_config.get("cmd_vel_topic", "/cmd_vel")),
            )
            self.declare_parameter(
                "uwb_follow_target_fob_id",
                str(uwb_config.get("target_fob_id", "")),
            )
            # Lite3 follows through the go2_uwb_behavior Action interface;
            # Go2 uses its external UWB process pipeline.
            self._uwb_follow_adapter: (
                UwbFollowAdapter | UwbFollowActionAdapter | None
            ) = None
            if (
                bool(self.get_parameter("uwb_follow_enabled").value)
                and chassis_type in ("go2", "lite3")
                and self._twist_publisher is not None
            ):
                finish_motion = (
                    self._chassis_backend.finish_navigation
                    if chassis_type == "lite3"
                    and self._chassis_backend is not None
                    else None
                )
                if chassis_type == "lite3":
                    # Lite3 follows through the go2_uwb_behavior chain instead
                    # of spawning the pipeline itself: that package now owns
                    # /cmd_vel, and a second publisher would fight it.  See
                    # adapters/uwb_follow_action_adapter.py.
                    ros_interface = uwb_config.get("ros_interface") or {}
                    self._uwb_roam_adapter = UwbRoamAdapter(
                        node=self, backend=self._chassis_backend,
                        should_stop=lambda: self._interrupt.cancel_requested,
                        brake_ready=lambda: self._uwb_follow_adapter.brake_ready(),
                        brake_chain=lambda: self._uwb_follow_adapter.brake_chain(),
                        arm_chain=lambda: self._uwb_follow_adapter.arm_chain(),
                    )
                    controller_adapters["uwb_roam"] = self._uwb_roam_adapter
                    self._uwb_follow_adapter = UwbFollowActionAdapter(
                        enabled=True,
                        node=self,
                        follow_action=str(
                            ros_interface.get(
                                "follow_action", "/go2/follow_uwb"
                            )
                        ),
                        set_behavior_service=str(
                            ros_interface.get(
                                "set_behavior_service", "/go2/set_behavior"
                            )
                        ),
                        server_timeout_sec=float(
                            ros_interface.get("server_timeout_sec", 5.0)
                        ),
                        ready_timeout_sec=float(
                            ros_interface.get("ready_timeout_sec", 4.0)
                        ),
                        prepare_motion=(
                            self._chassis_backend.prepare_navigation
                            if self._chassis_backend is not None
                            else None
                        ),
                        finish_motion=finish_motion,
                        should_stop=lambda: self._interrupt.cancel_requested,
                        auto_resume=False,
                    )
                    self.get_logger().info(
                        "go2_uwb_behavior follow client ready: "
                        f"action="
                        f"{ros_interface.get('follow_action', '/go2/follow_uwb')}, "
                        f"service="
                        f"{ros_interface.get('set_behavior_service', '/go2/set_behavior')}"
                    )
                else:
                    self._uwb_follow_adapter = UwbFollowAdapter(
                        enabled=True,
                        setup_script=str(
                            self.get_parameter("uwb_follow_setup_script").value
                        ),
                        serial_device=str(
                            self.get_parameter("uwb_follow_serial_device").value
                        ),
                        cmd_vel_topic=str(
                            self.get_parameter("uwb_follow_cmd_vel_topic").value
                        ),
                        aoa_package=str(
                            uwb_config.get("aoa_package", "uwb_aoa_pkg")
                        ),
                        aoa_executable=str(
                            uwb_config.get(
                                "aoa_executable", "libAoa_robot_example"
                            )
                        ),
                        target_fob_id=str(
                            self.get_parameter("uwb_follow_target_fob_id").value
                        ),
                        follow_package=str(
                            uwb_config.get(
                                "follow_package", "go2_uwb_local_follow"
                            )
                        ),
                        follow_launch_file=str(
                            uwb_config.get(
                                "follow_launch_file", "local_follow.launch.py"
                            )
                        ),
                        startup_grace_sec=float(
                            uwb_config.get("startup_grace_sec", 1.0)
                        ),
                        shutdown_timeout_sec=float(
                            uwb_config.get("shutdown_timeout_sec", 3.0)
                        ),
                        target_timeout_sec=float(
                            uwb_config.get("target_timeout_sec", 3.0)
                        ),
                        stop_publish_count=int(
                            uwb_config.get("stop_publish_count", 3)
                        ),
                        publish_twist=self._twist_publisher,
                        prepare_motion=None,
                        finish_motion=finish_motion,
                        should_stop=lambda: self._interrupt.cancel_requested,
                        auto_resume=False,
                    )
                    self.get_logger().info(
                        "external UWB follow adapter ready: "
                        "serial="
                        f"{self.get_parameter('uwb_follow_serial_device').value}, "
                        "fob_id="
                        f"{self.get_parameter('uwb_follow_target_fob_id').value}, "
                        "cmd_vel="
                        f"{self.get_parameter('uwb_follow_cmd_vel_topic').value}"
                    )
                    from geometry_msgs.msg import PointStamped
                    self.create_subscription(
                        PointStamped,
                        str(uwb_config.get("target_topic", "/uwb/target_point")),
                        lambda msg: self._uwb_follow_adapter.update_target(
                            float(msg.point.x), float(msg.point.y)
                        ),
                        10,
                    )
                    from diagnostic_msgs.msg import DiagnosticArray
                    self.create_subscription(
                        DiagnosticArray,
                        str(uwb_config.get(
                            "diagnostics_topic",
                            "/go2_uwb_local_follow/follow_diagnostics",
                        )),
                        self._on_uwb_follow_diagnostics,
                        10,
                    )
                controller_adapters["uwb_follow"] = self._uwb_follow_adapter
            elif bool(self.get_parameter("uwb_follow_enabled").value):
                self.get_logger().info(
                    "UWB follow adapter inactive; enable the selected chassis backend"
                )

            # ── Dynamic wake-source orientation through Nav2 Spin ─────
            wake_config = self._config.wake_orientation_config
            self.declare_parameter(
                "wake_orientation_enabled",
                bool(wake_config.get("enabled", True)),
            )
            self.declare_parameter(
                "wake_spin_action_name",
                str(wake_config.get("action_name", "/spin")),
            )
            self.declare_parameter(
                "wake_spin_server_timeout_sec",
                float(wake_config.get("server_timeout_sec", 5.0)),
            )
            self.declare_parameter(
                "wake_spin_result_timeout_sec",
                float(wake_config.get("result_timeout_sec", 15.0)),
            )
            self.declare_parameter(
                "wake_spin_time_allowance_sec",
                float(wake_config.get("time_allowance_sec", 12.0)),
            )
            self.declare_parameter(
                "wake_angle_zero_offset_deg",
                float(wake_config.get("angle_zero_offset_deg", 90.0)),
            )
            self.declare_parameter(
                "wake_angle_direction_sign",
                float(wake_config.get("angle_direction_sign", -1.0)),
            )
            self.declare_parameter(
                "wake_angle_deadband_deg",
                float(wake_config.get("angle_deadband_deg", 5.0)),
            )
            self.declare_parameter(
                "wake_angle_frame_id",
                str(
                    wake_config.get(
                        "required_frame_id",
                        "microphone_array",
                    )
                ),
            )
            self.declare_parameter(
                "wake_linear_array_back_search_enabled",
                bool(
                    wake_config.get(
                        "linear_array_back_search_enabled", False
                    )
                ),
            )
            self.declare_parameter(
                "wake_visual_confirm_timeout_sec",
                float(wake_config.get("visual_confirm_timeout_sec", 1.5)),
            )
            self.declare_parameter(
                "wake_visual_min_confidence",
                float(wake_config.get("visual_min_confidence", 0.60)),
            )
            self.declare_parameter(
                "wake_visual_max_age_ms",
                float(wake_config.get("visual_max_age_ms", 800.0)),
            )

            self._spin_client: Ros2Nav2SpinClient | None = None
            self._wake_orientation_adapter: (
                WakeOrientationAdapter | None
            ) = None
            wake_enabled = bool(
                self.get_parameter("wake_orientation_enabled").value
            )
            if wake_enabled and self._chassis_backend is not None:
                self._spin_client = Ros2Nav2SpinClient(
                    self,
                    action_name=str(
                        self.get_parameter("wake_spin_action_name").value
                    ),
                    server_timeout_sec=float(
                        self.get_parameter(
                            "wake_spin_server_timeout_sec"
                        ).value
                    ),
                    should_stop=lambda: self._interrupt.cancel_requested,
                )
                self._wake_orientation_adapter = WakeOrientationAdapter(
                    spin_relative=self._spin_client,
                    angle_zero_offset_deg=float(
                        self.get_parameter(
                            "wake_angle_zero_offset_deg"
                        ).value
                    ),
                    angle_direction_sign=float(
                        self.get_parameter(
                            "wake_angle_direction_sign"
                        ).value
                    ),
                    angle_deadband_deg=float(
                        self.get_parameter(
                            "wake_angle_deadband_deg"
                        ).value
                    ),
                    required_frame_id=str(
                        self.get_parameter("wake_angle_frame_id").value
                    ),
                    result_timeout_sec=float(
                        self.get_parameter(
                            "wake_spin_result_timeout_sec"
                        ).value
                    ),
                    time_allowance_sec=float(
                        self.get_parameter(
                            "wake_spin_time_allowance_sec"
                        ).value
                    ),
                    linear_array_back_search_enabled=bool(
                        self.get_parameter(
                            "wake_linear_array_back_search_enabled"
                        ).value
                    ),
                    visual_confirm_timeout_sec=float(
                        self.get_parameter(
                            "wake_visual_confirm_timeout_sec"
                        ).value
                    ),
                    visual_min_confidence=float(
                        self.get_parameter(
                            "wake_visual_min_confidence"
                        ).value
                    ),
                    visual_max_age_ms=float(
                        self.get_parameter("wake_visual_max_age_ms").value
                    ),
                    should_stop=lambda: self._interrupt.cancel_requested,
                    # Same injection contract as navigation_adapter and the
                    # UWB follow adapter: Nav2 turns the dog over the ordinary
                    # /cmd_vel topic, and on Lite3 that only works once the
                    # backend hands control over (Vision Mode).  Without this
                    # the Spin goal streams at full speed while the dog, still
                    # on the joystick, drops every sample.  getattr keeps the
                    # hook optional for backends that drive Nav2 themselves.
                    prepare_motion=getattr(
                        self._chassis_backend,
                        "prepare_navigation",
                        None,
                    ),
                    finish_motion=getattr(
                        self._chassis_backend,
                        "finish_navigation",
                        None,
                    ),
                )
                controller_adapters[
                    "wake_orientation"
                ] = self._wake_orientation_adapter
                self.get_logger().info(
                    "Wake orientation adapter enabled: "
                    f"action={self.get_parameter('wake_spin_action_name').value}, "
                    f"frame={self.get_parameter('wake_angle_frame_id').value}, "
                    f"zero_offset="
                    f"{self.get_parameter('wake_angle_zero_offset_deg').value}deg, "
                    f"direction_sign="
                    f"{self.get_parameter('wake_angle_direction_sign').value}, "
                    f"deadband="
                    f"{self.get_parameter('wake_angle_deadband_deg').value}deg, "
                    f"linear_back_search="
                    f"{self.get_parameter('wake_linear_array_back_search_enabled').value}"
                )
            elif wake_enabled:
                self.get_logger().info(
                    "Wake orientation adapter inactive; "
                    "enable the selected chassis backend"
                )
            else:
                self.get_logger().info(
                    "Wake orientation adapter disabled"
                )

            # ── Optional Nav2 semantic-waypoint adapter ───────────────
            navigation_config = self._config.navigation_config
            self.declare_parameter(
                "navigation_enabled",
                bool(navigation_config.get("enabled", False)),
            )
            self.declare_parameter(
                "navigation_action_name",
                str(
                    navigation_config.get(
                        "action_name",
                        "/navigate_to_pose",
                    )
                ),
            )
            self.declare_parameter(
                "navigation_frame_id",
                str(navigation_config.get("frame_id", "map")),
            )
            self.declare_parameter(
                "navigation_server_timeout_sec",
                float(
                    navigation_config.get("server_timeout_sec", 10.0)
                ),
            )
            self.declare_parameter(
                "navigation_result_timeout_sec",
                float(
                    navigation_config.get("result_timeout_sec", 300.0)
                ),
            )
            waypoint_nav_config = navigation_config.get("waypoint_nav", {})
            self.declare_parameter(
                "waypoint_nav_service_name",
                str(waypoint_nav_config.get("service_name", "/waypoint_nav/task")),
            )
            self.declare_parameter(
                "waypoint_nav_status_topic",
                str(waypoint_nav_config.get("status_topic", "/waypoint_nav/status")),
            )
            self.declare_parameter(
                "waypoint_nav_protocol_version",
                str(waypoint_nav_config.get("protocol_version", "1.0")),
            )
            self.declare_parameter(
                "waypoint_nav_client_id",
                str(waypoint_nav_config.get("client_id", "marsdog_action_executor")),
            )
            self.declare_parameter(
                "waypoint_nav_service_timeout_sec",
                float(waypoint_nav_config.get("service_timeout_sec", 5.0)),
            )
            self.declare_parameter(
                "waypoint_nav_query_timeout_sec",
                float(waypoint_nav_config.get("query_timeout_sec", 2.0)),
            )
            self.declare_parameter(
                "waypoint_nav_cancel_confirmation_timeout_sec",
                float(
                    waypoint_nav_config.get(
                        "cancel_confirmation_timeout_sec", 5.0
                    )
                ),
            )
            self.declare_parameter(
                "waypoint_nav_terminal_retention_sec",
                float(waypoint_nav_config.get("terminal_retention_sec", 86400.0)),
            )
            self.declare_parameter(
                "navigation_preempt_lock_wait_sec",
                float(waypoint_nav_config.get("preempt_lock_wait_sec", 8.0)),
            )

            self._nav2_client: Ros2Nav2Client | None = None
            self._waypoint_nav_client: Ros2WaypointNavClient | None = None
            self._mobility_adapter: BehaviorMobilityAdapter | None = None
            if self.get_parameter("navigation_enabled").value:
                if self._chassis_backend is None:
                    raise RuntimeError(
                        "navigation_enabled requires the selected chassis "
                        "backend to be enabled"
                    )
                self._nav2_client = Ros2Nav2Client(
                    self,
                    action_name=str(
                        self.get_parameter(
                            "navigation_action_name"
                        ).value
                    ),
                    frame_id=str(
                        self.get_parameter("navigation_frame_id").value
                    ),
                    server_timeout_sec=float(
                        self.get_parameter(
                            "navigation_server_timeout_sec"
                        ).value
                    ),
                    should_stop=lambda: self._interrupt.cancel_requested,
                )
                self._waypoint_nav_client = Ros2WaypointNavClient(
                    self,
                    service_name=str(
                        self.get_parameter("waypoint_nav_service_name").value
                    ),
                    status_topic=str(
                        self.get_parameter("waypoint_nav_status_topic").value
                    ),
                    protocol_version=str(
                        self.get_parameter("waypoint_nav_protocol_version").value
                    ),
                    client_id=str(
                        self.get_parameter("waypoint_nav_client_id").value
                    ),
                    service_timeout_sec=float(
                        self.get_parameter("waypoint_nav_service_timeout_sec").value
                    ),
                    query_timeout_sec=float(
                        self.get_parameter("waypoint_nav_query_timeout_sec").value
                    ),
                    cancel_confirmation_timeout_sec=float(
                        self.get_parameter(
                            "waypoint_nav_cancel_confirmation_timeout_sec"
                        ).value
                    ),
                    terminal_retention_sec=float(
                        self.get_parameter(
                            "waypoint_nav_terminal_retention_sec"
                        ).value
                    ),
                    should_stop=lambda: self._interrupt.cancel_requested,
                )
                self._mobility_adapter = BehaviorMobilityAdapter(
                    navigate_waypoint=self._nav2_client,
                    navigate_fixed_place=self._waypoint_nav_client,
                    fixed_places=waypoint_nav_config["places"],
                    motion_adapter=self._chassis_backend,
                    waypoints=navigation_config["waypoints"],
                    behavior_routes=navigation_config["behavior_routes"],
                    stage_actions=navigation_config["stage_actions"],
                    result_timeout_sec=float(
                        self.get_parameter(
                            "navigation_result_timeout_sec"
                        ).value
                    ),
                    random_navigation_behaviors=navigation_config.get(
                        "random_navigation_behaviors", []
                    ),
                    random_navigation_place=navigation_config.get(
                        "random_navigation_place"
                    ),
                    random_navigation_result_timeout_sec=navigation_config.get(
                        "random_navigation_result_timeout_sec"
                    ),
                    random_navigation_in_place_probability=(
                        navigation_config.get(
                            "random_navigation_in_place_probability", {}
                        )
                    ),
                    random_navigation_fixed_pool=navigation_config.get(
                        "random_navigation_fixed_pool"
                    ),
                )
                controller_adapters[
                    "behavior_mobility"
                ] = self._mobility_adapter
                self.get_logger().info(
                    "Navigation adapter enabled: "
                    f"fixed_service="
                    f"{self.get_parameter('waypoint_nav_service_name').value}, "
                    f"random_place="
                    f"{self._mobility_adapter._random_navigation_place}, "
                    f"random_pool="
                    f"{','.join(self._mobility_adapter._random_navigation_fixed_pool) or '<server>'},"
                    f"frame={self.get_parameter('navigation_frame_id').value}, "
                    f"waypoints={len(navigation_config['waypoints'])}, "
                    f"routed_behaviors="
                    f"{len(self._mobility_adapter.routed_behaviors)}, "
                    f"random_nav_behaviors="
                    f"{len(self._mobility_adapter._random_navigation_behaviors)}, "
                    f"mapped_stage_actions="
                    f"{len(navigation_config['stage_actions'])}"
                )
            else:
                self.get_logger().info(
                    "Navigation adapter disabled; set "
                    "navigation_enabled:=true with a chassis backend enabled"
                )

            # ── Closed-loop approach to the selected voice caller ───────
            target_defaults = {
                "target_approach_enabled": True,
                "target_approach_publish_rate_hz": 10.0,
                "target_approach_min_confidence": 0.60,
                "target_approach_visual_timeout_sec": 0.8,
                "target_approach_acquire_timeout_sec": 3.0,
                "target_approach_lost_timeout_sec": 1.0,
                "target_approach_timeout_sec": 20.0,
                "target_approach_stop_distance_m": 1.20,
                "target_approach_minimum_safe_distance_m": 0.80,
                "target_approach_distance_deadband_m": 0.15,
                "target_approach_distance_hysteresis_m": 0.10,
                "target_approach_arrival_hold_sec": 0.5,
                "target_approach_linear_gain": 0.50,
                "target_approach_angular_gain": 0.80,
                "target_approach_max_linear_x": 0.15,
                "target_approach_max_angular_z": 0.30,
                "target_approach_max_linear_accel": 0.20,
                "target_approach_max_angular_accel": 0.30,
                "target_approach_heading_deadband": 0.06,
                "target_approach_max_heading_error": 0.25,
                "target_approach_allow_bbox_distance_fallback": False,
                "target_approach_demo_target_height": 0.68,
                "target_approach_demo_height_deadband": 0.05,
                "target_approach_bbox_height_hysteresis": 0.03,
                "target_approach_reacquire_min_consecutive_frames": 3,
            }
            for parameter_name, default_value in target_defaults.items():
                self.declare_parameter(parameter_name, default_value)

            self._target_approach_adapter: TargetApproachAdapter | None = None
            if (
                bool(self.get_parameter("target_approach_enabled").value)
                and self._twist_publisher is not None
            ):
                target_max_linear = min(
                    chassis_max_linear,
                    float(
                        self.get_parameter(
                            "target_approach_max_linear_x"
                        ).value
                    ),
                )
                target_max_angular = min(
                    chassis_max_angular,
                    float(
                        self.get_parameter(
                            "target_approach_max_angular_z"
                        ).value
                    ),
                )
                self._target_approach_adapter = TargetApproachAdapter(
                    publish_twist=self._twist_publisher,
                    publish_rate_hz=float(
                        self.get_parameter(
                            "target_approach_publish_rate_hz"
                        ).value
                    ),
                    min_confidence=float(
                        self.get_parameter(
                            "target_approach_min_confidence"
                        ).value
                    ),
                    visual_timeout_sec=float(
                        self.get_parameter(
                            "target_approach_visual_timeout_sec"
                        ).value
                    ),
                    acquire_timeout_sec=float(
                        self.get_parameter(
                            "target_approach_acquire_timeout_sec"
                        ).value
                    ),
                    lost_timeout_sec=float(
                        self.get_parameter(
                            "target_approach_lost_timeout_sec"
                        ).value
                    ),
                    approach_timeout_sec=float(
                        self.get_parameter(
                            "target_approach_timeout_sec"
                        ).value
                    ),
                    stop_distance_m=float(
                        self.get_parameter(
                            "target_approach_stop_distance_m"
                        ).value
                    ),
                    minimum_safe_distance_m=float(
                        self.get_parameter(
                            "target_approach_minimum_safe_distance_m"
                        ).value
                    ),
                    distance_deadband_m=float(
                        self.get_parameter(
                            "target_approach_distance_deadband_m"
                        ).value
                    ),
                    distance_hysteresis_m=float(
                        self.get_parameter(
                            "target_approach_distance_hysteresis_m"
                        ).value
                    ),
                    arrival_hold_sec=float(
                        self.get_parameter(
                            "target_approach_arrival_hold_sec"
                        ).value
                    ),
                    linear_gain=float(
                        self.get_parameter(
                            "target_approach_linear_gain"
                        ).value
                    ),
                    angular_gain=float(
                        self.get_parameter(
                            "target_approach_angular_gain"
                        ).value
                    ),
                    max_linear_x=target_max_linear,
                    max_angular_z=target_max_angular,
                    max_linear_accel=float(
                        self.get_parameter(
                            "target_approach_max_linear_accel"
                        ).value
                    ),
                    max_angular_accel=float(
                        self.get_parameter(
                            "target_approach_max_angular_accel"
                        ).value
                    ),
                    heading_deadband=float(
                        self.get_parameter(
                            "target_approach_heading_deadband"
                        ).value
                    ),
                    max_heading_error=float(
                        self.get_parameter(
                            "target_approach_max_heading_error"
                        ).value
                    ),
                    allow_bbox_distance_fallback=bool(
                        self.get_parameter(
                            "target_approach_allow_bbox_distance_fallback"
                        ).value
                    ),
                    demo_target_height=float(
                        self.get_parameter(
                            "target_approach_demo_target_height"
                        ).value
                    ),
                    demo_height_deadband=float(
                        self.get_parameter(
                            "target_approach_demo_height_deadband"
                        ).value
                    ),
                    bbox_height_hysteresis=float(
                        self.get_parameter(
                            "target_approach_bbox_height_hysteresis"
                        ).value
                    ),
                    reacquire_min_consecutive_frames=int(
                        self.get_parameter(
                            "target_approach_reacquire_min_consecutive_frames"
                        ).value
                    ),
                    stop_publish_count=chassis_stop_count,
                    should_stop=lambda: self._interrupt.cancel_requested,
                )
                controller_adapters[
                    "target_approach"
                ] = self._target_approach_adapter
                self.get_logger().info(
                    "Target approach adapter enabled: "
                    f"max_linear={target_max_linear:.3f}m/s, "
                    f"max_angular={target_max_angular:.3f}rad/s, "
                    "topic=/perception/visual_event, "
                    "target_key=vision_epoch+target_id, "
                    f"bbox_demo={self.get_parameter('target_approach_allow_bbox_distance_fallback').value}"
                )
            elif bool(self.get_parameter("target_approach_enabled").value):
                self.get_logger().info(
                    "Target approach adapter inactive; enable the selected "
                    "chassis backend"
                )

            # Voice caller approach uses one Vision/SLAM result and one Nav2
            # goal.  The old visual velocity adapter remains unrouted.
            self._person_nav_approach_adapter = None
            if self._twist_publisher is not None and VisionTask is not None:
                self._person_nav_approach_adapter = PersonNavApproachAdapter(
                    Ros2PersonApproachTransport(
                        self,
                        nav_action=str(self.get_parameter("navigation_action_name").value),
                    ),
                    self._twist_publisher,
                    should_stop=lambda: self._interrupt.cancel_requested,
                    chassis_backend=self._chassis_backend,
                )
                controller_adapters["person_nav_approach"] = (
                    self._person_nav_approach_adapter
                )
            else:
                self.get_logger().warning(
                    "Voice caller Nav2 approach unavailable: chassis or VisionTask missing"
                )

            # ── Generic selected visual-target approach ────────────────
            visual_target_config = self._config.visual_target_approach_config
            object_stream_config = visual_target_config.get(
                "object_detection_stream", {}
            )
            self._vision_object_callback_group = ReentrantCallbackGroup()
            self._vision_object_client = _VisionObjectDetectionLeaseClient(
                self,
                service_name=str(
                    object_stream_config.get(
                        "service_name", "/perception/vision/task"
                    )
                ),
                timeout_sec=float(
                    object_stream_config.get("service_timeout_sec", 1.0)
                ),
                confidence=float(
                    object_stream_config.get("confidence", 0.5)
                ),
                callback_group=self._vision_object_callback_group,
            )
            self._visual_target_approach_adapter: (
                VisualTargetApproachAdapter | None
            ) = None
            visual_behavior_policies = dict(
                visual_target_config["behavior_policies"]
            )
            if chassis_type == "go2":
                visual_behavior_policies.update(
                    visual_target_config.get(
                        "go2_owner_approach_policies", {}
                    )
                )
            elif chassis_type == "lite3":
                visual_behavior_policies.update(
                    visual_target_config.get(
                        "lite3_owner_approach_policies", {}
                    )
                )
            if (
                bool(visual_target_config.get("enabled", True))
                and self._twist_publisher is not None
            ):
                visual_target_max_linear = min(
                    chassis_max_linear,
                    float(visual_target_config["max_linear_x"]),
                )
                visual_target_max_angular = min(
                    chassis_max_angular,
                    float(visual_target_config["max_angular_z"]),
                )
                self._visual_target_approach_adapter = (
                    VisualTargetApproachAdapter(
                        publish_twist=self._twist_publisher,
                        behavior_policies=visual_behavior_policies,
                        publish_rate_hz=float(
                            visual_target_config["publish_rate_hz"]
                        ),
                        min_confidence=float(
                            visual_target_config["min_confidence"]
                        ),
                        visual_timeout_sec=float(
                            visual_target_config["visual_timeout_sec"]
                        ),
                        acquire_timeout_sec=float(
                            visual_target_config["acquire_timeout_sec"]
                        ),
                        lost_timeout_sec=float(
                            visual_target_config["lost_timeout_sec"]
                        ),
                        approach_timeout_sec=float(
                            visual_target_config["approach_timeout_sec"]
                        ),
                        minimum_stop_distance_m=float(
                            visual_target_config[
                                "minimum_stop_distance_m"
                            ]
                        ),
                        minimum_safe_distance_m=float(
                            visual_target_config[
                                "minimum_safe_distance_m"
                            ]
                        ),
                        distance_deadband_m=float(
                            visual_target_config["distance_deadband_m"]
                        ),
                        distance_hysteresis_m=float(
                            visual_target_config["distance_hysteresis_m"]
                        ),
                        arrival_hold_sec=float(
                            visual_target_config["arrival_hold_sec"]
                        ),
                        linear_gain=float(
                            visual_target_config["linear_gain"]
                        ),
                        angular_gain=float(
                            visual_target_config["angular_gain"]
                        ),
                        max_linear_x=visual_target_max_linear,
                        max_angular_z=visual_target_max_angular,
                        max_linear_accel=float(
                            visual_target_config["max_linear_accel"]
                        ),
                        max_angular_accel=float(
                            visual_target_config["max_angular_accel"]
                        ),
                        heading_deadband=float(
                            visual_target_config["heading_deadband"]
                        ),
                        max_heading_error=float(
                            visual_target_config["max_heading_error"]
                        ),
                        allow_bbox_distance_fallback=bool(
                            visual_target_config[
                                "allow_bbox_distance_fallback"
                            ]
                        ),
                        bbox_target_height=float(
                            visual_target_config["bbox_target_height"]
                        ),
                        bbox_height_deadband=float(
                            visual_target_config["bbox_height_deadband"]
                        ),
                        bbox_height_hysteresis=float(
                            visual_target_config["bbox_height_hysteresis"]
                        ),
                        reacquire_min_consecutive_frames=int(
                            visual_target_config[
                                "reacquire_min_consecutive_frames"
                            ]
                        ),
                        stop_publish_count=chassis_stop_count,
                        should_stop=lambda: self._interrupt.cancel_requested,
                        require_object_stream=bool(
                            object_stream_config.get("required", True)
                        ),
                        start_object_detection=(
                            self._vision_object_client.start
                            if self._vision_object_client.available
                            else None
                        ),
                        stop_object_detection=(
                            self._vision_object_client.stop
                            if self._vision_object_client.available
                            else None
                        ),
                        object_detection_rate_hz=float(
                            object_stream_config.get("rate_hz", 4.0)
                        ),
                        object_detection_lease_margin_sec=float(
                            object_stream_config.get(
                                "lease_margin_sec", 2.0
                            )
                        ),
                    )
                )
                controller_adapters["visual_target_approach"] = (
                    self._visual_target_approach_adapter
                )
                self.get_logger().info(
                    "Visual target approach enabled: "
                    f"behaviors={len(visual_behavior_policies)}, "
                    f"max_linear={visual_target_max_linear:.3f}m/s, "
                    "human_range_mode=bbox_height, "
                    "nonhuman_range_mode=metric, "
                    "object_stream=session_v2"
                )
            elif bool(visual_target_config.get("enabled", True)):
                self.get_logger().info(
                    "Visual target approach inactive; enable the selected "
                    "chassis backend"
                )

            self._stage_executor = StageExecutor(
                eligibility_checker=self._eligibility,
                posture_manager=self._posture,
                interrupt_manager=self._interrupt,
                action_catalog=self._config.action_catalog,
                controller_routes=self._controller_routes,
                controller_adapters=controller_adapters,
            )
            self._result_evaluator = ResultEvaluator()
            self._behavior_execution_lock = threading.Lock()
            self._current_priority: int = 99  # lower = more urgent
            self._goal_reservation_lock = threading.Lock()
            self._reserved_goal_id: str | None = None
            self._long_goal_id: str | None = None
            self._lease_lock = threading.Lock()
            self._lease_seen: dict[tuple[str, str], float] = {}
            self.declare_parameter("long_goal_lease_timeout_sec", 2.0)
            self.declare_parameter("long_goal_lease_grace_sec", 3.0)
            from std_msgs.msg import String
            self.create_subscription(
                String, "/behavior/goal_lease", self._on_goal_lease, 10,
            )

            # ── Background session attention tracking ────────────────
            self._behavior_sounds = BehaviorSoundController(
                self._config.sound_config,
                self._config.config_dir,
            )

            self.declare_parameter("attention_tracking_enabled", True)
            self.declare_parameter("attention_tracking_gain", 0.8)
            self.declare_parameter("attention_tracking_deadband", 0.08)
            self.declare_parameter("attention_tracking_activation_deadband", 0.14)
            self.declare_parameter("attention_tracking_smoothing_alpha", 0.15)
            self.declare_parameter("attention_tracking_max_angular_z", 0.25)
            self.declare_parameter("attention_tracking_max_angular_accel", 0.25)
            self.declare_parameter("attention_tracking_visual_timeout_sec", 0.8)
            self.declare_parameter("attention_tracking_direction_sign", -1.0)
            self.declare_parameter("follow_target_height", 0.68)
            self.declare_parameter("follow_height_deadband", 0.05)
            self.declare_parameter("follow_activation_deadband", 0.10)
            self.declare_parameter("follow_linear_gain", 1.0)
            self.declare_parameter("follow_max_linear_x", 0.25)
            self.declare_parameter("follow_max_linear_accel", 0.50)
            self.declare_parameter("follow_max_heading_error", 0.30)
            self._attention_controller: AttentionTrackingController | None = None
            if (
                bool(self.get_parameter("attention_tracking_enabled").value)
                and self._twist_publisher is not None
            ):
                self._attention_controller = AttentionTrackingController(
                    gain=float(self.get_parameter("attention_tracking_gain").value),
                    deadband=float(
                        self.get_parameter("attention_tracking_deadband").value
                    ),
                    activation_deadband=float(
                        self.get_parameter(
                            "attention_tracking_activation_deadband"
                        ).value
                    ),
                    smoothing_alpha=float(
                        self.get_parameter(
                            "attention_tracking_smoothing_alpha"
                        ).value
                    ),
                    max_angular_z=float(
                        self.get_parameter(
                            "attention_tracking_max_angular_z"
                        ).value
                    ),
                    max_angular_accel=float(
                        self.get_parameter(
                            "attention_tracking_max_angular_accel"
                        ).value
                    ),
                    visual_timeout_sec=float(
                        self.get_parameter(
                            "attention_tracking_visual_timeout_sec"
                        ).value
                    ),
                    wake_angle_zero_offset_deg=float(
                        self.get_parameter(
                            "wake_angle_zero_offset_deg"
                        ).value
                    ),
                    wake_angle_direction_sign=float(
                        self.get_parameter(
                            "wake_angle_direction_sign"
                        ).value
                    ),
                    wake_angle_deadband_deg=float(
                        self.get_parameter(
                            "wake_angle_deadband_deg"
                        ).value
                    ),
                    direction_sign=float(
                        self.get_parameter(
                            "attention_tracking_direction_sign"
                        ).value
                    ),
                    follow_target_height=float(
                        self.get_parameter("follow_target_height").value
                    ),
                    follow_height_deadband=float(
                        self.get_parameter("follow_height_deadband").value
                    ),
                    follow_activation_deadband=float(
                        self.get_parameter("follow_activation_deadband").value
                    ),
                    follow_linear_gain=float(
                        self.get_parameter("follow_linear_gain").value
                    ),
                    follow_max_linear_x=float(
                        self.get_parameter("follow_max_linear_x").value
                    ),
                    follow_max_linear_accel=float(
                        self.get_parameter("follow_max_linear_accel").value
                    ),
                    follow_max_heading_error=float(
                        self.get_parameter("follow_max_heading_error").value
                    ),
                )
                self.get_logger().info(
                    "Session attention tracking ready: "
                    "/behavior/attention_tracking + /perception/visual_event"
                )
            if (
                self._attention_controller is not None
                or self._uwb_follow_adapter is not None
                or self._target_approach_adapter is not None
                or self._person_nav_approach_adapter is not None
                or self._visual_target_approach_adapter is not None
                or self._wake_orientation_adapter is not None
            ):
                self._setup_attention_tracking_io()

            # ── Exact behavior-tree contract ─────────────────────────────
            self._acceptable_behaviors = self._config.get_behavior_names()
            self.get_logger().info(
                f"Accepted behavior-tree names: "
                f"{len(self._acceptable_behaviors)}"
            )

            # ── Debug publishers ────────────────────────────────────────
            self._debug = DebugPublishers(self, enable_legacy=False)

            # ── Action Server ───────────────────────────────────────────
            self._action_callback_group = ReentrantCallbackGroup()
            action_source = get_action_source()
            if _ExecuteBehavior is None:
                self.get_logger().error(
                    "ExecuteBehavior action message not found. "
                    "Ensure marsdog_interfaces is installed and built. "
                    "Action Server will NOT start."
                )
            else:
                self._action_server = ActionServer(
                    self,
                    _ExecuteBehavior,
                    "/execute_behavior",
                    execute_callback=self._on_execute,
                    goal_callback=self._on_goal,
                    cancel_callback=self._on_cancel,
                    handle_accepted_callback=self._on_accepted,
                    callback_group=self._action_callback_group,
                )
                self.get_logger().info(
                    f"Action Server /execute_behavior started "
                    f"(action from {action_source})."
                )

            self.get_logger().info(
                "ActionExecutorNode (v2) started — sole /execute_behavior server. "
                "Ensure no other marsdog_action_executor instance is running."
            )

        # ── Config path resolution ─────────────────────────────────────

        @staticmethod
        def _resolve_config_dir() -> Path:
            """Find the config directory: ROS2 share dir → local fallback."""
            try:
                from ament_index_python.packages import get_package_share_directory
                share = Path(get_package_share_directory("marsdog_action_executor"))
                cfg = share / "config"
                if cfg.exists():
                    return cfg
            except Exception:
                pass
            # Fallback: local source tree
            local = Path(__file__).resolve().parent.parent / "config"
            if local.exists():
                return local
            if not Path("config").exists() and installed_config_dir().is_dir():
                return installed_config_dir()
            return Path("config")

        # ── Action Server callbacks ─────────────────────────────────────

        def _on_goal(self, goal_request) -> GoalResponse:
            decision = goal_lifecycle.on_goal(self, goal_request, goal_response=GoalResponse)
            emit("action.goal.responded", {**goal_fields(goal_request),
                 "accepted": decision == GoalResponse.ACCEPT}, kind="lifecycle")
            return decision

        def _on_goal_lease(self, message) -> None:
            return goal_lifecycle.on_goal_lease(self, message)

        def _on_uwb_follow_diagnostics(self, message) -> None:
            adapter = self._uwb_follow_adapter
            if not isinstance(adapter, UwbFollowAdapter):
                return
            for status in message.status:
                if "UWB follow controller" in status.name:
                    adapter.update_controller_state(status.message)

        def _lease_expired(self, gid: str, bid: str, started: float) -> bool:
            return goal_lifecycle.lease_expired(self, gid, bid, started)

        def _setup_attention_tracking_io(self) -> None:
            from std_msgs.msg import String
            from rclpy.qos import (
                HistoryPolicy,
                QoSProfile,
                ReliabilityPolicy,
            )

            reliable = QoSProfile(
                reliability=ReliabilityPolicy.RELIABLE,
                history=HistoryPolicy.KEEP_LAST,
                depth=10,
            )
            visual_qos = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST,
                depth=5,
            )
            self.create_subscription(
                String,
                "/behavior/attention_tracking",
                self._on_attention_control,
                reliable,
            )
            self.create_subscription(
                String,
                "/perception/visual_event",
                self._on_visual_event,
                visual_qos,
            )
            object_stream_config = (
                self._config.visual_target_approach_config.get(
                    "object_detection_stream", {}
                )
            )
            self.create_subscription(
                String,
                str(
                    object_stream_config.get(
                        "topic", "/perception/vision/object_detections"
                    )
                ),
                self._on_object_detection,
                visual_qos,
                callback_group=self._vision_object_callback_group,
            )
            self.create_timer(0.1, self._tick_attention_tracking)

        def _on_attention_control(self, message) -> None:
            try:
                payload = json.loads(message.data)
            except (json.JSONDecodeError, TypeError):
                self.get_logger().warning("Invalid attention control JSON")
                return
            if not isinstance(payload, dict):
                self.get_logger().warning("Invalid attention control JSON object")
                return
            if self._attention_controller is not None:
                self._attention_controller.update_control(payload)
            # /behavior/attention_tracking belongs to the voice session.
            # UWB follow is owned only by its ExecuteBehavior Goal.
            if (
                (
                    self._attention_controller is None
                    or not self._attention_controller.enabled
                )
                and self._twist_publisher is not None
            ):
                if self._behavior_execution_lock.acquire(blocking=False):
                    try:
                        self._twist_publisher(TwistCommand())
                    finally:
                        self._behavior_execution_lock.release()

        def _on_visual_event(self, message) -> None:
            if not _dispatch_visual_event(
                message.data,
                attention_controller=self._attention_controller,
                target_approach_adapter=self._target_approach_adapter,
                visual_target_approach_adapter=(
                    self._visual_target_approach_adapter
                ),
                wake_orientation_adapter=self._wake_orientation_adapter,
                person_nav_approach_adapter=self._person_nav_approach_adapter,
            ):
                self.get_logger().warning(
                    "Invalid visual event JSON; target approach stopped"
                )

        def _on_object_detection(self, message) -> None:
            if not _dispatch_object_detection(
                message.data,
                visual_target_approach_adapter=(
                    self._visual_target_approach_adapter
                ),
            ):
                # Foreign sessions and idle packets are expected and are not
                # warnings. Malformed packets are still safely ignored because
                # they cannot update the active movement observation.
                return

        # Retain the private hook for older local tests/integration harnesses.
        def _on_attention_visual(self, message) -> None:
            self._on_visual_event(message)

        def _tick_attention_tracking(self) -> None:
            if (
                self._attention_controller is None
                or self._twist_publisher is None
            ):
                return
            if getattr(getattr(self, "_uwb_roam_adapter", None), "active", False):
                return
            # Hold the same ownership mutex used by foreground behaviors across
            # both command calculation and publication.  This closes the
            # check-then-publish race where an old attention command could land
            # after a target-approach behavior had already acquired /cmd_vel.
            if not self._behavior_execution_lock.acquire(blocking=False):
                return
            try:
                command = self._attention_controller.command(suspended=False)
                if command is not None:
                    self._twist_publisher(command)
            finally:
                self._behavior_execution_lock.release()

        def _on_cancel(self, goal_handle) -> CancelResponse:
            decision = goal_lifecycle.on_cancel(self, goal_handle, cancel_response=CancelResponse)
            emit("action.cancel.responded", {"goal_id": goal_handle.request.goal_id,
                                            "accepted": decision == CancelResponse.ACCEPT})
            return decision

        def _on_accepted(self, goal_handle) -> None:
            return goal_lifecycle.on_accepted(self, goal_handle)

        async def _on_execute(self, goal_handle):
            with bind_context(**goal_fields(goal_handle.request)):
                started = time.monotonic()
                emit("action.execution.started", goal_fields(goal_handle.request), kind="lifecycle")
                try:
                    result = await goal_execution.on_execute(self, goal_handle, make_result=_make_result)
                except Exception:
                    get_logger(__name__).exception("Action execution callback raised",
                        extra={"marsdog_event": "action.execution.crashed", "marsdog_kind": "lifecycle"})
                    raise
                # Includes early validation/busy returns that have no debug-result publication.
                emit("action.execution.completed", {key: getattr(result, key, None) for key in
                     ("goal_id", "behavior_id", "behavior_name", "status", "result", "reason")},
                     duration_ms=round((time.monotonic() - started) * 1000, 3), kind="lifecycle",
                     level=logging.INFO if getattr(result, "status", "") == "SUCCESS" else logging.WARNING)
                return result

        async def _execute_behavior(self, goal_handle):
            return await goal_execution.execute_behavior(self, goal_handle, make_result=_make_result)

        def _execute_long_behavior(
            self, goal_handle, ctx: ExecutionContext, stages: list[dict],
            started_wall: float,
        ):
            return goal_execution.execute_long_behavior(self, goal_handle, ctx, stages, started_wall, make_result=_make_result)

        def _execute_emergency_stop(self, goal_handle):
            return goal_execution.execute_emergency_stop(self, goal_handle, make_result=_make_result)

        # ── Helpers ────────────────────────────────────────────────────

        def _read_battery_level(self) -> None:
            """No verified telemetry source is connected; never synthesize SOC.

            recharge_result_energy_value remains declared for launch compatibility
            but is not a measurement and is deliberately not consumed here.
            """
            return None

        def _publish_feedback(
            self, goal_handle, gid: str, behavior_id: str,
            behavior_name: str, progress: float, stage: str,
            action: str, safe: bool, message: str,
        ) -> None:
            result = action_messages.publish_feedback(self, goal_handle, gid, behavior_id, behavior_name, progress, stage, action, safe, message, action_type=_ExecuteBehavior)
            emit("action.stage.feedback", {"goal_id": gid, "behavior_id": behavior_id,
                 "behavior_name": behavior_name, "progress": progress, "stage": stage,
                 "action_id": action, "safe_to_interrupt": safe, "message": message}, repeat_key=gid)
            return result


# ═══════════════════════════════════════════════════════════════════════════════
# Result helper
# ═══════════════════════════════════════════════════════════════════════════════

def _make_result(
    goal_id: str,
    behavior_id: str,
    behavior_name: str,
    resolved_name: str = "",
    status: str = "SUCCESS",
    result: str = "completed",
    reason: str = "",
    reward: float = 1.0,
    metadata: dict | None = None,
) -> object:
    return action_messages.make_result(goal_id, behavior_id, behavior_name, resolved_name, status, result, reason, reward, metadata, action_type=_ExecuteBehavior)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main(args: list[str] | None = None) -> None:
    """Entry point for the ROS2 node.

    Before running, source ROS2 and the colcon workspace::

        source /opt/ros/humble/setup.bash
        source ~/ros2_ws/install/setup.bash
        ros2 run marsdog_action_executor action_executor_node
    """
    if not HAS_ROS2:
        print(
            "ROS2 (rclpy) is not available. "
            "Make sure you've sourced ROS2 setup.bash, "
            "then run again with:\n"
            "  ros2 run marsdog_action_executor action_executor_node\n"
            "\n"
            "For a no-ROS2 demo, use:\n"
            "  uv run python -m marsdog_action_executor.standalone_demo"
        )
        sys.exit(1)

    import signal
    from rclpy.signals import SignalHandlerOptions
    # Cancellation and zero-velocity publication must finish before the ROS
    # context closes. An ok() check cannot prevent asynchronous signal shutdown.
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt
    previous_term = signal.signal(signal.SIGTERM, interrupt)
    node = ActionExecutorNode()
    # Long Goal workers and synchronous service waits need spare ROS callback
    # threads for inner Action results, service replies and lease renewals.
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node._behavior_sounds.stop()
        # Let the Action worker drain an accepted inner cancellation while
        # ROS callbacks can still deliver its real Result. A hard process kill
        # skips this path; the external supervisor must stop the chassis then.
        node._interrupt.request_cancel()
        roam = getattr(node, "_uwb_roam_adapter", None)
        if roam is not None:
            roam.cancel_step()
        if node._uwb_follow_adapter is not None:
            node._uwb_follow_adapter.request_cancel()
        deadline = time.monotonic() + 7.0
        while (rclpy.ok() and node._behavior_execution_lock.locked()
               and time.monotonic() < deadline):
            executor.spin_once(timeout_sec=0.1)
        if roam is not None:
            roam.close()
        if node._uwb_follow_adapter is not None and rclpy.ok():
            node._uwb_follow_adapter.emergency_stop()
        if rclpy.ok():
            node._stationary_expression_adapter.emergency_stop()
        if node._mobility_adapter is not None and rclpy.ok():
            node._mobility_adapter.emergency_stop()
        if node._wake_orientation_adapter is not None and rclpy.ok():
            node._wake_orientation_adapter.emergency_stop()
        if node._target_approach_adapter is not None and rclpy.ok():
            node._target_approach_adapter.emergency_stop()
        if node._person_nav_approach_adapter is not None and rclpy.ok():
            node._person_nav_approach_adapter.emergency_stop()
        if node._visual_target_approach_adapter is not None and rclpy.ok():
            node._visual_target_approach_adapter.emergency_stop()
        if node._chassis_backend is not None and rclpy.ok():
            node._chassis_backend.emergency_stop()
        executor.shutdown()
        node.destroy_node()
        _shutdown_rclpy_if_ok(rclpy, RCLError)
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    main()
