"""Transport-independent behavior runtime.

This module is the application boundary between ROS2 message handling and the
pure behavior-tree framework.  It owns candidate arbitration, conversion to
the BT input model, tree ticking, and execution lifecycle observations.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.arbitration import evaluate_preemption
from bionic_dog_bt.blackboard import Blackboard
from bionic_dog_bt.constants import STATUS_RUNNING
from bionic_dog_bt.datatypes import ActiveBehavior, BehaviorFeedbackEvent
from bionic_dog_bt.tree_builder import build_tree

from .candidate_pool import CandidatePool


@dataclass(frozen=True)
class TickOutcome:
    """Observable effects produced by one runtime tick."""

    tree_status: Status
    selected_candidate: Optional[dict] = None
    started_behavior: Optional[ActiveBehavior] = None
    completed_event: Optional[BehaviorFeedbackEvent] = None


class BehaviorRuntime:
    """Coordinate candidate arbitration and behavior-tree execution.

    ROS2 adapters inject candidates into :attr:`candidate_pool` and call
    :meth:`tick`.  No ROS2 message types are referenced here, so the same
    runtime is used by standalone tests and the deployed node.
    """

    def __init__(
        self,
        executor,
        *,
        blackboard: Blackboard | None = None,
        candidate_pool: CandidatePool | None = None,
        candidate_gate: Callable[[dict], bool] | None = None,
    ):
        self.blackboard = blackboard or Blackboard()
        self.candidate_pool = candidate_pool or CandidatePool()
        self.candidate_gate = candidate_gate
        self.tree = build_tree(self.blackboard, executor)
        self._last_started_goal_id = ""

    def tick(self) -> TickOutcome:
        """Run one arbitration and behavior-tree cycle."""
        candidate = self.candidate_pool.select_best(
            self.blackboard,
            can_run=self._can_run_candidate_now,
        )
        if candidate is not None:
            self.blackboard.set_active_behavior(
                self.candidate_to_active_behavior(candidate)
            )

        # The root is intentionally reactive: every tick starts evaluation at
        # Lv0 while child nodes preserve executor state on the blackboard.
        # A selected candidate is already reserved by name.  Release that
        # reservation if tree evaluation raises before it can be dispatched.
        try:
            self.tree.reset()
            tree_status = self.tree.tick()
        except Exception:
            if candidate is not None and not self._candidate_is_running(
                candidate
            ):
                self.candidate_pool.release_inflight(
                    candidate["behavior_name"],
                    candidate.get("candidate_id"),
                )
            raise
        self.blackboard.tick_count += 1
        self.blackboard.last_tick_time = time.time()

        started = self._take_started_behavior()
        completed = self.blackboard.last_feedback_event
        self.blackboard.last_feedback_event = None

        if completed is not None:
            self.candidate_pool.release_inflight(
                completed.behavior_name,
                completed.behavior_id,
            )

        # Relevance conditions or another guard may reject a selected
        # candidate before send_goal().  It must not leave a permanent
        # reservation behind.  A successfully started candidate retains its
        # reservation until one of the terminal paths above is observed.
        if candidate is not None and (
            (
                started is None
                or started.behavior_id != candidate.get("candidate_id")
            )
            and not self._candidate_is_running(candidate)
        ):
            self.candidate_pool.release_inflight(
                candidate["behavior_name"],
                candidate.get("candidate_id"),
            )

        # A terminal event is the lifecycle boundary.  Keeping the completed
        # object in current_behavior made dashboards report "recharge" forever
        # even though the Action result and Energy settlement had completed.
        # Do not clear a replacement that was started in the same preemption
        # tick; its behavior_id differs from the completed event.
        if (
            completed is not None
            and self.blackboard.current_behavior is not None
            and self.blackboard.current_behavior.behavior_id
            == completed.behavior_id
            and self.blackboard.current_status != STATUS_RUNNING
        ):
            self.blackboard.clear_current_behavior()

        return TickOutcome(
            tree_status=tree_status,
            selected_candidate=candidate,
            started_behavior=started,
            completed_event=completed,
        )

    def _candidate_is_running(self, candidate: dict) -> bool:
        """Return whether the selected reservation owns the active goal."""
        current = self.blackboard.current_behavior
        return bool(
            current is not None
            and self.blackboard.current_status == STATUS_RUNNING
            and current.behavior_id == candidate.get("candidate_id")
        )

    def _can_run_candidate_now(self, candidate: dict) -> bool:
        """Keep blocked work queued until it can start or preempt safely."""
        if self.candidate_gate is not None and not self.candidate_gate(candidate):
            return False

        blackboard = self.blackboard
        current = blackboard.current_behavior
        if current is None or blackboard.current_status != STATUS_RUNNING:
            return True

        # CandidatePool should suppress this before injection.  Keep the guard
        # for callers that manually mutate the pool/runtime during tests.
        if candidate["behavior_name"] == current.behavior_name:
            return False

        active = self.candidate_to_active_behavior(candidate)
        can_preempt, _ = evaluate_preemption(
            active.priority_level,
            active.value,
            active.behavior_name,
            current.priority_level,
            current.value,
            current.interrupt_policy,
            blackboard.executor_feedback,
        )
        return can_preempt

    @staticmethod
    def candidate_to_active_behavior(candidate: dict) -> ActiveBehavior:
        """Convert a queued candidate without dropping lifecycle metadata."""
        return ActiveBehavior(
            behavior_id=(
                candidate.get("candidate_id")
                or f"bhv_{uuid.uuid4().hex[:12]}"
            ),
            behavior_name=candidate["behavior_name"],
            priority_level=candidate["priority_level"],
            value=candidate["value"],
            confidence=candidate.get("confidence", 0.8),
            need_type=candidate.get("need_type", "external"),
            interrupt_policy=candidate.get("interrupt_policy", "immediate"),
            timeout_sec=candidate.get("timeout_sec", 30.0),
            cooldown_sec=candidate.get("cooldown_sec", 0.0),
            params=dict(candidate.get("params", {})),
            style=(
                {"emotion": candidate.get("source_emotion", "")}
                if candidate.get("source_emotion")
                else {}
            ),
            created_at=candidate.get("created_at", time.time()),
        )

    def _take_started_behavior(self) -> Optional[ActiveBehavior]:
        blackboard = self.blackboard
        if (
            blackboard.current_behavior is None
            or blackboard.current_status != STATUS_RUNNING
            or not blackboard.current_goal_id
            or blackboard.current_goal_id == self._last_started_goal_id
        ):
            return None

        self._last_started_goal_id = blackboard.current_goal_id
        return blackboard.current_behavior
