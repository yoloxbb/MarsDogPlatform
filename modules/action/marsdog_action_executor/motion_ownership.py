"""Application motion ownership and unresolved-controller admission boundary.

This owns Action's execution permission, not a device stop acknowledgement or a
ROS velocity multiplexer. Existing controllers remain responsible for proving
their terminal/stop state. External publisher exclusivity is a deployment gate.
"""
from __future__ import annotations
from dataclasses import dataclass
import threading
from typing import Iterable


@dataclass(frozen=True)
class MotionLease:
    goal_id: str
    generation: int


class MotionOwnership:
    def __init__(self):
        self._lock = threading.RLock()
        self._generation = 0
        self._lease: MotionLease | None = None
        self._stopping = False
        self._recovery: tuple[str, ...] = ()

    @property
    def current(self):
        with self._lock:
            return self._lease

    @property
    def recovery_reasons(self):
        with self._lock:
            return self._recovery

    def reserve(self, goal_id: str) -> MotionLease | None:
        if not isinstance(goal_id, str) or not goal_id:
            return None
        with self._lock:
            if self._lease is not None or self._recovery:
                return None
            self._generation += 1
            self._lease = MotionLease(goal_id, self._generation)
            self._stopping = False
            return self._lease

    def may_execute(self, lease: MotionLease) -> bool:
        with self._lock:
            return lease == self._lease and not self._stopping and not self._recovery

    def request_stop(self, goal_id: str) -> bool:
        with self._lock:
            if self._lease is None or self._lease.goal_id != goal_id:
                return False
            self._stopping = True
            return True

    def finish(self, lease: MotionLease, unresolved: Iterable[str] = ()) -> bool:
        with self._lock:
            if lease != self._lease:
                return False
            self._recovery = tuple(sorted(set(unresolved)))
            self._stopping = bool(self._recovery)
            # The application callback has ended. Recovery remains a separate
            # veto until the same controllers actually clear their interlocks.
            self._lease = None
            return not self._recovery

    def reconcile(self, unresolved: Iterable[str]) -> bool:
        with self._lock:
            if self._lease is not None:
                return False
            latched = [r for r in self._recovery if r.endswith(':operator_recovery_required')]
            self._recovery = tuple(sorted(set(unresolved) | set(latched)))
            return not self._recovery


def unresolved_controllers(controllers) -> tuple[str, ...]:
    """One registry covers all adapters, including optional local/waypoint ones.

    Accessor failures are unknown, never evidence of an idle controller.
    `active` is not universally a recovery flag; local motion is special because
    its bridge deliberately remains active until terminal AND chassis stop.
    """
    reasons = []
    for name, controller in controllers.items():
        if controller is None:
            continue
        fields = ('recovery_required', 'navigation_interlocked')
        if name == 'local_motion':
            fields += ('active',)
        try:
            for field in fields:
                if getattr(controller, field, False):
                    reasons.append(name + ':' + field)
        except Exception:
            reasons.append(name + ':state_unavailable')
    return tuple(sorted(set(reasons)))


def controllers_for_node(node):
    """Composition registry only; all admission checks use the same inventory."""
    return {name: getattr(node, attribute, None) for name, attribute in (
        ('uwb_roam', '_uwb_roam_adapter'), ('uwb_follow', '_uwb_follow_adapter'),
        ('person_approach', '_person_nav_approach_adapter'),
        ('geometry_approach', '_approach_navigation_adapter'),
        ('local_motion', '_local_motion_adapter'), ('waypoint', '_waypoint_nav_client'),
        ('mobility', '_mobility_adapter'), ('visual_approach', '_visual_target_approach_adapter'),
        ('target_approach', '_target_approach_adapter'), ('orientation', '_wake_orientation_adapter'),
    )}
