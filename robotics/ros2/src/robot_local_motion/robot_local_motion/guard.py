"""Input age and physical stop checks shared by the ROS server and pure tests."""
import math
from .core import angle


class StampGuard:
    def __init__(self):
        self.last = {}

    def accept(self, key, stamp_ns, now_ns, max_age):
        # Reject unstamped, replayed, stale and future observations.
        if (stamp_ns <= 0 or stamp_ns <= self.last.get(key, 0) or
                not 0 <= (now_ns - stamp_ns) / 1e9 <= max_age):
            return False
        self.last[key] = stamp_ns
        return True


class ObservationOrder:
    """Revocation may reuse its original stamp, but cannot clear a newer sample."""
    def __init__(self):
        self.sequences, self.stamps = {}, {}

    def accept(self, key, sequence, stamp_ns, now_ns, valid, max_age=2.0):
        previous = self.stamps.get(key, 0)
        if (sequence <= self.sequences.get(key, 0) or stamp_ns <= 0 or stamp_ns > now_ns or
                stamp_ns < previous or (valid and (stamp_ns == previous or
                (now_ns - stamp_ns) / 1e9 > max_age))):
            return False
        self.sequences[key], self.stamps[key] = sequence, stamp_ns
        return True


class StopCheck:
    def __init__(self, hold_sec=0.4, linear=0.08, angular=0.15,
                 position=0.015, yaw=0.04):
        self.hold_sec, self.linear, self.angular = hold_sec, linear, angular
        self.position, self.yaw = position, yaw
        self.anchor = self.since = None

    def update(self, now, pose, linear, angular, fresh):
        valid = (fresh and all(math.isfinite(x) for x in (linear, angular))
                 and abs(linear) <= self.linear and abs(angular) <= self.angular)
        if not valid:
            self.since = self.anchor = None
            return False
        if self.anchor is None:
            self.anchor, self.since = pose, now
        if (math.hypot(pose.x - self.anchor.x, pose.y - self.anchor.y) > self.position
                or abs(angle(pose.yaw - self.anchor.yaw)) > self.yaw):
            self.anchor, self.since = pose, now
            return False
        return now - self.since >= self.hold_sec
