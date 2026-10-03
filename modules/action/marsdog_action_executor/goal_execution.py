"""Execution orchestration through existing executor, adapter and goal-handle ports.

Owns callback sequencing, not ROS construction or controller algorithms. Locks,
terminal result publication and resource cleanup retain their original ordering.
"""
from __future__ import annotations
import json
from marsdog_observability import wrap_context
import threading
import time
from .execution_context import ExecutionContext
from .models import ExecutionResult
from .stationary_policy import INPLACE_WITH_HUMAN_BEHAVIORS, validate_inplace_plan
from .adapters.uwb_follow_action_adapter import UwbFollowActionAdapter
from .adapters.waypoint_nav_adapter import WaypointNavStatus
from .goal_contract import _normalise_goal_timeout, _outer_runtime_deadline, _navigation_cancel_won


async def on_execute(self, goal_handle, *, make_result):
    """Execute behavior; emergency stop bypasses serialization.

    When preempting a lower-priority goal, waits for the configured
    lock budget (8s by default) for
    the running goal to release the lock after receiving the
    cancel signal.
    """
    request = goal_handle.request
    if request.behavior_name == "emergency_stop":
        return self._execute_emergency_stop(goal_handle)

    if not self._behavior_execution_lock.acquire(blocking=False):
        # Preemption path: wait for old goal to finish cancelling
        lock_wait_sec = float(
            self.get_parameter(
                "navigation_preempt_lock_wait_sec"
            ).value
        )
        deadline = time.monotonic() + lock_wait_sec
        acquired = False
        while time.monotonic() < deadline:
            if self._behavior_execution_lock.acquire(blocking=False):
                acquired = True
                break
            time.sleep(0.05)
        if not acquired:
            goal_handle.abort()
            return make_result(
                request.goal_id,
                getattr(request, "behavior_id", request.goal_id),
                request.behavior_name,
                status="FAILED",
                result="failed",
                reason=(
                    "executor_busy: previous task has no confirmed "
                    f"terminal within {lock_wait_sec:.1f}s"
                ),
                reward=-1.0,
            )
    try:
        self._current_priority = int(
            getattr(request, "priority_level", 0)
        )
        return await self._execute_behavior(goal_handle)
    finally:
        self._behavior_sounds.stop()
        if request.behavior_name in INPLACE_WITH_HUMAN_BEHAVIORS:
            self._stationary_expression_adapter.cancel_step()
            if self._chassis_backend is not None:
                self._chassis_backend.hold_position()
        self._behavior_execution_lock.release()
        with self._goal_reservation_lock:
            if self._reserved_goal_id == str(request.goal_id):
                self._reserved_goal_id = None
        with self._lease_lock:
            self._lease_seen.pop((
                str(request.goal_id),
                str(getattr(request, "behavior_id", "") or request.goal_id),
            ), None)


