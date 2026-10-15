"""Opt-in public ROS task client and existing-chassis velocity bridge.

No robotics implementation imports. Legacy ACT routes remain unchanged unless
ctx.params['local_motion']['unit_id'] explicitly selects one movement unit.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import math
import threading
import time
from typing import Any
from .velocity import TwistCommand
from ..local_motion_request import MOVEMENT_UNITS, request_for


@dataclass
class LocalMotionOutcome:
    success: bool = False
    reason: str = ''
    canceled: bool = False
    timed_out: bool = False
    metadata: dict = field(default_factory=dict)


class Ros2LocalMotionClient:
    def __init__(self, node, action_name='/robot_local_motion/execute'):
        from robot_local_motion.action import ExecuteLocalMotion
        from rclpy.action import ActionClient
        from rclpy.callback_groups import ReentrantCallbackGroup
        self.node, self.kind = node, ExecuteLocalMotion
        self.client = ActionClient(node, ExecuteLocalMotion, action_name,
                                   callback_group=ReentrantCallbackGroup())
        self.handle = None
        self.cancel_event = threading.Event()
        self.pending = None
        from robot_local_motion.srv import ReleaseRecovery
        self.recovery_kind = ReleaseRecovery
        self.recovery_client = node.create_client(ReleaseRecovery, '/robot_local_motion/release_recovery',
                                                  callback_group=ReentrantCallbackGroup())

    def recover(self, timeout_sec=3.0):
        if self.pending is not None and not self.pending.done():
            return False
        if not self.recovery_client.wait_for_service(timeout_sec=timeout_sec):
            return False
        future = self.recovery_client.call_async(self.recovery_kind.Request(confirm_release=True))
        end = time.monotonic()+timeout_sec
        while not future.done() and time.monotonic() < end:
            time.sleep(.02)
        return bool(future.done() and future.result().released)

    def cancel(self):
        self.cancel_event.set()
        if self.handle:
            self.handle.cancel_goal_async()

    def _late_acceptance(self, future):
        try:
            handle = future.result()
            if handle and handle.accepted:
                self.handle = handle
                if self.cancel_event.is_set():
                    handle.cancel_goal_async()
        except Exception:
            pass

    def run(self, job, deadline, should_stop, accepted, feedback=None):
        self.cancel_event.clear()
        if not self.client.wait_for_server(timeout_sec=min(3.0, max(0.0, deadline-time.monotonic()))):
            return LocalMotionOutcome(reason='local_motion_server_unavailable')
        if should_stop():
            return LocalMotionOutcome(reason='canceled before send', canceled=True)
        goal = self.kind.Goal()
        goal.mode = job['mode']
        goal.target_id, goal.target_source = job.get('target_id', ''), job.get('target_source', '')
        goal.parameters_json = json.dumps(job['parameters'], allow_nan=False)
        fixed = job.get('goal', {})
        goal.goal.header.frame_id = fixed.get('frame_id', '')
        goal.goal.pose.position.x, goal.goal.pose.position.y = float(fixed.get('x', 0)), float(fixed.get('y', 0))
        yaw = float(fixed.get('yaw', 0))
        goal.goal.pose.orientation.z, goal.goal.pose.orientation.w = math.sin(yaw/2), math.cos(yaw/2)
        self.pending = self.client.send_goal_async(goal, feedback_callback=feedback)
        self.pending.add_done_callback(self._late_acceptance)
        acceptance_deadline = min(deadline, time.monotonic()+3.0)
        while not self.pending.done() and time.monotonic() < acceptance_deadline and not should_stop():
            time.sleep(.02)
        if not self.pending.done():
            self.cancel()
            return LocalMotionOutcome(reason='local_motion_acceptance_unknown',
                timed_out=time.monotonic() >= deadline and not should_stop(),
                metadata={'recovery_required':True})
        handle = self.pending.result()
        if not handle or not handle.accepted:
            return LocalMotionOutcome(reason='local_motion_goal_rejected')
        self.handle = handle
        accepted()
        future = handle.get_result_async()
        cancel_deadline = None
        budget_expired = False
        while not future.done():
            if should_stop() or time.monotonic() >= deadline or self.cancel_event.is_set():
                if cancel_deadline is None:
                    budget_expired = time.monotonic() >= deadline and not should_stop()
                    self.cancel()
                    cancel_deadline = time.monotonic()+6.0
                if time.monotonic() >= cancel_deadline:
                    return LocalMotionOutcome(reason='local_motion_terminal_unknown', timed_out=budget_expired,
                                              metadata={'recovery_required':True})
            time.sleep(.02)
        wrapped = future.result()
        # A fast cancellation result may complete between polling iterations.
        budget_expired = budget_expired or (self.cancel_event.is_set()
            and time.monotonic() >= deadline and not should_stop())
        self.handle = None
        result = wrapped.result
        metadata = {'outcome':result.outcome, 'stop_confirmed':result.stop_confirmed,
                    'effective_parameters_json':result.effective_parameters_json,
                    'recovery_required':not result.stop_confirmed}
        return LocalMotionOutcome(success=wrapped.status == 4 and result.outcome == 'SUCCEEDED' and result.stop_confirmed,
            reason='local_motion_client_timeout' if budget_expired else (result.message or result.outcome),
            canceled=result.outcome == 'CANCELED' and not budget_expired,
            timed_out=result.outcome == 'TIMEOUT' or budget_expired, metadata=metadata)


class LocalMotionAdapter:
    def __init__(self, *, node=None, backend, allowed_units, should_stop=lambda:False,
                 client=None, action_name='/robot_local_motion/execute',
                 command_topic='/robot_local_motion/command', base_frame='base_footprint'):
        if not frozenset(allowed_units) <= MOVEMENT_UNITS:
            raise ValueError('only movement units may use local motion')
        self.backend, self.allowed_units = backend, frozenset(allowed_units)
        self.should_stop = should_stop
        self.client = client or Ros2LocalMotionClient(node, action_name)
        self.active = self.forwarding = False
        self.last_error = ''
        self.lock = threading.Lock()
        self.cancel_requested = threading.Event()
        self.command_lock = threading.RLock()
        self.command = TwistCommand()
        self.command_at = 0.0
        self.command_start_ns = self.command_stamp_ns = 0
        self.command_deadline = math.inf
        self.budget_cancel_sent = False
        self.node, self.base_frame = node, base_frame
        if node is not None:
            from geometry_msgs.msg import TwistStamped
            from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
            self.group = MutuallyExclusiveCallbackGroup()
            self.sub = node.create_subscription(TwistStamped, command_topic, self.observe, 10, callback_group=self.group)
            self.timer = node.create_timer(.05, self.forward, callback_group=self.group)

    def can_execute(self, unit_id):
        return unit_id in self.allowed_units and all(callable(getattr(self.backend, name, None))
            for name in ('prepare_navigation', 'publish_velocity', 'finish_navigation'))

    def observe(self, msg):
        now_ns = self.node.get_clock().now().nanoseconds
        ns = msg.header.stamp.sec*10**9 + msg.header.stamp.nanosec
        values = (msg.twist.linear.x,msg.twist.angular.z)
        with self.command_lock:
            if (msg.header.frame_id != self.base_frame or ns <= max(self.command_start_ns,self.command_stamp_ns)
                    or not 0 <= (now_ns-ns)/1e9 <= .2 or not all(math.isfinite(x) for x in values)):
                return
            self.command_stamp_ns = ns
            self.command = TwistCommand(linear_x=values[0],angular_z=values[1])
            self.command_at = time.monotonic() - max(0.0, (now_ns-ns)/1e9)

    def forward(self):
        with self.command_lock:
            if self.active:
                if self.should_stop() or self.cancel_requested.is_set():
                    self.cancel_step()
                if time.monotonic() >= self.command_deadline:
                    # The local output budget is enforced even if DDS cancel or
                    # the task server's terminal response is delayed.
                    self.forwarding = False
                    if not self.budget_cancel_sent:
                        self.budget_cancel_sent = True
                        try:
                            self.client.cancel()
                        except Exception as exc:
                            self.last_error = 'local_motion_cancel_send_failed:' + str(exc)
                command = self.command if self.forwarding and time.monotonic()-self.command_at <= .2 else TwistCommand()
                self.backend.publish_velocity(command)

    def cancel_step(self, *_):
        self.cancel_requested.set()
        with self.command_lock:
            self.forwarding = False
            if self.active:
                try:
                    self.backend.publish_velocity(TwistCommand())
                except Exception as exc:
                    self.last_error = 'local_motion_stop_publish_failed:' + str(exc)
        try:
            self.client.cancel()
        except Exception as exc:
            self.last_error = 'local_motion_cancel_send_failed:' + str(exc)

    request_cancel = cancel_step
    emergency_stop = cancel_step

    def recover(self):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            if not self.active:
                return True
            self.cancel_step()
            if not self.client.recover() or not self.backend.finish_navigation():
                return False
            self.active = False
            self.last_error = ''
            return True
        finally:
            self.lock.release()

    def execute_step(self, unit_config, ctx, duration):
        result = self.execute_task(unit_config, ctx, duration)
        self.last_error = result.reason if not result.success else ''
        return result.success

    def execute_task(self, unit_config, ctx, timeout_sec, *, cancel_check=lambda: False):
        if not self.lock.acquire(blocking=False):
            return LocalMotionOutcome(reason='local_motion_busy')
        try:
            if self.active:
                return LocalMotionOutcome(reason='local_motion_recovery_required', metadata={'recovery_required':True})
            self.cancel_requested.clear()
            if not self.can_execute(str(unit_config.get('unit_id',''))):
                return LocalMotionOutcome(reason='local_motion_unit_or_backend_protocol_unavailable')
            raw = ctx.params.get('local_motion')
            unit = str(unit_config.get('unit_id',''))
            try:
                job = request_for(raw, unit, self.allowed_units)
            except ValueError as exc:
                return LocalMotionOutcome(reason=str(exc))
            settings = job['parameters']
            requested = settings.get('timeout_sec', timeout_sec)
            if isinstance(requested,bool) or not isinstance(requested,(int,float)) or not math.isfinite(requested) or requested <= 0:
                return LocalMotionOutcome(reason='local_motion_invalid_timeout')
            budget = min(float(requested), float(timeout_sec))
            if budget < .1:
                return LocalMotionOutcome(reason='local_motion_insufficient_budget',timed_out=True)
            job['parameters']['timeout_sec'] = budget
            stopping = lambda: self.should_stop() or self.cancel_requested.is_set() or cancel_check()
            if stopping():
                return LocalMotionOutcome(reason='canceled before preflight',canceled=True)
            if not self.backend.prepare_navigation():
                return LocalMotionOutcome(reason=getattr(self.backend,'last_error','') or 'local_motion_preflight_failed')
            started = time.monotonic()
            with self.command_lock:
                self.command_deadline = started+budget
                self.budget_cancel_sent = False
                self.command_start_ns = self.node.get_clock().now().nanoseconds if self.node else 0
                self.command_at = 0.0
            self.active = True
            def accepted():
                with self.command_lock:
                    self.forwarding = True
            def feedback(message):
                report = getattr(ctx, 'runtime_feedback', None)
                if callable(report):
                    f = message.feedback
                    try:
                        report(float(f.progress), unit,
                               f'local_motion:{f.state}; distance={f.distance_m:.3f}m', False)
                    except Exception:
                        # A UI/telemetry callback must not interrupt motion cleanup.
                        pass
            try:
                outcome = self.client.run(job, started+budget, stopping, accepted, feedback=feedback)
            except Exception as exc:
                self.cancel_step()
                outcome = LocalMotionOutcome(reason=str(exc), metadata={'recovery_required':True})
            with self.command_lock:
                self.forwarding = False
                self.backend.publish_velocity(TwistCommand())
            if not outcome.metadata.get('recovery_required'):
                if not self.backend.finish_navigation():
                    outcome = LocalMotionOutcome(reason=getattr(self.backend,'last_error','') or 'local_motion_chassis_stop_unconfirmed',
                                                  metadata={'recovery_required':True})
                else:
                    self.active = False
            ctx.metadata['local_motion'] = outcome.metadata
            self.last_error = outcome.reason if not outcome.success else ''
            return outcome
        finally:
            self.lock.release()
