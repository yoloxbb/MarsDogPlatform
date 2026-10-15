"""Single-owner task server. Existing MPPI keeps collision and emergency decisions."""
import json
import math
import signal
import threading
import time
from types import SimpleNamespace

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup, MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.time import Time
from rclpy.signals import SignalHandlerOptions
from rcl_interfaces.srv import GetParameters, SetParametersAtomically
from geometry_msgs.msg import PoseStamped, Twist, TwistStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from diagnostic_msgs.msg import DiagnosticArray
from tf2_ros import Buffer, TransformListener, TransformException
from robot_local_motion.action import ExecuteLocalMotion
from robot_local_motion.msg import TargetObservation
from robot_local_motion.srv import ReleaseRecovery
from .core import Limits, MotionTask, Pose, Target, parse_parameters, PLANNER_FIELDS, PLANNER_INTS, angle
from .guard import StampGuard, StopCheck, ObservationOrder
from .target_guard import ArrivalEvidence, TargetPolicy, target_status, bounded_approach_speed, closing_speed


def stamp_ns(stamp):
    return stamp.sec * 10**9 + stamp.nanosec


def yaw_of(q):
    values = (q.x, q.y, q.z, q.w)
    if not all(math.isfinite(x) for x in values) or abs(sum(x*x for x in values) - 1) > 0.02:
        raise ValueError('orientation must be a normalized finite quaternion')
    return math.atan2(2 * (q.w*q.z + q.x*q.y), 1 - 2 * (q.y*q.y + q.z*q.z))


def transform_point(x, y, z, transform):
    q, t = transform.rotation, transform.translation
    # Full 3D rotation is required for optical-frame observations; project onto
    # the odom ground plane only AFTER applying the calibrated extrinsic.
    tx, ty, tz = 2*(q.y*z-q.z*y), 2*(q.z*x-q.x*z), 2*(q.x*y-q.y*x)
    return (t.x+x+q.w*tx+q.y*tz-q.z*ty,
            t.y+y+q.w*ty+q.z*tx-q.x*tz)


