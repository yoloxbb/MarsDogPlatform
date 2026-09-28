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
from bionic_dog_bt.constants import GOAL_CANCEL_REQUESTED, STATUS_RUNNING
from bionic_dog_bt.datatypes import ActiveBehavior, BehaviorFeedbackEvent
from bionic_dog_bt.tree_builder import build_tree

from .candidate_pool import CandidatePool
from .lifecycle import (
    cancel_on_voice_idle,
    discard_unstarted_on_voice_idle,
)


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
        self.executor = executor
        self.tree = build_tree(self.blackboard, executor)
        self._last_started_goal_id = ""

    def tick(self) -> TickOutcome:
        """Run one arbitration and behavior-tree cycle."""
        # ``active_behavior`` may be a replacement reserved before requesting
        # cancellation of the current Goal.  Do not overwrite it while the old
        # Goal still owns execution.
        pending_before = self.blackboard.active_behavior
        candidate = None
        if self.blackboard.active_behavior is None:
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
            if candidate is not None and not self._candidate_is_owned(
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

        # A pending replacement can become irrelevant while cancellation is
        # still settling.  If a condition discarded it before dispatch, free
        # only that candidate's reservation (never the old running Goal's).
        if (
            pending_before is not None
            and self.blackboard.active_behavior is None
            and (
                self.blackboard.current_behavior is None
                or self.blackboard.current_behavior.behavior_id
                != pending_before.behavior_id
            )
        ):
            self.candidate_pool.release_inflight(
                pending_before.behavior_name,
                pending_before.behavior_id,
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
            and not self._candidate_is_owned(candidate)
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

    def _candidate_is_owned(self, candidate: dict) -> bool:
        """Return whether a reservation is pending or owns the active goal."""
        pending = self.blackboard.active_behavior
        if (
            pending is not None
            and pending.behavior_id == candidate.get("candidate_id")
            and self.blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED
        ):
            return True
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
        if blackboard.goal_lifecycle == GOAL_CANCEL_REQUESTED:
            return False

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
            active.params,
            current.params,
        )
        return can_preempt

    def cancel_current_interaction(
        self,
        interaction_id: str,
        *,
        reason: str,
    ) -> bool:
        """Request cancellation of one session-owned goal.

        Ownership and the in-flight reservation remain until the real Action
        Result is observed by :meth:`tick`.
        """
        interaction_id = str(interaction_id).strip()
        blackboard = self.blackboard
        current = blackboard.current_behavior
        if (
            not interaction_id
            or current is None
            or str(current.params.get("interaction_id", "")).strip()
            != interaction_id
            or not cancel_on_voice_idle(current.params)
        ):
            return False

        if blackboard.current_goal_id:
            goal_id = blackboard.current_goal_id
            blackboard.request_cancel(reason)
            return bool(self.executor.cancel_goal(goal_id))
        return False

    def discard_pending_interaction(self, interaction_id: str) -> bool:
        """Release a session-owned replacement that has not been sent yet."""
        pending = self.blackboard.active_behavior
        if (
            pending is None
            or str(pending.params.get("interaction_id", "")).strip()
            != str(interaction_id).strip()
            or not discard_unstarted_on_voice_idle(pending.params)
        ):
            return False
        self.blackboard.active_behavior = None
        self.candidate_pool.release_inflight(
            pending.behavior_name, pending.behavior_id
        )
        return True

    def cancel_current_for_shutdown(self) -> bool:
        """Request stop for any active Goal, including behavior-scoped work."""
        blackboard = self.blackboard
        if (
            blackboard.current_status != STATUS_RUNNING
            or not blackboard.current_goal_id
        ):
            return False
        if blackboard.goal_lifecycle != GOAL_CANCEL_REQUESTED:
            blackboard.request_cancel("behavior_tree_shutdown")
        return bool(self.executor.cancel_goal(blackboard.current_goal_id))

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
