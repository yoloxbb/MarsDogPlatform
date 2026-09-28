"""Explicit local development I/O; never publishes Lite3 hardware commands.

This simulates acknowledgements/status only, not dynamics, safety or hardware.
The existing Lite3 backend still owns command plans and preflight checks.
"""
import os
from dataclasses import asdict

from .lite3_backend import (
    CMD_STAND_LIE_TOGGLE, STATE_LIE, STATE_STAND,
    Lite3ChassisBackend, Lite3RobotStatus,
)


class SimulatedLite3IO:
    def __init__(self, emit=lambda _event: None):
        self.emit = emit
        self.backend = None
        self.posture = STATE_STAND

    def status_tick(self):
        if self.backend is not None:
            # Internal mock feedback only. Never converted to a battery observation.
            self.backend.update_status(Lite3RobotStatus(
                self.posture, 0, 0, 75.0, 2.0, 2.0))

    def command(self, command):
        if command.cmd_code == CMD_STAND_LIE_TOGGLE:
            self.posture = STATE_LIE if self.posture == STATE_STAND else STATE_STAND
        self.emit({"simulated": True, "kind": "simple_command", **asdict(command)})
        self.status_tick()
        return True

    def twist(self, command):
        self.emit({"simulated": True, "kind": "twist", **asdict(command)})
        self.status_tick()


def require_local_simulation():
    if (os.environ.get("MARSDOG_LOCAL_SIMULATION") != "1"
            or os.environ.get("ROS_LOCALHOST_ONLY") != "1"
            or not 180 <= int(os.environ.get("ROS_DOMAIN_ID", "-1")) <= 219):
        raise RuntimeError("Simulated Lite3 I/O requires the explicit localhost development profile")


def make_simulated_lite3_backend(node, *, simple_cmd_topic, cmd_vel_topic,
                                action_plans, uwb_driving=None, **kwargs):
    require_local_simulation()
    import json
    from std_msgs.msg import String
    publisher = node.create_publisher(String, "/development/lite3_io", 10)
    def emit(event):
        publisher.publish(String(data=json.dumps(event)))
    io = SimulatedLite3IO(emit)
    backend = Lite3ChassisBackend(io.command, io.twist, action_plans, **kwargs)
    io.backend = backend
    io.status_tick()
    node._simulated_lite3_io = io
    node._simulated_lite3_timer = node.create_timer(0.025, io.status_tick)
    node.get_logger().warning(
        "SIMULATED Lite3 I/O: no hardware command publishers; status is synthetic")
    return backend, io.command, io.twist