class LocalMotionServer(Node):
    def __init__(self):
        super().__init__('local_motion_server')
        def param(name, default):
            return self.declare_parameter(name, default).value
        self.enabled = param('enable_motion', False)
        self.allow_unbounded_approach = param('allow_unbounded_approach', False)
        self.use_uwb_follow = param('use_uwb_follow_control', False)
        self.follow_profile = None
        if self.use_uwb_follow:
            from .uwb_follow_backend import load_follow_profile
            self.follow_profile = load_follow_profile()
        self.base = param('base_frame', 'base_footprint')
        self.odom_frame = param('odom_frame', 'odom')
        self.odom_child = param('odom_child_frame', self.base)
        self.odom_age = param('odom_timeout_sec', 0.1)
        self.obstacle_age = param('obstacle_timeout_sec', 0.7)
        self.planner_age = param('planner_timeout_sec', 0.2)
        self.stop_timeout = param('stop_timeout_sec', 5.0)
        self.exclusive = param('enforce_exclusive_output', True)
        self.output_topic = param('cmd_vel_topic', '/robot_local_motion/cmd_vel')
        self.limits = Limits(**{key: param(key, value) for key, value in Limits().__dict__.items()})
        self.stop_settings = dict(hold_sec=param('stop_hold_sec', 0.4),
                                 linear=param('stop_linear_threshold', 0.08),
                                 angular=param('stop_angular_threshold', 0.15),
                                 position=param('stop_position_threshold', 0.015),
                                 yaw=param('stop_yaw_threshold', 0.04))
        self.target_policy = TargetPolicy(
            enabled=param('strict_target_arrival', False),
            arrival_samples=param('target_arrival_samples', 5),
            braking_decel=param('target_braking_decel', 0.7),
            reaction_sec=param('target_reaction_sec', 0.2),
            position_margin=param('target_position_margin_m', 0.08))
        if (not self.base or not self.odom_frame or self.output_topic == '/robot_local_motion/planner_raw'
                or any(not math.isfinite(v) or v <= 0 for v in (
                    self.odom_age, self.obstacle_age, self.planner_age, self.stop_timeout,
                    *self.stop_settings.values(), *self.limits.__dict__.values()))
                or self.limits.min_linear_speed > self.limits.max_linear_speed):
            raise ValueError('invalid deployment limits, timeouts or frames')
        self.lock = threading.RLock()
        self.reserved = False
        self.active = None
        self.recovery_locked = False
        self.guard = StampGuard()
        self.pose = None
        self.odom_at = self.cloud_at = self.final_at = 0.0
        self.velocity = (math.inf, math.inf)
        self.obstacles = []
        self.input_errors = {'odom': '', 'cloud': ''}
        self.targets = {}
        self.pending_targets = {}
        self.target_tf_wait = param('target_tf_wait_sec', 0.2)
        if not math.isfinite(self.target_tf_wait) or not 0 < self.target_tf_wait <= 0.5:
            raise ValueError('target_tf_wait_sec must be in (0,0.5]')
        self.target_order = ObservationOrder()
        self.sequences = self.target_order.sequences
        self.final = (0.0, 0.0)
        self.decisions = {}
        self.decision_topic = param('planner_decision_topic', '/robot_local_motion/planner_decision')
        self.planner_state, self.diagnostic_at = '', 0.0
        self.baseline = None
        self.pending_config = []
        self.last_ros_ns = None
        self.tf = Buffer()
        self.tf_listener = TransformListener(self.tf, self)
        # Control and subscription callbacks share one group; action execution waits
        # in another group and never writes actuator commands itself.
        self.control_group = MutuallyExclusiveCallbackGroup()
        self.action_group = ReentrantCallbackGroup()
        self.cmd_pub = self.create_publisher(Twist, self.output_topic, 10)
        self.command_pub = self.create_publisher(TwistStamped, param('command_topic', '/robot_local_motion/command'), 10)
        self.nominal_pub = self.create_publisher(TwistStamped, param('nominal_cmd_topic', '/robot_local_motion/nominal_cmd'), 10)
        def sub(msg_type, name, default, callback, qos=10):
            return self.create_subscription(msg_type, param(name, default), callback, qos,
                                            callback_group=self.control_group)
        from rclpy.qos import qos_profile_sensor_data
        self.subscriptions_owned = [
            sub(Odometry, 'odom_topic', '/leg_odom2', self.on_odom, qos_profile_sensor_data),
            sub(PointCloud2, 'obstacle_topic', '/local_grid_obstacle', self.on_cloud, qos_profile_sensor_data),
            sub(TargetObservation, 'target_topic', '/robot_local_motion/target', self.on_target, qos_profile_sensor_data),
            sub(TwistStamped, 'final_cmd_topic', '/robot_local_motion/final_cmd', self.on_final),
            sub(DiagnosticArray, 'diagnostics_topic', '/robot_local_motion/planner_diagnostics', self.on_diagnostics),
        ]
        if self.use_uwb_follow:
            self.subscriptions_owned.append(self.create_subscription(DiagnosticArray,
                self.decision_topic, self.on_decision, 10, callback_group=self.control_group))
        planner = param('planner_node', '/local_velocity_planner_node').rstrip('/')
        self.get_params = self.create_client(GetParameters, planner + '/get_parameters', callback_group=self.control_group)
        self.set_params = self.create_client(SetParametersAtomically, planner + '/set_parameters_atomically', callback_group=self.control_group)
        self.planner_keys = ['max_linear_speed', 'max_angular_speed', *PLANNER_FIELDS]
        self.deployment_keys = ['robot_length', 'robot_width', 'safety_margin', 'min_linear_speed',
                                'base_frame', 'odom_frame', 'odom_child_frame', 'enable_motion', 'enable_task_parameters',
                                'task_parameter_defaults_json']
        if self.use_uwb_follow:
            self.deployment_keys += ['decision_topic', 'max_reverse_speed', 'angular_command_deadband']
        self.action_server = ActionServer(self, ExecuteLocalMotion,
            param('action_name', '/robot_local_motion/execute'), self.execute,
            goal_callback=self.accept, cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=self.action_group)
        self.recovery_service = self.create_service(ReleaseRecovery,
            '/robot_local_motion/release_recovery', self.release_recovery, callback_group=self.control_group)
        self.recovery_stop = StopCheck(**self.stop_settings)
        self.timer = self.create_timer(0.05, self.tick, callback_group=self.control_group)

    def conflict(self):
        return self.exclusive and self.count_publishers(self.output_topic) > 1

    def accept(self, request):
        try:
            p = parse_parameters(request.parameters_json, request.mode, self.limits,
                allow_unbounded_approach=self.allow_unbounded_approach)
            if request.mode in ('approach', 'follow', 'orbit') or (request.mode == 'explore' and p['center_mode'] == 'target'):
                if not request.target_id or not request.target_source:
                    raise ValueError('target_id and target_source are mandatory')
            if request.mode in ('move', 'turn') or p['center_mode'] == 'goal':
                if not request.goal.header.frame_id:
                    raise ValueError('fixed goal requires a frame')
                yaw_of(request.goal.pose.orientation)
                if not all(math.isfinite(v) for v in (request.goal.pose.position.x, request.goal.pose.position.y, request.goal.pose.position.z)):
                    raise ValueError('invalid goal coordinates')
                if abs(request.goal.pose.position.z) > 0.05:
                    raise ValueError('fixed local goals must lie on the ground plane')
        except (ValueError, TypeError) as exc:
            self.get_logger().warning('Goal rejected: ' + str(exc))
            return GoalResponse.REJECT
        with self.lock:
            if (not self.enabled or self.reserved or self.recovery_locked or self.conflict()
                    or any(not f.done() for f in self.pending_config)):
                return GoalResponse.REJECT
            self.reserved = True
        return GoalResponse.ACCEPT

    def execute(self, handle):
        p = parse_parameters(handle.request.parameters_json, handle.request.mode, self.limits,
            allow_unbounded_approach=self.allow_unbounded_approach)
        task = SimpleNamespace(handle=handle, p=p, started=time.monotonic(),
            phase='STARTING', done=threading.Event(), result=None, engine=None,
            future=None, stop=StopCheck(**self.stop_settings), outcome='', reason='',
            input_lost_since=None, feedback_at=0.0, config_started=0.0,
            command_after_ns=0, stop_started=0.0, verify_since=None,
            verify_arrival=ArrivalEvidence(self.target_policy.arrival_samples))
        with self.lock:
            self.active = task
        while rclpy.ok() and not task.done.wait(0.05):
            pass
        if task.result is None:
            # Shutdown cannot prove physical stop; callers must retain ownership.
            task.result = ExecuteLocalMotion.Result(outcome='STOP_UNCONFIRMED', message='server shutdown', stop_confirmed=False)
        if task.result.outcome == 'CANCELED':
            handle.canceled()
        elif task.result.outcome == 'SUCCEEDED':
            handle.succeed()
        else:
            handle.abort()
        return task.result

    def pose_msg(self):
        out = PoseStamped()
        out.header.frame_id = self.odom_frame
        out.header.stamp = self.get_clock().now().to_msg()
        if self.pose:
            out.pose.position.x, out.pose.position.y = self.pose.x, self.pose.y
            out.pose.orientation.z = math.sin(self.pose.yaw / 2)
            out.pose.orientation.w = math.cos(self.pose.yaw / 2)
        return out

    def transform(self, x, y, frame, stamp, yaw=0.0, z=0.0):
        if frame == self.odom_frame:
            return Pose(x, y, yaw)
        transform = self.tf.lookup_transform(self.odom_frame, frame, Time.from_msg(stamp))
        rotation = yaw_of(transform.transform.rotation)
        ox, oy = transform_point(x, y, z, transform.transform)
        return Pose(ox, oy, angle(yaw + rotation))

    def on_odom(self, msg):
        if msg.header.frame_id != self.odom_frame or msg.child_frame_id != self.odom_child:
            self.odom_at = 0.0
            self.input_errors['odom'] = 'odometry frame mismatch'
            return
        try:
            pose = Pose(msg.pose.pose.position.x, msg.pose.pose.position.y, yaw_of(msg.pose.pose.orientation))
            velocity = (msg.twist.twist.linear.x, msg.twist.twist.angular.z)
            if not all(math.isfinite(x) for x in (*pose.__dict__.values(), *velocity)):
                raise ValueError('non-finite odometry')
            if not self.guard.accept('odom', stamp_ns(msg.header.stamp), self.get_clock().now().nanoseconds, self.odom_age):
                raise ValueError('invalid odom stamp')
            age = (self.get_clock().now().nanoseconds - stamp_ns(msg.header.stamp)) / 1e9
            self.pose, self.velocity, self.odom_at = pose, velocity, time.monotonic() - max(0.0, age)
            self.input_errors['odom'] = ''
        except ValueError as exc:
            self.odom_at = 0.0
            self.input_errors['odom'] = str(exc)

    def on_cloud(self, msg):
        try:
            if (msg.header.frame_id not in (self.odom_frame, self.base) or msg.width * msg.height > 50000 or
                    not self.guard.accept('cloud', stamp_ns(msg.header.stamp), self.get_clock().now().nanoseconds, self.obstacle_age)):
                raise ValueError('invalid cloud frame, size or stamp')
            points = list(point_cloud2.read_points(msg, field_names=('x', 'y'), skip_nans=True))
            obstacles = [(float(p[0]), float(p[1])) for p in points if math.isfinite(p[0]) and math.isfinite(p[1])]
            if msg.header.frame_id == self.base and obstacles:
                transform = self.tf.lookup_transform(self.odom_frame, self.base, Time.from_msg(msg.header.stamp)).transform
                yaw_of(transform.rotation)
                obstacles = [transform_point(x, y, 0.0, transform) for x, y in obstacles]
            self.obstacles = obstacles
            age = (self.get_clock().now().nanoseconds - stamp_ns(msg.header.stamp)) / 1e9
            self.cloud_at = time.monotonic() - max(0.0, age)
            self.input_errors['cloud'] = ''
        except Exception as exc:
            self.cloud_at = 0.0
            self.input_errors['cloud'] = str(exc)

    def on_target(self, msg):
        key = (msg.source, msg.target_id)
        keys = self.targets.keys() | self.pending_targets.keys()
        if not all(key) or (key not in keys and len(keys) >= 64):
            return
        if not self.target_order.accept(key, msg.sequence, stamp_ns(msg.header.stamp),
                                        self.get_clock().now().nanoseconds, msg.valid):
            return  # Replayed/older invalidations must not erase a fresh target.
        try:
            if (not msg.valid or not msg.header.frame_id or not 0 <= msg.confidence <= 1 or
                    not all(math.isfinite(x) for x in (msg.position.x, msg.position.y, msg.position.z))):
                raise ValueError('invalid target')
            self.cache_target(key, msg)
            self.pending_targets.pop(key, None)
        except TransformException:
            if self.target_policy.enabled:
                self.pending_targets[key] = msg
            else:
                self.targets[key] = None
        except Exception:
            self.pending_targets.pop(key, None)
            self.targets[key] = None

    def cache_target(self, key, msg):
        pose = self.transform(msg.position.x, msg.position.y, msg.header.frame_id, msg.header.stamp, z=msg.position.z)
        age = (self.get_clock().now().nanoseconds-stamp_ns(msg.header.stamp))/1e9
        self.targets[key] = Target(pose.x, pose.y, time.monotonic()-max(0.0,age), msg.confidence, msg.sequence)

    def retry_target_transforms(self, ros_ns):
        for key, msg in list(self.pending_targets.items()):
            if (ros_ns-stamp_ns(msg.header.stamp))/1e9 > self.target_tf_wait:
                self.targets[key] = None
                self.pending_targets.pop(key, None)
                continue
            try:
                self.cache_target(key, msg)
                self.pending_targets.pop(key, None)
            except TransformException:
                pass
            except Exception:
                self.targets[key] = None
                self.pending_targets.pop(key, None)

    def on_final(self, msg):
        ns = stamp_ns(msg.header.stamp)
        if (msg.header.frame_id != self.base or
                not self.guard.accept('final', ns, self.get_clock().now().nanoseconds, self.planner_age)):
            self.final_at = 0.0
            return
        values = (msg.twist.linear.x, msg.twist.angular.z)
        if not all(math.isfinite(x) for x in values):
            self.final_at = 0.0
            return
        age = (self.get_clock().now().nanoseconds - ns) / 1e9
        self.final, self.final_at = values, time.monotonic() - max(0.0, age)
        self.final_ns = ns

    def on_diagnostics(self, msg):
        if msg.status:
            self.planner_state = msg.status[0].message
            self.diagnostic_at = time.monotonic()

    def on_decision(self, msg):
        ns = stamp_ns(msg.header.stamp)
        if (msg.header.frame_id != self.base or len(msg.status) != 1 or
                not self.guard.accept('decision', ns, self.get_clock().now().nanoseconds, self.planner_age)):
            return
        status = msg.status[0]
        values = {value.key: value.value for value in status.values}
        try:
            final = float(values['final_v']), float(values['final_w'])
            maximum = float(values['max_reverse_speed'])
            if not all(math.isfinite(v) for v in (*final, maximum)) or maximum <= 0:
                return
            self.decisions[ns] = dict(state=status.message, final=final, maximum=maximum,
                recovery=values['emergency_recovery_active']=='true', enabled=values['enable_motion']=='true')
            self.decisions = {stamp: row for stamp, row in self.decisions.items()
                              if ns-stamp <= int(self.planner_age*1e9)}
        except (KeyError, ValueError):
            return

    def reverse_allowed(self, task, output):
        decision = self.decisions.get(getattr(self, 'final_ns', 0))
        return bool(task.engine.follow_control is not None and
            task.p.get('effective_planner', {}).get('enable_emergency_reverse') and
            decision and decision['state']=='EMERGENCY_REVERSING' and decision['recovery'] and
            decision['enabled'] and all(abs(a-b)<=1e-9 for a,b in zip(output, decision['final'])) and
            -min(task.p['max_linear_speed'], task.reverse_limit, decision['maximum']) <= output[0] < 0 and
            abs(output[1]) <= 1e-9)

    def publish(self, linear=0.0, angular=0.0, nominal=True):
        if nominal:
            cmd = TwistStamped()
            cmd.header.frame_id = self.base
            cmd.header.stamp = self.get_clock().now().to_msg()
            cmd.twist.linear.x, cmd.twist.angular.z = float(linear), float(angular)
            self.nominal_pub.publish(cmd)
        else:
            cmd = Twist()
            cmd.linear.x, cmd.angular.z = float(linear), float(angular)
            self.cmd_pub.publish(cmd)
            stamped = TwistStamped()
            stamped.header.frame_id = self.base
            stamped.header.stamp = self.get_clock().now().to_msg()
            stamped.twist = cmd
            self.command_pub.publish(stamped)

    def zeros(self):
        self.publish()
        self.publish(nominal=False)

    def stop_task(self, task, outcome, reason=''):
        if task.phase != 'STOPPING' or (task.outcome == 'SUCCEEDED' and outcome != 'SUCCEEDED'):
            task.phase, task.outcome, task.reason = 'STOPPING', outcome, reason
            task.stop_started = time.monotonic()
            task.stop = StopCheck(**self.stop_settings)
            task.verify_since = None
            task.verify_arrival.reset()
        self.zeros()

    def complete(self, task, confirmed):
        outcome = task.outcome if confirmed else 'STOP_UNCONFIRMED'
        task.result = ExecuteLocalMotion.Result(outcome=outcome,
            message=task.reason if confirmed else f'{task.outcome}: physical stop not confirmed',
            stop_confirmed=confirmed, final_pose=self.pose_msg(),
            effective_parameters_json=json.dumps(task.p, sort_keys=True))
        self.recovery_locked = not confirmed
        self.reserved = False
        self.active = None
        if getattr(task, 'engine', None) is not None and task.engine.follow_control is not None:
            task.engine.follow_control.close()
        task.done.set()

    def stopped(self, checker, now):
        return self.pose is not None and checker.update(now, self.pose, *self.velocity,
                                                       now - self.odom_at <= self.odom_age)

    def verify_target(self, task, now):
        if task.verify_since is None:
            task.verify_since = now
        request = task.handle.request
        target = self.targets.get((request.target_source, request.target_id))
        state, _ = target_status(self.pose, target, now, task.p, self.limits)
        if state == 'MOVING':
            task.phase = 'ACTIVE'
            task.verify_since = None
            task.verify_arrival.reset()
            task.engine.holding = False
            task.engine.holding_since = None
            task.engine.arrival.reset()
            task.engine.progress_time = now
            task.engine.progress_pose = self.pose
            if task.engine.follow_control is not None:
                task.engine.follow_control.reset()
            task.command_after_ns = self.get_clock().now().nanoseconds
            self.final_at = 0.0
            return
        if state == 'TARGET_OUT_OF_RANGE':
            task.outcome, task.reason = state, 'post-stop target check: ' + state
            self.complete(task, True)
            return
        qualified = state == 'HOLDING' and target.received_at > task.verify_since
        if task.verify_arrival.update(target, qualified, task.p['arrival_hold_sec']):
            self.complete(task, True)
        elif now-task.verify_since >= task.p['input_recovery_timeout_sec']:
            task.outcome, task.reason = 'INPUT_LOST', 'fresh post-stop target evidence unavailable'
            self.complete(task, True)

    def release_recovery(self, request, response):
        response.released = bool(request.confirm_release and self.active is None and
                                 all(f.done() for f in self.pending_config) and
                                 self.stopped(self.recovery_stop, time.monotonic()))
        if response.released:
            self.recovery_locked = False
        response.message = 'released' if response.released else 'fresh stationary odometry is required'
        return response

    def tick(self):
        now = time.monotonic()
        ros_ns = self.get_clock().now().nanoseconds
        with self.lock:
            task = self.active
            self.pending_config = [f for f in self.pending_config if not f.done()]
            clock_reset = self.last_ros_ns is not None and ros_ns < self.last_ros_ns
            self.last_ros_ns = ros_ns
            if clock_reset:
                self.guard = StampGuard()
                self.odom_at = self.cloud_at = self.final_at = 0.0
                self.targets.clear()
                self.decisions.clear()
                self.pending_targets.clear()
                self.target_order.stamps.clear()
            self.retry_target_transforms(ros_ns)
            if task is None:
                if self.recovery_locked:
                    self.zeros()
                    self.stopped(self.recovery_stop, now)
                return
            if clock_reset:
                self.stop_task(task, 'INPUT_LOST', 'ROS clock moved backwards')
            if task.handle.is_cancel_requested and (task.phase != 'STOPPING' or task.outcome == 'SUCCEEDED'):
                self.stop_task(task, 'CANCELED')
            if self.conflict() and (task.phase != 'STOPPING' or task.outcome == 'SUCCEEDED'):
                self.stop_task(task, 'CONTROL_CONFLICT', 'multiple output publishers')
            if (task.p['timeout_sec'] > 0 and now - task.started >= task.p['timeout_sec']
                    and (task.phase != 'STOPPING' or task.outcome == 'SUCCEEDED')):
                self.stop_task(task, 'TIMEOUT')
            if task.phase == 'STOPPING':
                self.zeros()
                if self.stopped(task.stop, now):
                    if self.target_policy.enabled and task.handle.request.mode == 'approach' and task.outcome == 'SUCCEEDED':
                        self.verify_target(task, now)
                    else:
                        self.complete(task, True)
                elif now - task.stop_started >= self.stop_timeout:
                    self.complete(task, False)
                else:
                    task.verify_since = None
                    task.verify_arrival.reset()
                return
            fresh = self.pose is not None and now - self.odom_at <= self.odom_age and now - self.cloud_at <= self.obstacle_age
            if task.phase == 'STARTING':
                self.zeros()
                if now - task.started >= task.p['startup_timeout_sec']:
                    self.stop_task(task, 'INPUT_LOST', 'startup odometry, cloud, planner or stop check unavailable')
                    return
                if not fresh or not self.stopped(task.stop, now) or not self.get_params.service_is_ready() or not self.set_params.service_is_ready():
                    return
                try:
                    request = task.handle.request
                    goal = self.pose
                    if request.mode in ('move', 'turn') or task.p['center_mode'] == 'goal':
                        g = request.goal
                        # Relative fixed goals use the acceptance pose, not a moving reference.
                        if g.header.frame_id == self.base:
                            x, y = g.pose.position.x, g.pose.position.y
                            goal = Pose(self.pose.x + math.cos(self.pose.yaw)*x - math.sin(self.pose.yaw)*y,
                                        self.pose.y + math.sin(self.pose.yaw)*x + math.cos(self.pose.yaw)*y,
                                        angle(self.pose.yaw + yaw_of(g.pose.orientation)))
                        else:
                            goal = self.transform(g.pose.position.x, g.pose.position.y, g.header.frame_id,
                                                  g.header.stamp, yaw_of(g.pose.orientation))
                    follow = None
                    if self.use_uwb_follow and request.mode == 'approach':
                        from .uwb_follow_backend import UwbFollowControl
                        follow = UwbFollowControl(self.follow_profile, task.p['desired_distance_m'],
                            self.limits.min_linear_speed, task.p['max_linear_speed'], task.p['max_angular_speed'])
                        task.p['effective_follow'] = follow.config
                        task.p['yaw_tolerance_rad'] = follow.config['angle_reengage']
                    task.engine = MotionTask(request.mode, task.p, self.pose, goal, task.started,
                        self.limits, self.target_policy, follow)
                except Exception as exc:
                    self.stop_task(task, 'CONFIG_ERROR', str(exc))
                    return
                task.future = self.get_params.call_async(GetParameters.Request(names=self.planner_keys+self.deployment_keys))
                self.pending_config.append(task.future)
                task.phase, task.config_started = 'READ_PARAMS', now
                return
            if task.phase in ('READ_PARAMS', 'SET_PARAMS'):
                self.zeros()
                if not task.future.done():
                    if now - task.config_started > task.p['startup_timeout_sec']:
                        self.stop_task(task, 'CONFIG_ERROR', 'planner configuration timeout')
                    return
                try:
                    result = task.future.result()
                    if task.phase == 'READ_PARAMS':
                        queried_keys = self.planner_keys+self.deployment_keys
                        observed = {k: Parameter.from_parameter_msg(
                            __import__('rcl_interfaces.msg', fromlist=['Parameter']).Parameter(name=k, value=v)).value
                            for k, v in zip(queried_keys, result.values)}
                        if len(result.values) != len(queried_keys) or any(v is None for v in observed.values()):
                            raise ValueError('missing planner task/deployment parameters')
                        radius = math.hypot(observed['robot_length']/2 + observed['safety_margin'],
                                            observed['robot_width']/2 + observed['safety_margin'])
                        if (radius > self.limits.robot_radius or observed['min_linear_speed'] != self.limits.min_linear_speed or
                                observed['base_frame'] != self.base or observed['odom_frame'] != self.odom_frame or
                                observed['odom_child_frame'] != self.odom_child or not observed['enable_motion'] or
                                not observed['enable_task_parameters']):
                            raise ValueError('planner footprint, chassis minimum, frames or motion gate mismatch')
                        if self.use_uwb_follow:
                            if observed['decision_topic'] != self.decision_topic or observed['max_reverse_speed'] <= 0:
                                raise ValueError('UWB follow recovery decision channel or reverse limit mismatch')
                            task.reverse_limit = observed['max_reverse_speed']
                            if task.engine.follow_control is not None:
                                # The original planner drops tiny angular commands. Completion
                                # must use that effective stopping band rather than waiting for
                                # a nominal correction that the unchanged planner cannot execute.
                                config = task.engine.follow_control.config
                                if config['angular_kp'] <= 0:
                                    raise ValueError('round-trip UWB follow requires positive angular gain')
                                task.p['yaw_tolerance_rad'] = max(config['angle_reengage'],
                                    config['angle_deadband'] + observed['angular_command_deadband']/config['angular_kp']) + 1e-9
                        self.baseline = json.loads(observed['task_parameter_defaults_json'])
                        if not isinstance(self.baseline, dict) or set(self.baseline) != set(self.planner_keys):
                            raise ValueError('planner startup profile does not match the task contract')
                        settings = {**self.baseline, **task.p['planner'],
                                    'max_linear_speed': task.p['max_linear_speed'],
                                    'max_angular_speed': task.p['max_angular_speed']}
                        if 'max_avoidance_angular_speed' not in task.p['planner']:
                            settings['max_avoidance_angular_speed'] = min(settings['max_avoidance_angular_speed'], settings['max_angular_speed'])
                        if 'min_avoidance_angular_speed' not in task.p['planner']:
                            settings['min_avoidance_angular_speed'] = min(settings['min_avoidance_angular_speed'], settings['max_avoidance_angular_speed'])
                        task.p['effective_planner'] = settings
                        task.future = self.set_params.call_async(SetParametersAtomically.Request(
                            parameters=[Parameter(k, value=v if isinstance(v, bool) or k in PLANNER_INTS else float(v)).to_parameter_msg()
                                        for k, v in settings.items()]))
                        self.pending_config.append(task.future)
                        task.phase = 'SET_PARAMS'
                    elif not result.result.successful:
                        raise ValueError(result.result.reason)
                    else:
                        task.phase = 'ACTIVE'
                        task.command_after_ns = ros_ns
                        self.final_at = 0.0
                        task.stop = StopCheck(**self.stop_settings)
                except Exception as exc:
                    self.stop_task(task, 'CONFIG_ERROR', str(exc))
                return
            if not fresh:
                self.zeros()
                if task.input_lost_since is None:
                    task.input_lost_since = now
                if now - task.input_lost_since >= task.p['input_recovery_timeout_sec']:
                    self.stop_task(task, 'INPUT_LOST', 'odometry or obstacles expired: '+json.dumps(self.input_errors))
                return
            task.input_lost_since = None
            request = task.handle.request
            target = self.targets.get((request.target_source, request.target_id))
            blocked = now - self.diagnostic_at <= 1.0 and self.planner_state in ('BLOCKED', 'EMERGENCY_STOP', 'EMERGENCY_REVERSE_BLOCKED')
            original_follow = task.engine.follow_control is not None
            # Keep the original nominal controller running during planner recovery.
            # Feeding BLOCKED back as zero nominal cancels the old reverse state machine.
            step = task.engine.tick(now, self.pose, target, self.obstacles,
                blocked and not original_follow, self.velocity[0], self.velocity[1])
            if step.outcome:
                self.stop_task(task, step.outcome)
                return
            self.publish(step.linear, step.angular)
            # Planner output is gated by the CURRENT task state and freshness. A
            # stale previous task cannot leak through while a new goal configures.
            output = self.final if (now - self.final_at <= self.planner_age and
                                   getattr(self, 'final_ns', 0) > task.command_after_ns) else (0.0, 0.0)
            reverse = original_follow and self.reverse_allowed(task, output)
            if original_follow and output[0] < 0 and not reverse:
                output = (0.0, 0.0)
            if step.state in ('TARGET_LOST', 'HOLDING', 'DWELLING', 'RESELECTING', 'BLOCKED', 'BRAKING') and not step.angular:
                output = (0.0, 0.0)
                reverse = False
            elif step.linear == 0.0 and not reverse:
                output = (0.0, output[1])
            linear, angular = output
            if self.target_policy.enabled and request.mode == 'approach' and target is not None and linear != 0:
                distance = math.hypot(target.x-self.pose.x, target.y-self.pose.y)
                # A reverse away from the selected target needs no approach brake;
                # a reverse toward a rear target retains the same lower-distance guard.
                if linear > 0 or closing_speed(self.pose, target, linear) > 0:
                    safe = bounded_approach_speed(abs(linear), closing_speed(self.pose, target, self.velocity[0]),
                        distance, max(self.limits.min_stand_off_distance, task.p['desired_distance_m']-task.p['distance_deadband_m']), self.limits.min_linear_speed,
                        self.target_policy, now-target.received_at)
                    linear = math.copysign(safe, linear)
            if (abs(linear) > task.p['max_linear_speed'] + 1e-6 or abs(angular) > task.p['max_angular_speed'] + 1e-6 or
                    not task.engine.boundary_allows(self.pose, linear, angular)):
                linear = angular = 0.0
            self.publish(linear, angular, nominal=False)
            if reverse and linear < 0:
                step.state = 'EMERGENCY_REVERSING'
            if now - task.feedback_at >= 0.2:
                task.feedback_at = now
                task.handle.publish_feedback(ExecuteLocalMotion.Feedback(state=step.state,
                    distance_m=float(step.distance), progress=float(step.progress),
                    elapsed_sec=now-task.started, current_pose=self.pose_msg()))


def main():
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = LocalMotionServer()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    shutdown_requested = False
    def stop_signal(_signum, _frame):
        nonlocal shutdown_requested
        shutdown_requested = True
    previous = {sig: signal.signal(sig, stop_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        while rclpy.ok() and not shutdown_requested:
            executor.spin_once(timeout_sec=0.1)
    finally:
        with node.lock:
            if rclpy.ok():
                node.zeros()
            if node.active is not None:
                node.stop_task(node.active, 'CANCELED', 'server shutdown')
        deadline = time.monotonic()+node.stop_timeout+0.5
        while rclpy.ok() and node.active is not None and time.monotonic()<deadline:
            executor.spin_once(timeout_sec=0.05)
        with node.lock:
            if rclpy.ok():node.zeros()
            if node.active is not None:node.complete(node.active, False)
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        for sig, handler in previous.items():signal.signal(sig, handler)
