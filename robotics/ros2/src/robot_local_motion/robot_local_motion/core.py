"""Deterministic task control. Collision planning remains in the existing MPPI."""

from dataclasses import dataclass
import json
import math
import random
from .target_guard import ArrivalEvidence, TargetPolicy, bounded_approach_speed, closing_speed


MODES = ('move', 'approach', 'follow', 'orbit', 'explore', 'turn')

MODE_FIELDS = {
    'move': {'position_tolerance_m', 'require_final_yaw'},
    'approach': {'desired_distance_m', 'distance_deadband_m', 'distance_reengage_m',
                 'face_target_when_holding', 'lock_target_position'},
    'follow': {'desired_distance_m', 'distance_deadband_m', 'distance_reengage_m',
               'face_target_when_holding', 'lock_target_position', 'complete_when_holding', 'duration_sec'},
    'orbit': {'orbit_radius_m', 'orbit_turns', 'orbit_direction', 'orbit_lead_angle_rad',
              'orbit_capture_tolerance_m', 'lock_orbit_center', 'lock_target_position'},
    'explore': {'position_tolerance_m', 'duration_sec', 'min_radius_m', 'max_radius_m',
                'goal_obstacle_clearance_m', 'goal_pause_sec', 'sector_center_rad',
                'sector_width_rad', 'random_seed', 'goal_count', 'max_sample_attempts', 'max_retries'},
    'turn': set(),
}
for _mode in ('move', 'approach', 'follow', 'orbit', 'explore'):
    MODE_FIELDS[_mode].update({'linear_gain', 'heading_slowdown_start', 'heading_stop_angle'})
for _mode in ('move', 'approach', 'explore'):
    MODE_FIELDS[_mode].update({'progress_window_sec', 'progress_distance_m'})
TARGET_FIELDS = {'target_offset_x_m', 'target_offset_y_m', 'target_max_age_sec',
                 'lost_target_timeout_sec', 'target_min_confidence', 'lost_target_policy'}
SPECIFIC_FIELDS = set().union(*MODE_FIELDS.values())


@dataclass(frozen=True)
class Limits:
    max_linear_speed: float = 0.8
    min_linear_speed: float = 0.25
    max_angular_speed: float = 1.5
    min_stand_off_distance: float = 0.5
    max_goal_distance: float = 3.0
    max_task_timeout: float = 3600.0
    robot_radius: float = 0.42


