"""Per-beacon geometry, jump gate and smoothing. No cross-ID history or business roles."""
from collections import Counter
from dataclasses import dataclass, fields
import math


@dataclass(frozen=True)
class TrackingConfig:
    min_range_m: float = 0.05
    max_range_m: float = 30.0
    stale_timeout_sec: float = 0.7
    smoothing_tau_sec: float = 0.15
    max_step_m: float = 0.25
    max_speed_mps: float = 2.0
    max_gate_dt_sec: float = 0.2
    acquire_samples: int = 3
    reacquire_samples: int = 5
    cluster_radius_m: float = 0.20
    allow_jump_reacquire: bool = False
    allow_sync_reset_after_stale: bool = True
    sync_reset_samples: int = 3

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in ('acquire_samples', 'reacquire_samples', 'sync_reset_samples'):
                minimum = 3 if f.name == 'sync_reset_samples' else 1
                if type(value) is not int or not minimum <= value <= 100:
                    raise ValueError(f'{f.name} must be an integer in [1,100]')
            elif f.name in ('allow_jump_reacquire', 'allow_sync_reset_after_stale'):
                if type(value) is not bool:
                    raise ValueError('allow_jump_reacquire must be boolean')
            elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'{f.name} must be finite and nonnegative')
        if (self.min_range_m >= self.max_range_m or self.stale_timeout_sec <= 0 or
                self.max_gate_dt_sec <= 0 or self.cluster_radius_m <= 0):
            raise ValueError('invalid range, freshness or cluster limits')


@dataclass(frozen=True)
class Observation:
    valid: bool
    x: float
    y: float
    reason: str


class BeaconTracker:
    def __init__(self, config=TrackingConfig(), angle_sign=-1.0, angle_offset_rad=0.0):
        self.config = config
        self.angle_sign, self.angle_offset_rad = angle_sign, angle_offset_rad
        self.counters = Counter()
        self.reset()

    def reset(self):
        self.last_sync = self.last_seen = self.last_accepted = None
        self.raw = self.filtered = self.cluster = None
        self.cluster_count = 0
        self.reset_sync_candidate = None
        self.reset_sync_count = 0
        self.valid = False
        self.reason = 'waiting'

    def _result(self, valid, reason):
        self.valid, self.reason = valid, reason
        if not valid:
            self.counters[reason] += 1
        x, y = self.filtered or (0.0, 0.0)
        return Observation(valid, x, y, reason)

    def _cluster(self, point):
        if self.cluster is None or math.dist(point, self.cluster) > self.config.cluster_radius_m:
            self.cluster, self.cluster_count = point, 1
        else:
            self.cluster_count += 1

    def expire(self, now):
        if self.last_seen is not None and now - self.last_seen > self.config.stale_timeout_sec:
            # Keep the sync watermark: a delayed duplicate must not revive a tag.
            self.last_seen = self.last_accepted = None
            self.raw = self.filtered = self.cluster = None
            self.cluster_count = 0
            return self._result(False, 'expired')
        return None

    def update(self, frame, now):
        self.counters['input'] += 1
        self.expire(now)
        if self.last_sync is not None:
            delta = (frame.sync_count - self.last_sync) & 0xffffffff
            if not 0 < delta < 0x80000000:
                if (delta != 0 and self.last_seen is None and
                        self.config.allow_sync_reset_after_stale):
                    # A powered-off beacon may restart its own counter. Require
                    # a stale identity and several distinct advancing samples.
                    if (self.reset_sync_candidate is None or not 0 <
                            (frame.sync_count - self.reset_sync_candidate) & 0xffffffff < 0x80000000):
                        self.reset_sync_count = 1
                    else:
                        self.reset_sync_count += 1
                    self.reset_sync_candidate = frame.sync_count
                    if self.reset_sync_count < self.config.sync_reset_samples:
                        self.counters['wire_reset_pending'] += 1
                        return None
                    self.counters['wire_clock_reset'] += 1
                else:
                    self.counters['replay_or_out_of_order'] += 1
                    return None
        self.reset_sync_candidate = None
        self.reset_sync_count = 0
        self.last_sync, self.last_seen = frame.sync_count, now
        if (not all(math.isfinite(v) for v in (frame.distance, frame.angle_deg, frame.pitch_deg)) or
                not self.config.min_range_m <= frame.distance <= self.config.max_range_m or
                not -180 <= frame.angle_deg <= 180 or not -90 <= frame.pitch_deg <= 90):
            self.cluster = None
            self.cluster_count = 0
            return self._result(False, 'invalid_geometry')
        yaw = self.angle_sign * math.radians(frame.angle_deg) + self.angle_offset_rad
        point = (frame.distance * math.cos(yaw), frame.distance * math.sin(yaw))
        if self.raw is None:
            self._cluster(point)
            if self.cluster_count < self.config.acquire_samples:
                return self._result(False, 'acquiring')
            self.raw = self.filtered = point
            self.last_accepted = now
            self.cluster = None
            self.cluster_count = 0
            self.counters['accepted'] += 1
            return self._result(True, 'acquired')
        dt = max(0.0, now - self.last_accepted)
        limit = self.config.max_step_m + self.config.max_speed_mps * min(dt, self.config.max_gate_dt_sec)
        if math.dist(point, self.raw) > limit:
            self._cluster(point)
            if (self.config.allow_jump_reacquire and
                    self.cluster_count >= self.config.reacquire_samples):
                self.raw = self.filtered = point
                self.last_accepted = now
                self.cluster = None
                self.cluster_count = 0
                self.counters['reacquired'] += 1
                self.counters['accepted'] += 1
                return self._result(True, 'reacquired')
            return self._result(False, 'jump_rejected')
        self.cluster = None
        self.cluster_count = 0
        alpha = 1.0 if self.config.smoothing_tau_sec == 0 else -math.expm1(-dt / self.config.smoothing_tau_sec)
        self.filtered = tuple(a + alpha * (b - a) for a, b in zip(self.filtered, point))
        self.raw, self.last_accepted = point, now
        self.counters['accepted'] += 1
        return self._result(True, 'tracking')
