"""ROS adapter for the opt-in, movement-only UWB round-trip demo."""
import json
import math
import signal
import time
import uuid

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from rcl_interfaces.msg import ParameterDescriptor
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener, TransformException
from robot_local_motion.action import ExecuteLocalMotion
from robot_local_motion.msg import TargetObservation
from .core import Pose, Target
from .guard import ObservationOrder, StampGuard, StopCheck
from .roundtrip_core import RoundTrip, RoundTripConfig
from .server import stamp_ns, yaw_of, transform_point


class UwbRoundTripDemo(Node):
    def __init__(self, **kwargs):
        super().__init__('uwb_roundtrip_demo', **kwargs)
        def param(key, default):
            return self.declare_parameter(key, default,
                descriptor=ParameterDescriptor(dynamic_typing=key in ('owner_id', 'frisbee_id'))).value
        self.enabled = param('enable_motion', False)
        self.autostart = param('autostart', False)
        self.machine = RoundTrip(RoundTripConfig(param('owner_id', ''), param('frisbee_id', ''),
            dwell_sec=param('dwell_sec', 3.0), approach_timeout_sec=param('approach_timeout_sec', 0.0),
            acquire_timeout_sec=param('acquire_timeout_sec', 20.0)))
        self.source = param('target_source', 'uwb_multitag')
        self.base = param('base_frame', 'base_footprint')
        self.odom_frame = param('odom_frame', 'odom')
        self.odom_child = param('odom_child_frame', self.base)
        self.odom_age = param('odom_timeout_sec', 0.1)
        self.target_age = param('target_max_age_sec', 0.5)
        self.maximum_range = param('max_goal_distance', 10.0)
        self.speed = param('max_linear_speed', 1.0)
        self.angular_speed = param('max_angular_speed', 1.2)
        self.distances = {'APPROACH_FRISBEE': param('frisbee_distance_m', 0.5),
                          'RETURN_OWNER': param('owner_distance_m', 1.0)}
        self.settle_timeout = param('cancel_settle_timeout_sec', 8.0)
        self.server_wait_timeout = param('server_wait_timeout_sec', 10.0)
        self.feedback_timeout = param('motion_feedback_timeout_sec', 10.0)
        if (not self.source or not self.base or not self.odom_frame or not self.odom_child or
                any(not math.isfinite(v) or v <= 0 for v in (
                    self.odom_age, self.target_age, self.maximum_range, self.speed,
                    self.angular_speed, self.settle_timeout, self.server_wait_timeout, self.feedback_timeout, *self.distances.values()))):
            raise ValueError('invalid round-trip deployment configuration')
        self.tf = Buffer()
        self.tf_listener = TransformListener(self.tf, self)
        self.pose = None
        self.velocity = (math.inf, math.inf)
        self.odom_at = -math.inf
        self.stamp_guard = StampGuard()
        self.order = ObservationOrder()
        self.targets = {}
        self.pending_targets = {}
        self.owner_samples = 0
        self.owner_last_at = -math.inf
        self.stop = StopCheck(hold_sec=param('stop_hold_sec', 0.4),
            linear=param('stop_linear_threshold', 0.08), angular=param('stop_angular_threshold', 0.15),
            position=param('stop_position_threshold', 0.015), yaw=param('stop_yaw_threshold', 0.04))
        self.create_subscription(Odometry, param('odom_topic', '/odom'), self.on_odom, qos_profile_sensor_data)
        self.create_subscription(TargetObservation, param('target_topic', '/robot_local_motion/target'),
                                 self.on_target, qos_profile_sensor_data)
        self.client = ActionClient(self, ExecuteLocalMotion,
            param('action_name', '/uwb_roundtrip/local_motion/execute'))
        self.status_pub = self.create_publisher(String, param('status_topic', '/uwb_roundtrip/status'), 10)
        self.create_service(Trigger, '~/start', self.start_service)
        self.create_service(Trigger, '~/cancel', self.cancel_service)
        self.send_future = self.result_future = self.cancel_future = self.goal_handle = None
        self.request_sent_at = self.cancel_at = self.feedback_at = 0.0
        self.last_child_feedback = {}
        self.last_status_at = 0.0
        self.run_id = ''
        self.history = []
        self.last_clock_ns = None
        self.startup_at = time.monotonic()
        self.autostart_attempted = False
        self.timer = self.create_timer(0.05, self.tick)
        self.emit_status()

    def stationary(self, now):
        return self.pose is not None and self.stop.update(now, self.pose, *self.velocity,
            0 <= now-self.odom_at <= self.odom_age)

    def on_odom(self, msg):
        try:
            if msg.header.frame_id != self.odom_frame or msg.child_frame_id != self.odom_child:
                raise ValueError('odometry frame mismatch')
            ns = stamp_ns(msg.header.stamp)
            clock_ns = self.get_clock().now().nanoseconds
            if not self.stamp_guard.accept('odom', ns, clock_ns, self.odom_age):
                raise ValueError('odometry timestamp rejected')
            pose = Pose(msg.pose.pose.position.x, msg.pose.pose.position.y, yaw_of(msg.pose.pose.orientation))
            if self.odom_child != self.base:
                # Lingmao's split-frame relay keeps body and footprint origins
                # coincident in XY and their yaw equal. Verify this relative
                # relationship, then use the original odometry's ground-plane
                # projection, just like the local server/planner. Waiting for a
                # same-stamp odom TF here races the odometry callback itself.
                tf = self.tf.lookup_transform(self.base, self.odom_child, Time()).transform
                if abs(tf.translation.x)>1e-6 or abs(tf.translation.y)>1e-6 or abs(yaw_of(tf.rotation))>1e-6:
                    raise ValueError('split odometry frame must share footprint XY origin and yaw')
            velocity = (msg.twist.twist.linear.x, msg.twist.twist.angular.z)
            if not all(math.isfinite(v) for v in (*pose.__dict__.values(), *velocity)):
                raise ValueError('invalid odometry')
            self.pose, self.velocity = pose, velocity
            self.odom_at = time.monotonic()-max(0.0, (clock_ns-ns)/1e9)
        except Exception:
            self.odom_at = -math.inf

    def on_target(self, msg):
        if msg.source != self.source or msg.target_id not in (
                self.machine.config.owner_id, self.machine.config.frisbee_id):
            return
        ns = stamp_ns(msg.header.stamp)
        clock_ns = self.get_clock().now().nanoseconds
        if not self.order.accept((msg.source, msg.target_id), msg.sequence, ns, clock_ns, msg.valid):
            return
        try:
            if (not msg.valid or not msg.header.frame_id or not 0 <= msg.confidence <= 1 or
                    not all(math.isfinite(v) for v in (msg.position.x, msg.position.y, msg.position.z)) or
                    not 0 <= (clock_ns-ns)/1e9 <= self.target_age):
                raise ValueError('invalid target')
            self.cache_target(msg)
            self.pending_targets.pop(msg.target_id, None)
        except TransformException:
            self.pending_targets[msg.target_id] = msg
        except Exception:
            self.pending_targets.pop(msg.target_id, None)
            self.targets[msg.target_id] = None
            if msg.target_id == self.machine.config.owner_id:
                self.owner_samples = 0

    def cache_target(self, msg):
        x, y = msg.position.x, msg.position.y
        if msg.header.frame_id != self.odom_frame:
            tf = self.tf.lookup_transform(self.odom_frame, msg.header.frame_id, Time.from_msg(msg.header.stamp)).transform
            x, y = transform_point(x, y, msg.position.z, tf)
        age = (self.get_clock().now().nanoseconds-stamp_ns(msg.header.stamp))/1e9
        at = time.monotonic()-max(0.0,age)
        self.targets[msg.target_id] = Target(x,y,at,msg.confidence,msg.sequence)
        if msg.target_id == self.machine.config.owner_id:
            self.owner_samples = self.owner_samples+1 if at-self.owner_last_at <= self.target_age else 1
            self.owner_last_at = at

    def retry_target_transforms(self, clock_ns):
        for identity,msg in list(self.pending_targets.items()):
            if (clock_ns-stamp_ns(msg.header.stamp))/1e9 > min(.2,self.target_age):
                self.pending_targets.pop(identity,None)
                self.targets[identity]=None
                if identity==self.machine.config.owner_id:self.owner_samples=0
                continue
            try:
                self.cache_target(msg)
                self.pending_targets.pop(identity,None)
            except TransformException:
                pass
            except Exception:
                self.pending_targets.pop(identity,None)
                self.targets[identity]=None
                if identity==self.machine.config.owner_id:self.owner_samples=0

    def ready_target(self, identity, now):
        target = self.targets.get(identity)
        return (target is not None and self.pose is not None and 0 <= now-target.received_at <= self.target_age
                and math.hypot(target.x-self.pose.x, target.y-self.pose.y) <= self.maximum_range)

    def start_service(self, _, response):
        response.success, response.message = self.start_roundtrip()
        return response

    def start_roundtrip(self):
        now = time.monotonic()
        if not self.enabled:
            return False, 'enable_motion is false'
        if self.machine.busy or self.send_future is not None or self.goal_handle is not None:
            return False, 'busy or recovery required'
        if not self.client.server_is_ready() or not self.stationary(now):
            return False, 'action server or stationary odometry unavailable'
        if not self.ready_target(self.machine.config.frisbee_id, now):
            return False, 'fresh frisbee target within configured range unavailable'
        self.run_id, self.history = str(uuid.uuid4()), []
        self.send(self.machine.start(now))
        self.emit_status()
        return True, 'round trip accepted: approach frisbee, wait 3 seconds, return to owner'

    def cancel_service(self, _, response):
        if not self.machine.busy:
            response.success, response.message = False, 'no active round trip'
            return response
        self.request_cancel()
        response.success, response.message = True, 'cancel requested; wait for terminal status and stop confirmation'
        return response

    def request_cancel(self):
        self.machine.cancel(self.stationary(time.monotonic()))
        if not self.cancel_at:
            self.cancel_at = time.monotonic()
        if self.goal_handle is not None and self.cancel_future is None:
            self.cancel_future = self.goal_handle.cancel_goal_async()
        self.emit_status()

    def send(self, request):
        goal = ExecuteLocalMotion.Goal()
        goal.mode, goal.target_id, goal.target_source = request.mode, request.target_id, self.source
        parameters = {'timeout_sec': request.timeout_sec, 'max_linear_speed': self.speed,
            'max_angular_speed': self.angular_speed,
            'planner': {'enable_emergency_reverse': request.mode == 'approach'}}
        if request.mode == 'approach':
            parameters.update(desired_distance_m=self.distances[self.machine.state],
                distance_deadband_m=0.20, distance_reengage_m=0.25, arrival_hold_sec=0.4,
                target_max_age_sec=self.target_age, lost_target_policy='pause', lost_target_timeout_sec=3.0,
                lock_target_position=False, face_target_when_holding=True, blocked_policy='wait')
        else:
            goal.goal = PoseStamped()
            goal.goal.header.frame_id = self.base
            goal.goal.pose.orientation.z = math.sin(request.yaw_delta/2)
            goal.goal.pose.orientation.w = math.cos(request.yaw_delta/2)
        goal.parameters_json = json.dumps(parameters)
        self.request_sent_at = self.feedback_at = time.monotonic()
        self.last_child_feedback = {}
        self.cancel_at = 0.0
        self.cancel_future = None
        try:
            self.send_future = self.client.send_goal_async(goal, feedback_callback=self.on_motion_feedback)
        except Exception as exc:
            self.machine.fail('STOP_UNCONFIRMED', 'goal dispatch failed: '+str(exc), False)

    def on_motion_feedback(self, message):
        self.feedback_at = time.monotonic()
        feedback = message.feedback
        self.last_child_feedback = {'state': feedback.state, 'distance_m': feedback.distance_m,
                                    'elapsed_sec': feedback.elapsed_sec}

    def poll_motion(self, now):
        if self.send_future is not None and self.send_future.done():
            future, self.send_future = self.send_future, None
            try:
                self.goal_handle = future.result()
                if not self.goal_handle.accepted:
                    self.goal_handle = None
                    self.machine.motion_done(now, 'CONFIG_ERROR', self.stationary(now), 'child goal rejected')
                else:
                    self.feedback_at = now
                    self.result_future = self.goal_handle.get_result_async()
                    if self.machine.cancel_requested:
                        self.request_cancel()
            except Exception as exc:
                self.machine.fail('STOP_UNCONFIRMED', 'goal acknowledgement unavailable: '+str(exc), False)
        if self.result_future is not None and self.result_future.done():
            future, self.result_future = self.result_future, None
            try:
                wrapped = future.result()
                result = wrapped.result
                valid_status = wrapped.status in (GoalStatus.STATUS_SUCCEEDED, GoalStatus.STATUS_ABORTED, GoalStatus.STATUS_CANCELED)
                coherent = result.outcome != 'SUCCEEDED' or wrapped.status == GoalStatus.STATUS_SUCCEEDED
                stopped = bool(valid_status and coherent and result.stop_confirmed)
                self.history.append({'stage': self.machine.state, 'mode': self.machine.pending.mode,
                    'target_id': self.machine.pending.target_id, 'outcome': result.outcome,
                    'stop_confirmed': stopped, 'at_monotonic': now})
                self.goal_handle = None
                self.machine.motion_done(now, result.outcome, stopped, result.message)
            except Exception as exc:
                self.machine.fail('STOP_UNCONFIRMED', 'child result unavailable: '+str(exc), False)
        if self.machine.pending is not None and self.machine.state != 'RECOVERY_REQUIRED':
            if (self.machine.pending.timeout_sec > 0
                    and now-self.request_sent_at > self.machine.pending.timeout_sec+self.settle_timeout):
                self.request_cancel()
            # Removing the travel deadline must not leave an unknown goal or
            # silent action connection owned indefinitely. Feedback is emitted
            # by the server independently of arrival/no-progress decisions.
            if ((self.send_future is not None and now-self.request_sent_at >= self.server_wait_timeout)
                    or (self.goal_handle is not None and now-self.feedback_at >= self.feedback_timeout)):
                self.request_cancel()
            if self.cancel_at and now-self.cancel_at > self.settle_timeout:
                self.machine.fail('STOP_UNCONFIRMED', 'child cancellation did not settle', False)

    def tick(self):
        now = time.monotonic()
        clock_ns = self.get_clock().now().nanoseconds
        if self.last_clock_ns is not None and clock_ns < self.last_clock_ns:
            self.targets.clear()
            self.pending_targets.clear()
            self.owner_samples = 0
            self.order.stamps.clear()
            self.odom_at = -math.inf
            self.stamp_guard = StampGuard()
            if self.machine.busy:
                self.request_cancel()
        self.last_clock_ns = clock_ns
        self.retry_target_transforms(clock_ns)
        self.poll_motion(now)
        stationary = self.stationary(now)
        owner_ready = self.owner_samples >= 5 and self.ready_target(self.machine.config.owner_id, now)
        request = self.machine.tick(now, stationary, owner_ready)
        if request is not None:
            self.send(request)
        if self.autostart and not self.autostart_attempted:
            accepted, message = self.start_roundtrip()
            if accepted:
                self.autostart_attempted = True
            elif now-self.startup_at >= self.server_wait_timeout:
                self.autostart_attempted = True
                self.machine.fail('INPUT_LOST', 'autostart: '+message, stationary)
        if now-self.last_status_at >= 0.5:
            self.emit_status()

    def emit_status(self):
        now = time.monotonic()
        payload = {'run_id': self.run_id, 'state': self.machine.state, 'outcome': self.machine.outcome,
            'message': self.machine.message, 'stop_confirmed': self.machine.stop_confirmed,
            'owner_id': self.machine.config.owner_id, 'frisbee_id': self.machine.config.frisbee_id,
            'dwell_sec': self.machine.config.dwell_sec, 'history': self.history,
            'approach_timeout_sec': self.machine.config.approach_timeout_sec,
            'child_feedback': self.last_child_feedback,
            'movement_only': True, 'pickup_confirmed': False,
            'elapsed_sec': now-self.machine.started if self.run_id else 0.0}
        self.status_pub.publish(String(data=json.dumps(payload)))
        self.last_status_at = now


def main():
    # Keep DDS alive during SIGINT/SIGTERM settlement; the default rclpy
    # handler shuts it down before the client can cancel its owned goal.
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = None
    shutdown_requested = False
    def stop_signal(_signum, _frame):
        nonlocal shutdown_requested
        shutdown_requested = True
    previous = {sig: signal.signal(sig, stop_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        node = UwbRoundTripDemo()
        while rclpy.ok() and not shutdown_requested:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        if node is not None and rclpy.ok() and node.machine.busy:
            node.request_cancel()
            end = time.monotonic()+node.settle_timeout
            while rclpy.ok() and node.machine.pending is not None and time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=0.05)
            if node.machine.pending is not None:
                node.machine.fail('STOP_UNCONFIRMED', 'shutdown before child terminal result', False)
            node.emit_status()
        if node is not None:node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        for sig, handler in previous.items():signal.signal(sig, handler)
