"""Movement-only dual-beacon round trip; no manipulation success is inferred."""
from dataclasses import dataclass
import math
from .uwb_protocol import canonical_id


@dataclass(frozen=True)
class RoundTripConfig:
    owner_id: str
    frisbee_id: str
    dwell_sec: float = 3.0
    approach_timeout_sec: float = 0.0
    acquire_timeout_sec: float = 20.0

    def __post_init__(self):
        owner, frisbee = canonical_id(self.owner_id), canonical_id(self.frisbee_id)
        if owner == frisbee:
            raise ValueError('owner_id and frisbee_id must be different')
        object.__setattr__(self, 'owner_id', owner)
        object.__setattr__(self, 'frisbee_id', frisbee)
        if (type(self.approach_timeout_sec) not in (int, float)
                or not math.isfinite(self.approach_timeout_sec) or self.approach_timeout_sec < 0
                or any(not math.isfinite(v) or v <= 0 for v in (self.dwell_sec, self.acquire_timeout_sec))):
            raise ValueError('approach timeout must be finite and nonnegative; other budgets must be positive')


@dataclass(frozen=True)
class MotionRequest:
    mode: str
    target_id: str = ''
    yaw_delta: float = 0.0
    timeout_sec: float = 30.0


class RoundTrip:
    TERMINAL = ('IDLE', 'DONE', 'FAILED', 'CANCELED', 'RECOVERY_REQUIRED')

    def __init__(self, config):
        self.config = config
        self.state = 'IDLE'
        self.outcome = self.message = ''
        self.pending = None
        self.cancel_requested = False
        self.stop_confirmed = False
        self.started = self.dwell_started = self.acquire_started = self.search_wait_started = 0.0
        self.search_turns = 0

    @property
    def busy(self):
        return self.state not in self.TERMINAL or self.state == 'RECOVERY_REQUIRED'

    def start(self, now):
        if self.busy:
            raise ValueError('round trip busy or recovery required')
        self.started = now
        self.outcome = self.message = ''
        self.cancel_requested = False
        self.stop_confirmed = False
        self.search_turns = 0
        self.state = 'APPROACH_FRISBEE'
        return self._request(MotionRequest('approach', self.config.frisbee_id,
                                          timeout_sec=self.config.approach_timeout_sec))

    def _request(self, request):
        if self.pending is not None:
            raise RuntimeError('previous child motion is still owned')
        self.pending = request
        self.stop_confirmed = False
        return request

    def fail(self, outcome, message, stopped):
        self.outcome, self.message, self.stop_confirmed = outcome, message, stopped
        self.state = 'FAILED' if stopped else 'RECOVERY_REQUIRED'

    def cancel(self, stopped):
        self.cancel_requested = True
        if self.state == 'RECOVERY_REQUIRED' and self.pending is None:
            return
        if self.pending is None:
            self.outcome = 'CANCELED' if stopped else 'STOP_UNCONFIRMED'
            self.stop_confirmed = stopped
            self.state = 'CANCELED' if stopped else 'RECOVERY_REQUIRED'

    def motion_done(self, now, outcome, stop_confirmed, message=''):
        if self.pending is None:
            raise RuntimeError('unexpected child motion result')
        request = self.pending
        self.pending = None
        self.stop_confirmed = stop_confirmed
        if not stop_confirmed:
            self.fail('STOP_UNCONFIRMED', message or outcome, False)
            return
        if self.cancel_requested:
            self.state, self.outcome = 'CANCELED', 'CANCELED'
            return
        if outcome != 'SUCCEEDED':
            self.fail(outcome, message, True)
            return
        if self.state == 'APPROACH_FRISBEE':
            self.state, self.dwell_started = 'DWELL', now
        elif self.state == 'RETURN_OWNER':
            self.state, self.outcome = 'DONE', 'SUCCEEDED'
            self.message = 'movement round trip completed; no pickup or carry claim'
        elif request.mode == 'turn' and self.state == 'ACQUIRE_OWNER':
            self.search_wait_started = now
        else:
            self.fail('CONFIG_ERROR', 'unexpected child result stage', True)

    def tick(self, now, stationary, owner_ready):
        if self.pending is not None or self.state in self.TERMINAL:
            return None
        if not stationary:
            self.fail('STOP_UNCONFIRMED', 'stationary evidence lost between motion stages', False)
            return None
        if self.state == 'DWELL' and now-self.dwell_started >= self.config.dwell_sec:
            self.state = 'ACQUIRE_OWNER'
            self.acquire_started = self.search_wait_started = now
        if self.state == 'ACQUIRE_OWNER':
            if now-self.acquire_started >= self.config.acquire_timeout_sec:
                self.fail('INPUT_LOST', 'owner reacquisition budget exhausted', True)
            elif owner_ready:
                self.state = 'RETURN_OWNER'
                return self._request(MotionRequest('approach', self.config.owner_id,
                                                  timeout_sec=self.config.approach_timeout_sec))
            elif now-self.search_wait_started >= 0.6:
                if self.search_turns >= 4:
                    self.fail('INPUT_LOST', 'owner not visible after four search turns', True)
                else:
                    self.search_turns += 1
                    return self._request(MotionRequest('turn', yaw_delta=math.pi/2,
                        timeout_sec=max(0.1, self.config.acquire_timeout_sec-(now-self.acquire_started))))
        return None