async def execute_behavior(self, goal_handle, *, make_result):
    """Async execution callback — v2 pipeline."""
    goal_req = goal_handle.request
    gid = goal_req.goal_id
    requested_name = goal_req.behavior_name
    behavior_id = getattr(goal_req, "behavior_id", gid)
    runtime_timeout_sec = _normalise_goal_timeout(
        getattr(goal_req, "timeout_sec", 60.0)
    )
    behavior_started_wall = time.time()
    behavior_started_monotonic = time.monotonic()

    self.get_logger().info(
        f"[{gid}] Executing: {requested_name}"
    )

    # ── Step 1: Parse ──────────────────────────────────────────
    ctx = self._goal_parser.parse_from_ros_goal(goal_req)
    ctx.runtime_deadline_monotonic = _outer_runtime_deadline(
        behavior_started_monotonic, runtime_timeout_sec,
    )
    if not ctx.is_valid:
        self.get_logger().error(
            f"[{gid}] Invalid params: {ctx.error_reason}"
        )
        goal_handle.abort()
        return make_result(
            gid, behavior_id, requested_name,
            status="FAILED", result="failed",
            reason=ctx.error_reason or "invalid_params",
            reward=-1.0,
        )

    # ── Step 2: Validate the exact behavior-tree name ───────────
    ctx = self._behavior_resolver.resolve(ctx)
    if not ctx.is_valid:
        self.get_logger().error(
            f"[{gid}] Unresolvable behavior: {ctx.error_reason}"
        )
        goal_handle.abort()
        return make_result(
            gid, behavior_id, requested_name,
            resolved_name=ctx.resolved_behavior_name,
            status="FAILED", result="failed",
            reason=ctx.error_reason or "unsupported_behavior",
            reward=-1.0,
        )

    canonical = ctx.resolved_behavior_name
    self.get_logger().info(f"[{gid}] Validated: {canonical}")
    ctx.runtime_feedback = lambda progress, action, message, safe: (
        self._publish_feedback(
            goal_handle,
            gid,
            behavior_id,
            canonical,
            progress,
            str(ctx.current_stage or "target_approach"),
            action,
            safe,
            message,
        )
    )

    # ── Step 3: Get template & stages ──────────────────────────
    template = self._config.get_behavior_template(canonical)
    if template is None:
        self.get_logger().error(
            f"[{gid}] No template for: {canonical}"
        )
        goal_handle.abort()
        return make_result(
            gid, behavior_id, requested_name,
            resolved_name=canonical,
            status="FAILED", result="failed",
            reason=f"no_template: {canonical}",
            reward=-1.0,
        )

    stages = template.get("stages", [])
    if not stages:
        self.get_logger().error(
            f"[{gid}] Behavior {canonical} has no stages"
        )
        goal_handle.abort()
        return make_result(
            gid, behavior_id, requested_name,
            resolved_name=canonical,
            status="FAILED", result="failed",
            reason=f"no_stages: {canonical}",
            reward=-1.0,
        )

    if canonical in ("follow_owner", "play_alone") and runtime_timeout_sec <= 0:
        return self._execute_long_behavior(
            goal_handle, ctx, stages, behavior_started_wall,
        )

    success_condition = template.get("success_condition")
    # Dict format → extract type field (e.g. {type: action_completed, ...})
    if isinstance(success_condition, dict):
        success_condition = success_condition.get("type")

    self.get_logger().info(
        f"[{gid}] Plan: {canonical} -> {len(stages)} stages"
    )

    inplace_check = validate_inplace_plan(
        canonical,
        ctx.params,
        stages,
        self._controller_routes,
        self._config.navigation_config,
    )
    if not inplace_check.valid:
        reason = inplace_check.reason
        self._stationary_expression_adapter.cancel_step()
        if self._chassis_backend is not None:
            self._chassis_backend.hold_position()
        self.get_logger().error(
            f"[{gid}] In-place plan rejected: {reason}"
        )
        goal_handle.abort()
        self._debug.publish_result(ExecutionResult(
            goal_id=gid,
            behavior_id=behavior_id,
            behavior_name=canonical,
            status="FAILED",
            result="failed",
            reason=reason,
            reward=-1.0,
        ))
        return make_result(
            gid, behavior_id, requested_name,
            resolved_name=canonical,
            status="FAILED", result="failed",
            reason=reason, reward=-1.0,
        )

    # ── Step 4: Navigate semantic waypoint, when routed ─────────
    stage_results: dict[str, bool] = {}

    # Reset interrupt state
    self._interrupt.reset()
    self._posture.reset()
    if goal_handle.is_cancel_requested:
        # Do not let a cancel accepted while this Goal was waiting for
        # the execution lock be erased by the per-goal reset above.
        self._interrupt.request_cancel()

    if (
        self._mobility_adapter is not None
        and self._mobility_adapter.waypoint_for_behavior(canonical)
        is not None
    ):
        waypoint_name = (
            self._mobility_adapter.waypoint_for_behavior(canonical)
        )
        # Random behaviors request waypoint_nav's reserved live-map
        # target and use their own shorter timeout; semantic routes
        # keep the full fixed-waypoint budget.
        is_random_nav = (
            canonical
            in self._mobility_adapter._random_navigation_behaviors
        )
        if is_random_nav:
            nav_timeout = float(
                self._config.navigation_config.get(
                    "random_navigation_result_timeout_sec"
                )
                or self._config.navigation_config.get(
                    "result_timeout_sec", 300.0
                )
            )
        else:
            nav_timeout = float(
                self._config.navigation_config.get(
                    "result_timeout_sec", 300.0
                )
            )
        remaining = ctx.remaining_runtime_sec(time.monotonic())
        if remaining is not None:
            nav_timeout = min(nav_timeout, remaining)
        self.get_logger().info(
            f"[{gid}] Navigation: {canonical} -> "
            f"waypoint {waypoint_name} "
            f"(timeout={nav_timeout:.0f}s)"
        )
        waypoint_task_id = f"action:{gid}:waypoint"

        def _waypoint_feedback(status: WaypointNavStatus) -> None:
            progress_by_code = {
                "QUEUED": 0.02,
                "DISPATCHED": 0.05,
                "NAV2_ACCEPTED": 0.10,
                "RECOVERY_REQUIRED": 0.05,
                "NAV2_SUCCEEDED": 0.20,
            }
            self._publish_feedback(
                goal_handle,
                gid,
                behavior_id,
                canonical,
                progress_by_code.get(status.code, 0.10),
                "waypoint_navigation",
                f"WAYPOINT_NAV/{status.code}",
                (
                    status.safe_to_interrupt
                    if not status.terminal
                    else False
                ),
                (
                    f"waypoint task={status.task_id} "
                    f"state={status.state} code={status.code}: "
                    f"{status.message}"
                ),
            )

        navigation_ok = (
            nav_timeout > 0.0
            and not goal_handle.is_cancel_requested
            and self._mobility_adapter.navigate_for_behavior(
                canonical,
                timeout_sec=nav_timeout,
                task_id=waypoint_task_id,
                status_callback=_waypoint_feedback,
            )
        )
        if not navigation_ok:
            cancel_requested = (
                goal_handle.is_cancel_requested
                or self._interrupt.cancel_requested
            )
            waypoint_outcome = (
                self._waypoint_nav_client.last_outcome
                if (
                    self._waypoint_nav_client is not None
                    and self._waypoint_nav_client.last_outcome.task_id
                    == waypoint_task_id
                )
                else None
            )
            mobility_error = str(
                getattr(
                    self._mobility_adapter,
                    "last_error",
                    "",
                )
                or ""
            ).strip()
            canceled = _navigation_cancel_won(
                cancel_requested,
                waypoint_outcome,
            )
            timed_out = (
                not canceled
                and (
                    ctx.remaining_runtime_sec(time.monotonic()) == 0.0
                    or (
                        waypoint_outcome is not None
                        and waypoint_outcome.code == "TIMEOUT"
                    )
                )
            )
            status = (
                "CANCELED" if canceled
                else "TIMEOUT" if timed_out
                else "FAILED"
            )
            result_text = "canceled" if canceled else "failed"
            if timed_out:
                reason = "behavior_goal_timeout"
            elif mobility_error:
                reason = mobility_error
            elif waypoint_outcome is not None:
                reason = (
                    f"waypoint_navigation_{result_text}: "
                    f"task_id={waypoint_outcome.task_id}, "
                    f"state={waypoint_outcome.state}, "
                    f"code={waypoint_outcome.code}, "
                    f"terminal_confirmed="
                    f"{waypoint_outcome.terminal_confirmed}, "
                    f"message={waypoint_outcome.message}"
                )
            else:
                reason = (
                    f"navigation_{result_text}: "
                    f"waypoint={waypoint_name}"
                )
            self.get_logger().error(f"[{gid}] {reason}")
            if canceled:
                goal_handle.canceled()
            else:
                goal_handle.abort()
            self._debug.publish_result(
                ExecutionResult(
                    goal_id=gid,
                    behavior_id=behavior_id,
                    behavior_name=canonical,
                    status=status,
                    result=result_text,
                    reason=reason,
                    duration_sec=(
                        time.time() - behavior_started_wall
                    ),
                    reward=-1.0,
                )
            )
            return make_result(
                gid,
                behavior_id,
                requested_name,
                resolved_name=canonical,
                status=status,
                result=result_text,
                reason=reason,
                reward=-1.0,
            )

    # ── Step 5: Execute existing behavior-tree stages ───────────
    # For target-bound behaviors, sound is part of the interaction and
    # must not start before target_approach succeeds. Behaviors without
    # an approach Stage still start audio with their first Stage.
    sound_started = self._behavior_sounds.apply_control_behavior(
        canonical
    )

    for i, stage_cfg in enumerate(stages):
        stage_id = (
            stage_cfg.get("stage_id")
            or stage_cfg.get("stage_name")
            or f"stage_{i}"
        )

        # ── Cancel check ────────────────────────────────────
        if goal_handle.is_cancel_requested:
            ctx.cancel_requested = True
            self._interrupt.request_cancel()
            self.get_logger().info(f"[{gid}] Cancel — stopping at stage {stage_id}")
            break

        # ── Timeout check ────────────────────────────────────
        remaining = ctx.remaining_runtime_sec(time.monotonic())
        if remaining is not None and remaining <= 0.0:
            elapsed = time.time() - behavior_started_wall
            self.get_logger().warning(
                f"[{gid}] Timeout after {elapsed:.1f}s "
                f"(limit: {runtime_timeout_sec:.1f}s)"
            )
            ctx.metadata["unit_failure_state"] = "timeout"
            ctx.metadata["unit_failure_reason"] = (
                "behavior_goal_timeout"
            )
            stage_results[stage_id] = False
            break

        # ── Execute stage ────────────────────────────────────
        self.get_logger().info(
            f"[{gid}] Stage {i+1}/{len(stages)}: {stage_id}"
        )
        if not sound_started and stage_id != "target_approach":
            sound_path = self._behavior_sounds.play_for(canonical)
            sound_started = True
            if sound_path is not None:
                self.get_logger().info(
                    f"[{gid}] Behavior sound started: {canonical} -> "
                    f"{sound_path.name}"
                )
        self._interrupt.apply_to_context(ctx)

        # Stage-scoped audio. Started after the context refresh so a
        # cancel that landed earlier this iteration starts nothing new,
        # and scoped to this call so the failure-policy break below
        # cannot leak the stream into the rest of the behavior.
        # target_approach needs no guard here: no stage mapping ever
        # targets it, unlike the behavior-level start above.
        with self._behavior_sounds.stage_sound(
            canonical, stage_id
        ) as stage_sound_path:
            if stage_sound_path is not None:
                self.get_logger().info(
                    f"[{gid}] Stage sound started: {stage_id} -> "
                    f"{stage_sound_path.name}"
                )
            result = self._stage_executor.execute_stage(stage_cfg, ctx)

        stage_results[stage_id] = result.success
        self._interrupt.apply_to_context(ctx)

        # ── Publish feedback ─────────────────────────────────
        progress = round((i + 1) / len(stages), 4)
        self._publish_feedback(
            goal_handle, gid, behavior_id, canonical,
            progress, stage_id, result.unit_id,
            self._interrupt.safe_to_interrupt,
            f"Stage {i+1}/{len(stages)}: {result.unit_id} — "
            f"{'OK' if result.success else result.message}",
        )

        # ── Handle stage failure ─────────────────────────────
        if not result.success:
            failure_policy = stage_cfg.get("failure_policy", "abort")
            required = stage_cfg.get("required", True)
            self.get_logger().warning(
                f"[{gid}] Stage {stage_id} failed: {result.message} "
                f"(policy={failure_policy}, required={required})"
            )
            if required and failure_policy == "abort":
                break
            # skip_stage → continue to next stage

    # ── Step 6: Evaluate result ────────────────────────────────
    behavior_result = self._result_evaluator.evaluate(
        ctx, stage_results, success_condition,
    )

    duration = time.time() - behavior_started_wall
    self.get_logger().info(
        f"[{gid}] Result: {behavior_result.status} "
        f"(success={behavior_result.success}, "
        f"stages={behavior_result.completed_stages}, "
        f"units={behavior_result.executed_units}, "
        f"duration={duration:.1f}s)"
    )

    if behavior_result.success:
        goal_handle.succeed()
    elif ctx.cancel_requested and behavior_result.status != "controller_error":
        goal_handle.canceled()
    else:
        goal_handle.abort()

    result_text = (
        "completed"
        if behavior_result.success
        else "canceled"
        if behavior_result.status == "canceled"
        else "failed"
    )

    # ── Metadata for behaviors that report internal state ──────
    metadata: dict[str, object] = {}
    target_approach_metadata = ctx.metadata.get("target_approach")
    if isinstance(target_approach_metadata, dict):
        metadata["target_approach"] = dict(
            target_approach_metadata
        )
    visual_target_metadata = ctx.metadata.get(
        "visual_target_approach"
    )
    if isinstance(visual_target_metadata, dict):
        metadata["visual_target_approach"] = dict(
            visual_target_metadata
        )
    lite3_action_metadata = ctx.metadata.get("lite3_action")
    if isinstance(lite3_action_metadata, dict):
        metadata["lite3_action"] = dict(lite3_action_metadata)
    lite3_action_history = ctx.metadata.get("lite3_actions")
    if isinstance(lite3_action_history, list):
        metadata["lite3_actions"] = [
            dict(item)
            for item in lite3_action_history
            if isinstance(item, dict)
        ]
    if (
        behavior_result.success
        and canonical in ("restInPlace", "recharge")
    ):
        # No verified battery producer is connected. Completion of a
        # proxy/action is not a measurement or charging confirmation.
        metadata["energy_settlement"] = "observation_unavailable"
    metadata_json = json.dumps(metadata) if metadata else "{}"

    exec_result = ExecutionResult(
        goal_id=gid,
        behavior_id=behavior_id,
        behavior_name=canonical,
        status=behavior_result.status.upper(),
        result=result_text,
        reason=(
            str(ctx.metadata.get("unit_failure_reason"))
            if not behavior_result.success
            and ctx.metadata.get("unit_failure_reason")
            else behavior_result.message or behavior_result.reason
        ),
        duration_sec=duration,
        reward=behavior_result.reward,
        emotion_delta_json="{}",
        need_delta_json="{}",
        metadata_json=metadata_json,
    )
    self._debug.publish_result(exec_result)

    return make_result(
        gid, behavior_id, requested_name,
        resolved_name=canonical,
        status=behavior_result.status.upper(),
        result=result_text,
        reason=(
            str(ctx.metadata.get("unit_failure_reason"))
            if not behavior_result.success
            and ctx.metadata.get("unit_failure_reason")
            else behavior_result.message or behavior_result.reason
        ),
        reward=behavior_result.reward,
        metadata=metadata,
    )