# default, lower bound, upper bound. Every field is consumed by control or ROS.
NUMERIC = {
    'timeout_sec': (60.0, 0.1, 3600.0),
    'duration_sec': (0.0, 0.0, 3600.0),
    'max_linear_speed': (0.5, 0.0, 1.0),
    'max_angular_speed': (1.2, 0.01, 1.5),
    'linear_gain': (0.6, 0.01, 5.0),
    'angular_gain': (1.0, 0.01, 5.0),
    'heading_slowdown_start': (0.3, 0.0, math.pi),
    'heading_stop_angle': (1.4, 0.01, math.pi),
    'position_tolerance_m': (0.15, 0.02, 1.0),
    'yaw_tolerance_rad': (0.08, 0.01, 1.0),
    'arrival_hold_sec': (0.4, 0.0, 10.0),
    'desired_distance_m': (1.0, 0.5, 3.0),
    'distance_deadband_m': (0.08, 0.0, 0.5),
    'distance_reengage_m': (0.15, 0.0, 1.0),
    'target_offset_x_m': (0.0, -3.0, 3.0),
    'target_offset_y_m': (0.0, -3.0, 3.0),
    'target_max_age_sec': (0.5, 0.02, 2.0),
    'lost_target_timeout_sec': (3.0, 0.0, 30.0),
    'target_min_confidence': (0.0, 0.0, 1.0),
    'startup_timeout_sec': (4.0, 0.1, 30.0),
    'input_recovery_timeout_sec': (3.0, 0.0, 30.0),
    'blocked_timeout_sec': (3.0, 0.1, 30.0),
    'progress_window_sec': (5.0, 0.5, 60.0),
    'progress_distance_m': (0.1, 0.01, 1.0),
    'max_distance_travelled_m': (0.0, 0.0, 100.0),
    'orbit_radius_m': (1.0, 0.5, 3.0),
    'orbit_turns': (1.0, 0.05, 10.0),
    'orbit_lead_angle_rad': (0.35, 0.05, 1.0),
    'orbit_capture_tolerance_m': (0.1, 0.02, 0.5),
    'min_radius_m': (0.5, 0.0, 3.0),
    'max_radius_m': (2.0, 0.1, 3.0),
    'goal_obstacle_clearance_m': (0.7, 0.0, 2.0),
    'goal_pause_sec': (0.0, 0.0, 30.0),
    'sector_center_rad': (0.0, -math.pi, math.pi),
    'sector_width_rad': (2 * math.pi, 0.05, 2 * math.pi),
    'boundary_radius_m': (0.0, 0.0, 6.0),
    'boundary_prediction_sec': (1.0, 0.1, 3.0),
}
INTEGER = {
    'random_seed': (0, 0, 2**32 - 1),
    'goal_count': (1, 1, 100),
    'max_sample_attempts': (50, 1, 100),
    'max_retries': (2, 0, 20),
    'orbit_direction': (1, -1, 1),
}
BOOLEAN = {
    'require_final_yaw': False,
    'face_target_when_holding': True,
    'complete_when_holding': False,
    'lock_target_position': False,
    'lock_orbit_center': False,
}
ENUMS = {
    'lost_target_policy': ('pause', ('pause', 'abort')),
    'blocked_policy': ('abort', ('abort', 'wait', 'resample')),
    'center_mode': ('initial_pose', ('initial_pose', 'goal', 'target')),
    'sector_reference': ('initial_heading', ('initial_heading', 'odom')),
}

# Opt-in planner fields. Geometry, minimum executable speeds, sensor freshness,
# emergency thresholds and hard deployment limits cannot be weakened per goal.
PLANNER_FIELDS = {
    'max_linear_accel': (0.01, 0.5),
    'max_linear_decel': (0.01, 0.7),
    'max_angular_accel': (0.01, 1.5),
    'prediction_time': (0.5, 3.0),
    'mppi_batch_size': (8, 256),
    'mppi_iteration_count': (1, 5),
    'mppi_temperature': (0.001, 10.0),
    'mppi_linear_noise_std': (0.0, 0.5),
    'mppi_angular_noise_std': (0.0, 1.5),
    'mppi_noise_correlation': (0.0, 0.99),
    'mppi_random_seed': (0, 2**31 - 1),
    'min_avoidance_angular_speed': (0.0, 1.5),
    'max_avoidance_angular_speed': (0.01, 1.5),
    'obstacle_influence_distance': (0.1, 2.0),
    'minimum_safe_clearance': (0.05, 1.0),
    'minimum_ttc': (0.3, 3.0),
    'weight_follow_linear': (0.0, 100.0),
    'weight_follow_angular': (0.0, 100.0),
    'weight_smooth_linear': (0.0, 100.0),
    'weight_smooth_angular': (0.0, 100.0),
    'weight_obstacle': (0.0, 100.0),
    'weight_progress': (0.0, 100.0),
    'avoidance_direction_hold_sec': (0.0, 3.0),
    'enable_emergency_reverse': None,
}
PLANNER_INTS = {'mppi_batch_size', 'mppi_iteration_count', 'mppi_random_seed'}


def parameter_schema():
    return {
        'schema_version': 1, 'modes': list(MODES),
        'mode_fields': {k: sorted(v) for k, v in MODE_FIELDS.items()},
        'target_fields': sorted(TARGET_FIELDS),
        'numeric': {k: {'default': v[0], 'min': v[1], 'max': v[2]}
                    for k, v in NUMERIC.items()},
        'integer': {k: {'default': v[0], 'min': v[1], 'max': v[2]}
                    for k, v in INTEGER.items()},
        'boolean': BOOLEAN, 'enum': {k: {'default': v[0], 'choices': v[1]}
                                   for k, v in ENUMS.items()},
        'planner': PLANNER_FIELDS,
        'deployment_exceptions': {'timeout_sec': {'disabled_value': 0.0,
            'modes': ['approach'], 'requires': 'allow_unbounded_approach', 'default_allowed': False}},
    }


