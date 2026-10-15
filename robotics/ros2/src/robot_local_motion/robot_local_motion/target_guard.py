"""Opt-in target arrival and braking checks; independent of ROS wire types."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TargetPolicy:
    enabled: bool = False
    arrival_samples: int = 5
    braking_decel: float = 0.7
    reaction_sec: float = 0.2
    position_margin: float = 0.08

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.arrival_samples) is not int or not 1 <= self.arrival_samples <= 100:
            raise ValueError('invalid strict target arrival policy')
        if any(not math.isfinite(v) or v < 0 for v in (self.braking_decel, self.reaction_sec, self.position_margin)) or self.braking_decel <= 0:
            raise ValueError('invalid target braking policy')


class ArrivalEvidence:
    def __init__(self, minimum_samples):
        self.minimum_samples = minimum_samples
        self.reset()

    def reset(self):
        self.since = self.last_sample = None
        self.count = 0

    def update(self, target, qualified, hold_sec):
        if not qualified or target is None:
            self.reset()
            return False
        sample = (target.sequence, target.received_at)
        if self.last_sample is not None and (sample[0] <= self.last_sample[0] or sample[1] <= self.last_sample[1]):
            return False
        self.last_sample = sample
        if self.since is None:
            self.since = target.received_at
        self.count += 1
        return self.count >= self.minimum_samples and target.received_at - self.since + 1e-9 >= hold_sec


def target_fresh(target, now, parameters):
    return (target is not None and 0 <= now - target.received_at <= parameters['target_max_age_sec']
            and target.confidence >= parameters['target_min_confidence'])


def target_status(pose, target, now, parameters, limits):
    if not target_fresh(target, now, parameters):
        return 'INPUT_LOST', math.inf
    x = target.x + parameters['target_offset_x_m']
    y = target.y + parameters['target_offset_y_m']
    distance = math.hypot(x - pose.x, y - pose.y)
    if distance > limits.max_goal_distance:
        return 'TARGET_OUT_OF_RANGE', distance
    if distance > parameters['desired_distance_m'] + parameters['distance_reengage_m']:
        return 'MOVING', distance
    heading = math.atan2(math.sin(math.atan2(y-pose.y, x-pose.x)-pose.yaw),
                         math.cos(math.atan2(y-pose.y, x-pose.x)-pose.yaw))
    if parameters['face_target_when_holding'] and abs(heading) > parameters['yaw_tolerance_rad']:
        return 'MOVING', distance
    return 'HOLDING', distance


def closing_speed(pose, target, linear):
    heading = math.atan2(target.y-pose.y, target.x-pose.x)-pose.yaw
    return max(0.0, linear * math.cos(heading))


def stopping_distance(speed, policy, observation_age=0.0):
    speed = max(0.0, speed)
    return speed * (policy.reaction_sec + max(0.0, observation_age)) + speed*speed/(2*policy.braking_decel) + policy.position_margin


def bounded_approach_speed(requested, current_closing_speed, distance, stand_off, minimum, policy, observation_age=0.0):
    gap = distance - stand_off
    # stand_off is the hard lower edge of the accepted distance band. Include
    # uncertainty rather than braking prematurely at the nominal setpoint.
    if stopping_distance(current_closing_speed, policy, observation_age) >= gap:
        return 0.0
    reaction = policy.reaction_sec + max(0.0, observation_age)
    available = max(0.0, gap - policy.position_margin)
    cap = math.sqrt((policy.braking_decel*reaction)**2 + 2*policy.braking_decel*available) - policy.braking_decel*reaction
    cap = min(requested, cap)
    return cap if cap >= minimum else 0.0