def execute_long_behavior(self, goal_handle, ctx: ExecutionContext, stages: list[dict], started_wall: float, *, make_result):
    """Run one leased Goal until cancellation or a real failure."""
    gid = str(goal_handle.request.goal_id)
    behavior_id = str(getattr(goal_handle.request, "behavior_id", "") or gid)
    name = ctx.resolved_behavior_name
    started = time.monotonic()
    cycle = 0
    cycles_completed = 0
    state = {"stage": "starting", "action": "", "safe": True}
    lease_lost = threading.Event()
    ticker_done = threading.Event()
    self._long_goal_id = gid
    self._interrupt.reset()
    self._posture.reset()
    if goal_handle.is_cancel_requested:
        self._interrupt.request_cancel()

    def canceled() -> bool:
        return bool(goal_handle.is_cancel_requested or self._interrupt.cancel_requested)

    def tick() -> None:
        while not ticker_done.wait(0.5):
            if self._lease_expired(gid, behavior_id, started):
                lease_lost.set()
                if name == "play_alone":
                    roam_adapter = getattr(self, "_uwb_roam_adapter", None)
                    if roam_adapter is not None:
                        roam_adapter.cancel_step()
                    self._stationary_expression_adapter.cancel_step()
                    if (self._chassis_backend is not None
                            and not getattr(roam_adapter, "active", False)):
                        self._chassis_backend.cancel_step()
                elif self._uwb_follow_adapter is not None:
                    self._uwb_follow_adapter.request_cancel()
            self._publish_feedback(
                goal_handle, gid, behavior_id, name, 0.0,
                state["stage"], state["action"],
                bool(state["safe"] and not canceled() and not lease_lost.is_set()),
                f"cycle={cycle} stage={state['stage']} "
                f"lease={'expired' if lease_lost.is_set() else 'active'}",
            )

    thread = threading.Thread(target=wrap_context(tick), name=f"goal-feedback-{gid}", daemon=True)
    thread.start()
    status = "FAILED"
    reason = "long_goal_failed"
    try:
        if name == "follow_owner":
            adapter = self._uwb_follow_adapter
            if adapter is None:
                reason = "uwb_follow_unavailable"
            elif canceled():
                status, reason = "CANCELED", "canceled_before_start"
            else:
                if isinstance(adapter, UwbFollowActionAdapter):
                    adapter._long_goal_active = True
                state.update(stage="following", action="ACT_INTERACT_FOLLOW_OWNER")
                if isinstance(adapter, UwbFollowActionAdapter):
                    started_ok = adapter.start(timeout_sec=0.0)
                else:
                    started_ok = adapter.start(wait_for_grace=True)
                    if started_ok:
                        adapter.enable_target_monitor()
                if not started_ok:
                    reason = adapter.last_error or "uwb_follow_start_failed"
                    if canceled() and not adapter.recovery_required:
                        status, reason = "CANCELED", "canceled_during_startup"
                else:
                    while True:
                        if canceled():
                            status, reason = "CANCELED", "canceled"
                            break
                        if lease_lost.is_set():
                            reason = "upstream_goal_lease_expired"
                            break
                        if not adapter.poll_health() or not adapter.active:
                            reason = adapter.last_error or "uwb_follow_ended"
                            break
                        time.sleep(0.1)
                state.update(stage="stopping", safe=False)
                if not adapter.stop_confirmed(reason):
                    status = "FAILED"
                    reason = adapter.last_error or "uwb_follow_terminal_unknown"
        else:
            roam = getattr(self, "_uwb_roam_adapter", None)
            if canceled():
                status, reason = "CANCELED", "canceled_before_start"
            elif roam is None:
                reason = "uwb_roam_unavailable"
            else:
                while True:
                    if canceled():
                        status, reason = "CANCELED", "canceled"
                        break
                    if lease_lost.is_set():
                        reason = "upstream_goal_lease_expired"
                        break
                    cycle += 1
                    ctx.completed_stages.clear()
                    ctx.metadata.pop("uwb_roam_terminal_status", None)
                    for stage in stages:
                        stage_id = str(stage.get("stage_id") or "stage")
                        state.update(stage=stage_id, action="", safe=True)
                        if canceled() or lease_lost.is_set():
                            break
                        result = self._stage_executor.execute_stage(stage, ctx)
                        state["action"] = result.unit_id
                        if not result.success:
                            reason = str(ctx.metadata.get("unit_failure_reason") or result.message)
                            break
                        self._publish_feedback(
                            goal_handle, gid, behavior_id, name, 0.0,
                            stage_id, result.unit_id, True,
                            f"cycle={cycle} stage={stage_id} complete",
                        )
                    else:
                        cycles_completed += 1
                        state.update(stage="cycle_complete", action="", safe=True)
                        continue
                    if canceled():
                        if ctx.metadata.get("uwb_roam_terminal_status") in (4, 6):
                            status = "FAILED"
                        else:
                            status, reason = "CANCELED", "canceled"
                    elif lease_lost.is_set():
                        reason = "upstream_goal_lease_expired"
                    break
            state.update(stage="stopping", safe=False)
            terminal_unknown = bool(roam is not None and roam.active)
            if roam is not None and roam.active:
                # The adapter owns the inner goal until its real Result.
                # A transport failure latches recovery_required and
                # prevents a replacement Goal from taking /cmd_vel.
                roam.cancel_step()
                reason = "uwb_roam_terminal_unknown:operator_recovery_required"
                status = "FAILED"
            if self._chassis_backend is not None:
                self._chassis_backend.emergency_stop()
                if (not terminal_unknown
                        and self._chassis_backend.finish_navigation() is False):
                    status = "FAILED"
                    reason = (self._chassis_backend.last_error
                              or "play_alone_stop_unconfirmed")
                    if roam is not None:
                        roam.recovery_required = True
    except Exception as exc:
        reason = f"long_goal_exception:{type(exc).__name__}:{exc}"
        self.get_logger().error(reason)
        if name == "follow_owner" and self._uwb_follow_adapter is not None:
            self._uwb_follow_adapter.stop_confirmed(reason)
        if name == "play_alone" and self._chassis_backend is not None:
            self._chassis_backend.emergency_stop()
    finally:
        ticker_done.set()
        thread.join(timeout=1.0)
        if name == "follow_owner" and isinstance(
            self._uwb_follow_adapter, UwbFollowActionAdapter
        ):
            self._uwb_follow_adapter._long_goal_active = False
        self._long_goal_id = None

    if status == "CANCELED":
        goal_handle.canceled()
    else:
        goal_handle.abort()
    result = make_result(
        gid, behavior_id, name, status=status,
        result="canceled" if status == "CANCELED" else "failed",
        reason=reason, reward=-1.0,
        metadata={"cycles_completed": cycles_completed},
    )
    self._debug.publish_result(ExecutionResult(
        goal_id=gid, behavior_id=behavior_id, behavior_name=name,
        status=status,
        result="canceled" if status == "CANCELED" else "failed",
        reason=reason, duration_sec=time.time() - started_wall,
        reward=-1.0,
    ))
    return result