def parse_parameters(text, mode, limits=Limits(), *, allow_unbounded_approach=False):
    if mode not in MODES:
        raise ValueError('unknown mode')
    if len(text) > 16384:
        raise ValueError('parameter JSON exceeds 16 KiB')
    def unique(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError('duplicate parameter: ' + k)
            d[k] = v
        return d
    try:
        raw = json.loads(text or '{}', object_pairs_hook=unique,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except RecursionError as exc:
        raise ValueError('parameter JSON nesting is too deep') from exc
    if (not isinstance(raw, dict) or type(raw.get('schema_version', 1)) is not int
            or raw.get('schema_version', 1) != 1):
        raise ValueError('parameters must be a schema_version=1 object')
    allowed = set(NUMERIC) | set(INTEGER) | set(BOOLEAN) | set(ENUMS) | {'planner', 'schema_version'}
    if set(raw) - allowed:
        raise ValueError('unknown parameters: ' + ', '.join(sorted(set(raw) - allowed)))
    invalid_mode_fields = (set(raw) & SPECIFIC_FIELDS) - MODE_FIELDS[mode]
    if invalid_mode_fields:
        raise ValueError('parameters do not apply to ' + mode + ': ' + ', '.join(sorted(invalid_mode_fields)))
    target_mode = mode in ('approach', 'follow', 'orbit') or (mode == 'explore' and raw.get('center_mode') == 'target')
    if not target_mode and set(raw) & TARGET_FIELDS:
        raise ValueError('target parameters require a target-consuming mode')
    if raw.get('center_mode') == 'target' and not target_mode:
        raise ValueError('target boundary center requires target observations')
    if 'sector_reference' in raw and mode != 'explore':
        raise ValueError('sector_reference applies only to explore')
    p = {}
    for key, (default, low, high) in {**NUMERIC, **INTEGER}.items():
        value = raw.get(key, default)
        expected = int if key in INTEGER else (int, float)
        # Zero disables only an explicitly permitted approach deadline. All
        # ordinary modes/deployments retain their existing positive budgets.
        if key == 'timeout_sec' and mode == 'approach' and allow_unbounded_approach and value == 0:
            low = 0.0
        if (isinstance(value, bool) or not isinstance(value, expected) or
                not low <= value <= high or not math.isfinite(value)):
            raise ValueError(f'{key} must be within [{low}, {high}]')
        p[key] = value
    for key, default in BOOLEAN.items():
        p[key] = raw.get(key, default)
        if not isinstance(p[key], bool):
            raise ValueError(key + ' must be boolean')
    for key, (default, choices) in ENUMS.items():
        p[key] = raw.get(key, default)
        if p[key] not in choices:
            raise ValueError(key + ' has an invalid choice')
    if not 0 < p['max_linear_speed'] <= limits.max_linear_speed:
        raise ValueError('max_linear_speed exceeds deployment limit or is zero')
    if p['max_linear_speed'] < limits.min_linear_speed:
        raise ValueError('requested speed is below the executable chassis minimum')
    if p['max_angular_speed'] > limits.max_angular_speed:
        raise ValueError('max_angular_speed exceeds deployment limit')
    if p['timeout_sec'] > limits.max_task_timeout or p['duration_sec'] > p['timeout_sec']:
        raise ValueError('duration/timeout exceeds task or deployment budget')
    if p['duration_sec'] and mode not in ('follow', 'explore'):
        raise ValueError('duration_sec completes only follow or explore; other modes require arrival')
    if p['heading_slowdown_start'] >= p['heading_stop_angle']:
        raise ValueError('heading thresholds must have increasing order')
    if p['distance_reengage_m'] < p['distance_deadband_m']:
        raise ValueError('distance_reengage_m must be >= distance_deadband_m')
    if mode in ('approach', 'follow') and p['desired_distance_m'] < limits.min_stand_off_distance:
        raise ValueError('desired_distance_m violates the minimum approach distance')
    if p['orbit_direction'] not in (-1, 1):
        raise ValueError('orbit_direction must be -1 or +1')
    if p['min_radius_m'] >= p['max_radius_m']:
        raise ValueError('min_radius_m must be < max_radius_m')
    if mode == 'explore' and p['max_radius_m'] > limits.max_goal_distance:
        raise ValueError('exploration radius exceeds local observation limit')
    if mode == 'orbit' and p['orbit_radius_m'] > limits.max_goal_distance:
        raise ValueError('orbit radius exceeds local observation limit')
    if mode == 'orbit' and p['orbit_radius_m'] < limits.min_stand_off_distance:
        raise ValueError('orbit radius violates deployment stand-off distance')
    if p['boundary_radius_m'] and p['boundary_radius_m'] <= limits.robot_radius:
        raise ValueError('boundary must contain the chassis footprint')
    if mode == 'explore' and p['boundary_radius_m'] and (
            p['max_radius_m'] + limits.robot_radius > p['boundary_radius_m']):
        raise ValueError('exploration targets plus footprint exceed boundary')
    if p['blocked_policy'] == 'resample' and mode != 'explore':
        raise ValueError('resample is available only for exploration')
    planner = raw.get('planner', {})
    if not isinstance(planner, dict) or set(planner) - set(PLANNER_FIELDS):
        raise ValueError('unknown planner parameters')
    for key, value in planner.items():
        bounds = PLANNER_FIELDS[key]
        if bounds is None:
            if not isinstance(value, bool):
                raise ValueError(key + ' must be boolean')
        elif (isinstance(value, bool) or not isinstance(value, int if key in PLANNER_INTS else (int, float))
              or not bounds[0] <= value <= bounds[1] or not math.isfinite(value)):
            raise ValueError('invalid planner parameter: ' + key)
    p['planner'] = dict(planner)
    p['schema_version'] = 1
    return p


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    yaw: float = 0.0


@dataclass(frozen=True)
class Target:
    x: float
    y: float
    received_at: float
    confidence: float = 1.0
    sequence: int = 0


@dataclass
class Step:
    linear: float = 0.0
    angular: float = 0.0
    state: str = 'STARTING'
    outcome: str = ''
    distance: float = 0.0
    progress: float = 0.0


def angle(value):
    return math.atan2(math.sin(value), math.cos(value))


class MotionTask:
    """One task owns its settings; success here still requires ROS stop confirmation."""

    def __init__(self, mode, parameters, initial_pose, goal_pose, now, limits=Limits(), target_policy=TargetPolicy(), follow_control=None):
        self.mode, self.p, self.limits = mode, parameters, limits
        self.target_policy = target_policy
        self.follow_control = follow_control
        self.actual_angular_velocity = 0.0
        self.arrival = ArrivalEvidence(target_policy.arrival_samples)
        self.progress_pose = initial_pose
        self.progress_target = None
        self.started = now
        self.initial = self.last_pose = initial_pose
        self.goal = goal_pose
        if (mode == 'move' or parameters['center_mode'] == 'goal') and math.hypot(goal_pose.x - initial_pose.x,
                                        goal_pose.y - initial_pose.y) > limits.max_goal_distance:
            raise ValueError('fixed target exceeds local observation limit')
        self.holding_since = self.lost_since = self.blocked_since = None
        self.progress_time = now
        self.best_distance = math.inf
        self.path_length = 0.0
        self.holding = False
        self.locked_target = None
        self.orbit_center = None
        self.orbit_previous_angle = None
        self.orbit_angle = 0.0
        self.explore_goal = None
        self.completed_goals = self.retries = 0
        self.pause_until = 0.0
        self.center = initial_pose
        if self.p['center_mode'] == 'goal':
            self.center = goal_pose
        self.random = random.Random(self.p['random_seed'] or None)

    def _drive(self, pose, x, y, stand_off=0.0):
        distance = math.hypot(x - pose.x, y - pose.y)
        heading = angle(math.atan2(y - pose.y, x - pose.x) - pose.yaw)
        if self.follow_control is not None and self.mode == 'approach':
            linear, angular = self.follow_control.command(
                distance*math.cos(heading), distance*math.sin(heading), self.actual_angular_velocity)
            if stand_off == distance:
                linear = 0.0
                if abs(heading) <= self.p['yaw_tolerance_rad']:
                    angular = 0.0
            return Step(linear, angular, 'MOVING', distance=distance)
        linear = min(self.p['max_linear_speed'], max(0.0, self.p['linear_gain'] * (distance - stand_off)))
        if abs(heading) >= self.p['heading_stop_angle']:
            linear = 0.0
        elif abs(heading) > self.p['heading_slowdown_start']:
            linear *= ((self.p['heading_stop_angle'] - abs(heading)) /
                       (self.p['heading_stop_angle'] - self.p['heading_slowdown_start']))
        if 0 < linear < self.limits.min_linear_speed:
            linear = self.limits.min_linear_speed
        angular = max(-self.p['max_angular_speed'], min(
            self.p['max_angular_speed'], self.p['angular_gain'] * heading))
        if abs(heading) <= self.p['yaw_tolerance_rad']:
            angular = 0.0
        return Step(linear, angular, 'MOVING', distance=distance)

    def _arrived(self, now, distance=0.0):
        if self.holding_since is None:
            self.holding_since = now
        outcome = 'SUCCEEDED' if now - self.holding_since >= self.p['arrival_hold_sec'] else ''
        return Step(state='HOLDING', outcome=outcome, distance=distance)

    def _sample(self, center, obstacles, pose):
        for _ in range(self.p['max_sample_attempts']):
            a = (self.initial.yaw if self.p['sector_reference'] == 'initial_heading' else 0.0) + self.p['sector_center_rad'] + self.random.uniform(
                -self.p['sector_width_rad'] / 2, self.p['sector_width_rad'] / 2)
            radius = math.sqrt(self.random.uniform(self.p['min_radius_m']**2, self.p['max_radius_m']**2))
            x, y = center.x + radius * math.cos(a), center.y + radius * math.sin(a)
            if math.hypot(x - pose.x, y - pose.y) > self.limits.max_goal_distance:
                continue
            clearance = max(self.p['goal_obstacle_clearance_m'], self.limits.robot_radius)
            if all(math.hypot(x - ox, y - oy) >= clearance for ox, oy in obstacles):
                return Pose(x, y)
        return None

    def tick(self, now, pose, target=None, obstacles=(), blocked=False, linear_velocity=0.0, angular_velocity=0.0):
        self.actual_angular_velocity = angular_velocity
        self.path_length += math.hypot(pose.x - self.last_pose.x, pose.y - self.last_pose.y)
        self.last_pose = pose
        elapsed = now - self.started
        if self.p['timeout_sec'] > 0 and elapsed >= self.p['timeout_sec']:
            return Step(outcome='TIMEOUT')
        if self.p['max_distance_travelled_m'] and self.path_length >= self.p['max_distance_travelled_m']:
            return Step(outcome='DISTANCE_LIMIT')
        needs_target = self.mode in ('approach', 'follow', 'orbit') or (
            self.mode == 'explore' and self.p['center_mode'] == 'target')
        if needs_target:
            valid = (target is not None and 0 <= now - target.received_at <= self.p['target_max_age_sec']
                     and target.confidence >= self.p['target_min_confidence'])
            if not valid:
                if self.follow_control is not None:
                    self.follow_control.reset()
                self.holding_since = None
                self.arrival.reset()
                if self.lost_since is None:
                    self.lost_since = now
                abort = self.p['lost_target_policy'] == 'abort' or now - self.lost_since >= self.p['lost_target_timeout_sec']
                return Step(state='TARGET_LOST', outcome='INPUT_LOST' if abort else '')
            self.lost_since = None
            if self.p['lock_target_position'] and self.locked_target is not None:
                tx, ty = self.locked_target
            else:
                tx = target.x + self.p['target_offset_x_m']
                ty = target.y + self.p['target_offset_y_m']
                self.locked_target = tx, ty
            if math.hypot(tx - pose.x, ty - pose.y) > self.limits.max_goal_distance:
                return Step(state='TARGET_OUT_OF_RANGE', outcome='TARGET_OUT_OF_RANGE')
            if self.p['center_mode'] == 'target':
                self.center = Pose(tx, ty)
        if blocked:
            self.holding_since = None
            self.arrival.reset()
            if self.blocked_since is None:
                self.blocked_since = now
            if now - self.blocked_since >= self.p['blocked_timeout_sec']:
                if self.p['blocked_policy'] == 'resample' and self.retries < self.p['max_retries']:
                    self.explore_goal = None
                    self.retries += 1
                    self.blocked_since = None
                    self.best_distance = math.inf
                    self.progress_time = now
                elif self.p['blocked_policy'] != 'wait':
                    return Step(state='BLOCKED', outcome='BLOCKED')
            return Step(state='BLOCKED')
        self.blocked_since = None
        if self.p['duration_sec'] and elapsed >= self.p['duration_sec']:
            return Step(outcome='SUCCEEDED')
        if self.mode == 'turn':
            error = angle(self.goal.yaw - pose.yaw)
            if abs(error) <= self.p['yaw_tolerance_rad']:
                return self._arrived(now)
            self.holding_since = None
            return Step(angular=max(-self.p['max_angular_speed'], min(
                self.p['max_angular_speed'], self.p['angular_gain'] * error)), state='TURNING')
        if self.mode in ('approach', 'follow'):
            distance = math.hypot(tx - pose.x, ty - pose.y)
            strict = self.target_policy.enabled and self.mode == 'approach'
            threshold = self.p['desired_distance_m'] + (
                self.p['distance_reengage_m'] if self.holding else self.p['distance_deadband_m'])
            if distance <= threshold:
                self.holding = True
                result = self._arrived(now, distance)
                if self.mode == 'follow' and not self.p['complete_when_holding']:
                    result.outcome = ''
                if self.p['face_target_when_holding']:
                    turn = self._drive(pose, tx, ty, distance)
                    result.angular = turn.angular
                    if result.angular:
                        self.holding_since = None
                        result.outcome = ''
                if strict:
                    ready = self.arrival.update(target, not result.angular, self.p['arrival_hold_sec'])
                    result.outcome = 'SUCCEEDED' if ready else ''
                return result
            self.holding = False
            self.holding_since = None
            self.arrival.reset()
            result = self._drive(pose, tx, ty, self.p['desired_distance_m'])
            if strict and result.linear:
                result.linear = bounded_approach_speed(result.linear, closing_speed(pose, target, linear_velocity),
                    distance, max(self.limits.min_stand_off_distance, self.p['desired_distance_m']-self.p['distance_deadband_m']), self.limits.min_linear_speed,
                    self.target_policy, now-target.received_at)
                if not result.linear:
                    result.state = 'BRAKING'
        elif self.mode == 'orbit':
            if self.orbit_center is None or not self.p['lock_orbit_center']:
                self.orbit_center = Pose(tx, ty)
            cx, cy = self.orbit_center.x, self.orbit_center.y
            theta = math.atan2(pose.y - cy, pose.x - cx)
            radius = math.hypot(pose.x - cx, pose.y - cy)
            on_ring = abs(radius - self.p['orbit_radius_m']) <= self.p['orbit_capture_tolerance_m']
            if (on_ring and self.orbit_previous_angle is not None and
                    math.hypot(pose.x - self.previous_orbit_pose.x,
                               pose.y - self.previous_orbit_pose.y) > 0.001):
                delta = angle(theta - self.orbit_previous_angle) * self.p['orbit_direction']
                self.orbit_angle = max(0.0, self.orbit_angle + delta)
            self.orbit_previous_angle = theta if on_ring else None
            self.previous_orbit_pose = pose
            if self.orbit_angle >= self.p['orbit_turns'] * 2 * math.pi:
                return self._arrived(now, radius)
            reference = theta + (self.p['orbit_direction'] * self.p['orbit_lead_angle_rad'] if on_ring else 0.0)
            result = self._drive(pose, cx + self.p['orbit_radius_m'] * math.cos(reference),
                                 cy + self.p['orbit_radius_m'] * math.sin(reference))
            result.state = 'ORBITING' if on_ring else 'APPROACHING_ORBIT'
            result.progress = self.orbit_angle / (self.p['orbit_turns'] * 2 * math.pi)
        else:
            if self.mode == 'explore':
                if now < self.pause_until:
                    return Step(state='DWELLING')
                if self.explore_goal is None:
                    self.explore_goal = self._sample(self.center, obstacles, pose)
                    self.best_distance, self.progress_time = math.inf, now
                    if self.explore_goal is None:
                        return Step(outcome='NO_VALID_GOAL')
                goal = self.explore_goal
            else:
                goal = self.goal
            result = self._drive(pose, goal.x, goal.y)
            if result.distance <= self.p['position_tolerance_m']:
                if self.p['require_final_yaw'] and self.mode == 'move':
                    error = angle(goal.yaw - pose.yaw)
                    if abs(error) > self.p['yaw_tolerance_rad']:
                        self.holding_since = None
                        return Step(angular=max(-self.p['max_angular_speed'], min(
                            self.p['max_angular_speed'], self.p['angular_gain'] * error)), state='ALIGNING')
                arrived = self._arrived(now, result.distance)
                if self.mode == 'explore' and arrived.outcome:
                    self.completed_goals += 1
                    if self.completed_goals < self.p['goal_count']:
                        self.explore_goal = None
                        self.holding_since = None
                        self.pause_until = now + self.p['goal_pause_sec']
                        arrived.outcome = ''
                return arrived
            self.holding_since = None
        # A continuous follow target may move, so it is governed by task duration
        # and blocked diagnostics rather than static-goal progress expiry.
        if self.mode in ('move', 'approach', 'explore'):
            moved_towards_target = False
            turned_towards_target = False
            if self.target_policy.enabled and self.mode == 'approach':
                dx, dy = tx-self.progress_pose.x, ty-self.progress_pose.y
                length = math.hypot(dx, dy)
                moved_towards_target = length > 1e-6 and (
                    (pose.x-self.progress_pose.x)*dx+(pose.y-self.progress_pose.y)*dy)/length >= self.p['progress_distance_m']
                if self.progress_target is not None:
                    px, py = self.progress_target
                    before = abs(angle(math.atan2(py-self.progress_pose.y, px-self.progress_pose.x)-self.progress_pose.yaw))
                    after = abs(angle(math.atan2(py-pose.y, px-pose.x)-pose.yaw))
                    turned_towards_target = (abs(angle(pose.yaw-self.progress_pose.yaw)) >= self.p['yaw_tolerance_rad']
                        and before-after >= max(0.1, self.p['yaw_tolerance_rad']))
            if self.best_distance - result.distance >= self.p['progress_distance_m'] or moved_towards_target or turned_towards_target:
                self.best_distance, self.progress_time = result.distance, now
                self.progress_pose = pose
                if self.target_policy.enabled and self.mode == 'approach':self.progress_target = (tx, ty)
            elif now - self.progress_time >= self.p['progress_window_sec']:
                if self.mode == 'explore' and self.p['blocked_policy'] == 'resample' and self.retries < self.p['max_retries']:
                    self.explore_goal = None
                    self.retries += 1
                    self.best_distance, self.progress_time = math.inf, now
                    return Step(state='RESELECTING')
                if self.p['blocked_policy'] != 'wait':
                    return Step(outcome='NO_PROGRESS')
        return result

    def boundary_allows(self, pose, linear, angular):
        radius = self.p['boundary_radius_m']
        if not radius:
            return True
        allowed = radius - self.limits.robot_radius
        start = math.hypot(pose.x - self.center.x, pose.y - self.center.y)
        x, y, yaw = pose.x, pose.y, pose.yaw
        for _ in range(math.ceil(self.p['boundary_prediction_sec'] / 0.05)):
            x += linear * math.cos(yaw) * 0.05
            y += linear * math.sin(yaw) * 0.05
            yaw += angular * 0.05
            distance = math.hypot(x - self.center.x, y - self.center.y)
            if distance > allowed and (start <= allowed or distance > start + 1e-6):
                return False
        return True
