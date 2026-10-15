"""Select a tag and sequence the existing UWB follow node; no velocity controller."""
import json
import math
import signal
import time
import uuid

import rclpy
from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import PointStamped, TwistStamped
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import ParameterDescriptor
from rcl_interfaces.srv import SetParametersAtomically
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import String
from std_srvs.srv import Trigger
from robot_local_motion.msg import TargetObservation
from .core import Pose
from .guard import ObservationOrder, StampGuard, StopCheck
from .roundtrip_launch import validate_roles


class NativeUwbRoundTrip(Node):
    def __init__(self, **kwargs):
        super().__init__('uwb_roundtrip_demo', **kwargs)
        def param(key, default):
            return self.declare_parameter(key, default, descriptor=ParameterDescriptor(
                dynamic_typing=key in ('owner_id', 'frisbee_id'))).value
        self.owner, self.frisbee = validate_roles(param('owner_id', ''), param('frisbee_id', ''))
        self.enabled = param('enable_motion', False)
        self.autostart = param('autostart', False)
        self.source = param('target_source', 'uwb_multitag')
        self.distances = {'APPROACH_FRISBEE': param('frisbee_distance_m', .8),
                          'RETURN_OWNER': param('owner_distance_m', 1.)}
        self.dwell_sec = param('dwell_sec', 3.)
        self.target_age = param('target_max_age_sec', .5)
        self.odom_age = param('odom_timeout_sec', .1)
        self.odom_frame = param('odom_frame', 'odom')
        self.odom_child = param('odom_child_frame', 'base_link')
        self.settle_timeout = param('cancel_settle_timeout_sec', 8.)
        if any(not math.isfinite(v) or v <= 0 for v in (
                self.dwell_sec, self.target_age, self.odom_age, self.settle_timeout, *self.distances.values())):
            raise ValueError('invalid native roundtrip timing/distance')
        self.phase = 'IDLE'
        self.leg = 'APPROACH_FRISBEE'
        self.role = self.frisbee
        self.outcome = self.message = self.run_id = ''
        self.history = []
        self.targets = {}
        self.order = ObservationOrder()
        self.guard = StampGuard()
        self.pose = None
        self.velocity = (math.inf, math.inf)
        self.odom_at = -math.inf
        self.stop_settings = dict(hold_sec=param('stop_hold_sec', .4),
            linear=param('stop_linear_threshold', .08), angular=param('stop_angular_threshold', .15),
            position=param('stop_position_threshold', .015), yaw=param('stop_yaw_threshold', .04))
        self.stop = StopCheck(**self.stop_settings)
        self.follow_values = {}
        self.follow_at = -math.inf
        self.final = (math.inf, math.inf)
        self.final_at = -math.inf
        self.paused = True
        self.cancel_requested = False
        self.future = None
        self.after_parameters = None
        self.started = self.dwell_started = 0.
        self.stop_confirmed = False
        self.last_status = 0.
        self.client = self.create_client(SetParametersAtomically,
            param('follow_parameter_service', '/uwb_follow_controller_node/set_parameters_atomically'))
        self.selected = self.create_publisher(PointStamped,
            param('selected_target_topic', '/uwb_roundtrip/selected_target'), 10)
        self.status = self.create_publisher(String, param('status_topic', '/uwb_roundtrip/status'), 10)
        self.create_subscription(TargetObservation, param('target_topic', '/robot_local_motion/target'),
            self.on_target, qos_profile_sensor_data)
        self.create_subscription(Odometry, param('odom_topic', '/odom'), self.on_odom, qos_profile_sensor_data)
        self.create_subscription(DiagnosticArray, param('follow_diagnostics_topic', '/uwb_roundtrip/follow_diagnostics'),
            self.on_follow, 10)
        self.create_subscription(TwistStamped, param('final_cmd_topic', '/robot_local_motion/final_cmd'),
            self.on_final, 10)
        self.create_service(Trigger, '~/start', self.start_service)
        self.create_service(Trigger, '~/cancel', self.cancel_service)
        self.timer = self.create_timer(.05, self.tick)
        self.emit()

    def on_odom(self, msg):
        now_ns = self.get_clock().now().nanoseconds
        ns = msg.header.stamp.sec*10**9 + msg.header.stamp.nanosec
        q, p = msg.pose.pose.orientation, msg.pose.pose.position
        values = (p.x, p.y, q.x, q.y, q.z, q.w, msg.twist.twist.linear.x, msg.twist.twist.angular.z)
        if (msg.header.frame_id != self.odom_frame or msg.child_frame_id != self.odom_child
                or not all(math.isfinite(v) for v in values)
                or not self.guard.accept('odom', ns, now_ns, self.odom_age)):
            self.odom_at = -math.inf
            return
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        self.pose = Pose(p.x, p.y, yaw)
        self.velocity = msg.twist.twist.linear.x, msg.twist.twist.angular.z
        self.odom_at = time.monotonic()-(now_ns-ns)/1e9

    def on_target(self, msg):
        if msg.source != self.source or msg.target_id not in (self.owner, self.frisbee):
            return
        ns = msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        if not self.order.accept(msg.target_id, msg.sequence, ns, self.get_clock().now().nanoseconds, msg.valid):
            return
        self.targets[msg.target_id] = msg
        if self.phase == self.leg and not self.paused and msg.target_id == self.role:
            self.forward(msg)

    def fresh_target(self):
        msg = self.targets.get(self.role)
        if msg is None or not msg.valid or not msg.header.frame_id:
            return None
        ns = msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        age = (self.get_clock().now().nanoseconds-ns)/1e9
        return msg if 0 <= age <= self.target_age else None

    def forward(self, msg):
        if self.fresh_target() is not msg:
            return
        point = PointStamped()
        point.header, point.point = msg.header, msg.position
        self.selected.publish(point)  # Preserve the original observation stamp and frame.

    def on_follow(self, msg):
        if msg.status:
            self.follow_values = {v.key: v.value for v in msg.status[0].values}
            self.follow_values['state'] = msg.status[0].message
            self.follow_at = time.monotonic()

    def on_final(self, msg):
        ns = msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
        age = (self.get_clock().now().nanoseconds-ns)/1e9
        self.final = msg.twist.linear.x, msg.twist.angular.z
        self.final_at = time.monotonic()-age if 0 <= age <= .2 else -math.inf

    def stationary(self, now):
        return (self.pose is not None and self.stop.update(now, self.pose, *self.velocity,
            0 <= now-self.odom_at <= self.odom_age))

    def zero_output(self, now):
        return now-self.final_at <= .2 and all(abs(v) <= 1e-6 for v in self.final)

    def configure(self, enabled, next_phase):
        if self.future is not None or not self.client.service_is_ready():
            return False
        request = SetParametersAtomically.Request(parameters=[
            Parameter('tracking_enabled', value=enabled).to_parameter_msg(),
            Parameter('follow_distance', value=float(self.distances[self.leg])).to_parameter_msg()])
        self.future = self.client.call_async(request)
        self.after_parameters = next_phase, not enabled
        self.follow_values = {}
        self.phase = 'CONFIGURING' if enabled else 'STOPPING'
        return True

    def start_roundtrip(self):
        now = time.monotonic()
        if not self.enabled:
            return False, 'motion disabled'
        if self.phase not in ('IDLE', 'DONE', 'CANCELED') or self.future is not None:
            return False, 'roundtrip already active or controller state unresolved'
        if not self.stationary(now) or not self.zero_output(now) or not self.client.service_is_ready():
            return False, 'waiting for original controller and stationary odometry'
        self.leg, self.role = 'APPROACH_FRISBEE', self.frisbee
        self.run_id, self.history = str(uuid.uuid4()), []
        self.outcome = self.message = ''
        self.started = now
        self.cancel_requested = self.stop_confirmed = False
        self.configure(True, self.leg)
        return True, self.run_id

    def start_service(self, request, response):
        response.success, response.message = self.start_roundtrip()
        return response

    def request_cancel(self):
        self.cancel_requested = True
        if self.future is None:
            self.configure(False, 'CANCELING')

    def cancel_service(self, request, response):
        if self.phase in ('IDLE', 'DONE', 'CANCELED'):
            response.success, response.message = False, 'no active roundtrip'
        else:
            self.request_cancel()
            response.success, response.message = True, 'cancel requested; wait for physical stop'
        return response

    def tick(self):
        now = time.monotonic()
        stationary = self.stationary(now)
        stopped = stationary and self.zero_output(now)
        if self.future is not None and self.future.done():
            future, self.future = self.future, None
            try:
                response = future.result().result
                if not response.successful:
                    raise RuntimeError(response.reason)
                self.phase, self.paused = self.after_parameters
                self.stop = StopCheck(**self.stop_settings)
                stopped = False
                if self.cancel_requested and not self.paused:
                    self.configure(False, 'CANCELING')
                elif not self.paused:
                    msg = self.fresh_target()
                    if msg is not None:
                        self.forward(msg)
            except Exception as exc:
                self.phase, self.outcome, self.message = 'RECOVERY_REQUIRED', 'CONFIG_ERROR', str(exc)
        if self.cancel_requested and self.future is None and self.phase not in ('CANCELING', 'CANCELED'):
            self.configure(False, 'CANCELING')
        elif self.phase == 'IDLE' and self.autostart and self.enabled and stopped:
            self.start_roundtrip()
        elif self.phase == self.leg and not self.paused:
            within = (now-self.follow_at <= .75 and self.fresh_target() is not None
                and self.follow_values.get('within_follow_distance') == 'true'
                and self.follow_values.get('tracking_enabled') == 'true'
                and self.follow_values.get('follow_distance') == f'{self.distances[self.leg]:.3f}')
            # Distance + the existing physical stop check finish a follow leg.
            # MPPI can retain a tiny angular command while aligning; pause the
            # follower before waiting for its output to become exactly zero.
            if within and stationary:
                self.configure(False, 'ARRIVED')
        elif self.phase == 'ARRIVED' and self.paused and stopped:
            self.history.append({'stage': self.leg, 'mode': 'original_uwb_follow',
                'target_id': self.role, 'outcome': 'SUCCEEDED', 'stop_confirmed': True,
                'at_monotonic': now})
            self.stop_confirmed = True
            if self.leg == 'APPROACH_FRISBEE':
                self.phase, self.dwell_started = 'DWELL', now
            else:
                self.phase, self.outcome = 'DONE', 'SUCCEEDED'
        elif self.phase == 'DWELL':
            if not stopped:
                self.dwell_started = now
            elif now-self.dwell_started >= self.dwell_sec:
                self.leg, self.role = 'RETURN_OWNER', self.owner
                self.stop_confirmed = False
                self.configure(True, self.leg)
        elif self.phase == 'CANCELING' and self.paused and stopped:
            self.phase, self.outcome, self.stop_confirmed = 'CANCELED', 'CANCELED', True
            self.cancel_requested = False
        if now-self.last_status >= .5:
            self.emit()

    def emit(self):
        self.last_status = time.monotonic()
        try:
            distance = float(self.follow_values.get('distance', 'n/a'))
        except (ValueError, TypeError):
            distance = None
        data = dict(run_id=self.run_id, state=self.phase, outcome=self.outcome, message=self.message,
            stop_confirmed=self.stop_confirmed, owner_id=self.owner, frisbee_id=self.frisbee,
            dwell_sec=self.dwell_sec, history=self.history, approach_timeout_sec=0.,
            child_feedback=dict(state=self.follow_values.get('state', ''),
                distance_m=distance, elapsed_sec=time.monotonic()-self.started if self.started else 0.),
            backend='uwb_follow_controller_node', movement_only=True, pickup_confirmed=False)
        self.status.publish(String(data=json.dumps(data)))


def main():
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = NativeUwbRoundTrip()
    shutdown_at = None
    def cancel(signum, frame):
        nonlocal shutdown_at
        shutdown_at = shutdown_at or time.monotonic()
        node.request_cancel()
    signal.signal(signal.SIGINT, cancel)
    signal.signal(signal.SIGTERM, cancel)
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=.05)
            if shutdown_at is not None and (node.phase == 'CANCELED' or
                    time.monotonic()-shutdown_at >= node.settle_timeout):
                node.emit()
                break
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