def execute_emergency_stop(self, goal_handle, *, make_result):
    """Publish zero velocity immediately without waiting for another goal."""
    self._behavior_sounds.stop()
    roam = getattr(self, "_uwb_roam_adapter", None)
    if roam is not None:
        roam.emergency_stop()
    self._stationary_expression_adapter.emergency_stop()
    goal_req = goal_handle.request
    gid = goal_req.goal_id
    behavior_id = getattr(goal_req, "behavior_id", gid)
    reason = "selected chassis backend disabled; no motion stop outlet"
    if self._uwb_follow_adapter is not None:
        self._uwb_follow_adapter.emergency_stop()
        reason = "UWB follow stopped and chassis stop published"
    if self._wake_orientation_adapter is not None:
        self._wake_orientation_adapter.emergency_stop()
        reason = "Nav2 Spin canceled"
    if self._target_approach_adapter is not None:
        self._target_approach_adapter.emergency_stop()
        reason = "target approach canceled and chassis stop published"
    if self._person_nav_approach_adapter is not None:
        self._person_nav_approach_adapter.emergency_stop()
        reason = "Nav2 caller approach cancel requested and chassis stop published"
    if self._visual_target_approach_adapter is not None:
        self._visual_target_approach_adapter.emergency_stop()
        reason = (
            "visual target approach canceled and chassis stop "
            "published"
        )
    if self._mobility_adapter is not None:
        self._mobility_adapter.emergency_stop()
        reason = "Nav2 canceled and chassis stop published"
    if self._chassis_backend is not None:
        self._chassis_backend.emergency_stop()
        if self._mobility_adapter is None:
            reason = "chassis stop published"

    exec_result = ExecutionResult(
        goal_id=gid,
        behavior_id=behavior_id,
        behavior_name="emergency_stop",
        status="SUCCESS",
        result="completed",
        reason=reason,
        reward=1.0,
    )
    self._debug.publish_result(exec_result)
    goal_handle.succeed()
    return make_result(
        gid,
        behavior_id,
        "emergency_stop",
        status="SUCCESS",
        result="completed",
        reason=reason,
        reward=1.0,
    )
