"""Transport-independent voice engagement policy with explicit capabilities.

The coordinator can run with plain state and fake ports, without a ROS node.
Legacy function entrypoints remain in voice_engagement; the adapter alone maps
node-owned state and existing clients to these narrow interfaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol
import time

from .voice_interaction_session import (
    ACQUIRING_TARGET, APPROACHING, AWAITING_IDENTITY, CLOSED, ORIENTING,
    WAITING, VoiceInteractionSession,
)


class VoiceState(Protocol):
    generation: int
    attention_interaction_id: str
    attention_mode: str

    @property
    def session(self) -> VoiceInteractionSession | None: ...

    @property
    def config(self) -> Mapping[str, Any]: ...


@dataclass
class VoiceEngagementState:
    session: VoiceInteractionSession | None = None
    generation: int = 0
    attention_interaction_id: str = ""
    attention_mode: str = "face_body_centering"
    config: Mapping[str, Any] = field(default_factory=dict)


class VoiceLeasePort(Protocol):
    def hold(self, interaction_id: str, hold_token: str, *, lease_sec: float,
             callback: Callable[[dict | None], None]) -> bool: ...
    def release(self, interaction_id: str, hold_token: str, *, reset_idle_timer: bool) -> bool: ...


class WakeTargetPort(Protocol):
    def request_wake_speaker(self, callback: Callable[[dict | None], None], **kwargs) -> None: ...


class CandidatePort(Protocol):
    def add(self, candidate: Any) -> bool: ...
    def discard_session(self, interaction_id: str) -> int: ...
    def discard_where(self, predicate: Callable[[dict], bool]) -> int: ...


class InteractionExecutionPort(Protocol):
    def discard_pending_interaction(self, interaction_id: str) -> bool: ...
    def cancel_current_interaction(self, interaction_id: str, *, reason: str) -> Any: ...


class DeferredEmotionPort(Protocol):
    def defer(self, interaction_id: str) -> None: ...
    def resume(self) -> None: ...


class VoiceLogPort(Protocol):
    def info(self, message: str) -> None: ...
    def warn(self, message: str) -> None: ...


@dataclass(frozen=True)
class VoiceEngagementPorts:
    lease: VoiceLeasePort
    targets: WakeTargetPort
    candidates: CandidatePort
    execution: InteractionExecutionPort
    emotions: DeferredEmotionPort
    publish_attention: Callable[[bool, dict], None]
    build_approach_candidate: Callable[..., Any]
    logger: VoiceLogPort


class VoiceEngagementCoordinator:
    def __init__(self, state: VoiceState, ports: VoiceEngagementPorts, *,
                 monotonic: Callable[[], float] | None = None):
        self.state = state
        self.ports = ports
        self._monotonic = monotonic or time.monotonic


    def request_voice_hold(self, session: VoiceInteractionSession):
        if (
            self.state.session is not session
            or not session.active
            or session.hold_request_pending
            or session.command_received
            or session.phase not in (
                ORIENTING, AWAITING_IDENTITY, ACQUIRING_TARGET, APPROACHING
            )
            or not str(session.hold_token).strip()
        ):
            return
        lease_sec = float(self.state.config.get("hold_lease_sec", 6.0))
        generation = session.generation
        interaction_id = session.interaction_id
        hold_token = str(session.hold_token).strip()
        session.hold_request_pending = True
        session.last_hold_attempted_at = self._monotonic()

        def _held(result: dict | None) -> None:
            current = self.state.session
            hold_succeeded = bool(
                isinstance(result, dict) and result.get("ok", True)
            )
            request_is_current = bool(
                current is session
                and current.matches(interaction_id, generation)
                and not current.command_received
                and current.hold_request_pending
                and str(current.hold_token).strip() == hold_token
                and current.phase in (
                    ORIENTING, ACQUIRING_TARGET, APPROACHING
                )
            )
            if not request_is_current:
                # The release that ended wake engagement may have reached
                # Voice before this older hold request.  If the older request
                # then succeeds, release the captured token once more so a
                # stale lease cannot delay the session's idle transition.
                if hold_succeeded:
                    reset_idle_timer = bool(
                        current is session
                        and current.phase == WAITING
                        and not current.command_received
                    )
                    if not self.ports.lease.release(
                        interaction_id,
                        hold_token,
                        reset_idle_timer=reset_idle_timer,
                    ):
                        self.ports.logger.warn(
                            "Late Voice hold cleanup unavailable: "
                            "interaction_id=%s" % interaction_id
                        )
                return
            current.hold_request_pending = False
            current.hold_active = hold_succeeded
            if current.hold_active:
                current.last_hold_renewed_at = self._monotonic()
            else:
                self.ports.logger.warn(
                    "Voice hold rejected: interaction_id=%s"
                    % current.interaction_id
                )

        scheduled = self.ports.lease.hold(
            interaction_id,
            hold_token,
            lease_sec=lease_sec,
            callback=_held,
        )
        if not scheduled:
            session.hold_request_pending = False
            session.hold_active = False
            self.ports.logger.warn(
                "Voice hold unavailable: interaction_id=%s"
                % session.interaction_id
            )

    def renew_voice_hold_if_due(self):
        session = self.state.session
        if (
            session is None
            or not session.active
            or session.command_received
            or not str(session.hold_token).strip()
            or session.phase not in (
                ORIENTING, ACQUIRING_TARGET, APPROACHING
            )
        ):
            return
        interval = float(
            self.state.config.get("hold_renew_interval_sec", 2.0)
        )
        last_attempt_or_success = max(
            session.last_hold_attempted_at,
            session.last_hold_renewed_at,
        )
        if (
            not session.hold_request_pending
            and self._monotonic() - last_attempt_or_success >= interval
        ):
            self.request_voice_hold(session)

    def expire_wake_target_query_if_due(self):
        """Fail a hung visual query closed and resume the voice idle timer."""
        session = self.state.session
        if session is None or session.phase != ACQUIRING_TARGET:
            return
        started_at = session.metadata.get("target_query_started_at")
        if not isinstance(started_at, (int, float)):
            return
        timeout_sec = max(
            0.1,
            float(self.state.config.get("acquire_timeout_sec", 2.0)),
        )
        if self._monotonic() - float(started_at) < timeout_sec:
            return

        # Invalidate the captured service callback before changing phase.  A
        # late Vision response must not enqueue motion after we started
        # waiting for speech.
        session.generation += 1
        self.state.generation = max(
            self.state.generation,
            session.generation,
        )
        session.metadata.pop("target_query_started_at", None)
        self.enter_voice_waiting(session, reason="visual_query_timeout")

    def expire_wake_identity_if_due(self):
        session = self.state.session
        if session is None or session.phase != AWAITING_IDENTITY:
            return
        started_at = session.metadata.get("identity_wait_started_at")
        if not isinstance(started_at, (int, float)):
            return
        timeout_sec = max(0.1, float(
            self.state.config.get("wake_identity_timeout_sec", 3.0)
        ))
        if self._monotonic() - float(started_at) >= timeout_sec:
            self.enter_voice_waiting(session, reason="wake_identity_timeout")

    def continue_wake_after_identity(self, session: VoiceInteractionSession):
        if session.phase != AWAITING_IDENTITY or session.command_received:
            return
        role = session.metadata.get("wake_speaker_role")
        status = session.metadata.get("wake_speaker_status")
        if role in ("owner", "family") and status == "matched":
            self.request_wake_speaker(session)
        elif status != "pending":
            self.enter_voice_waiting(session, reason="wake_identity_%s" % status)

    def release_voice_hold(self, session: VoiceInteractionSession, *, reset_idle_timer: bool):
        if not session.hold_token:
            return
        hold_token = session.hold_token
        session.hold_token = ""
        session.hold_active = False
        session.hold_request_pending = False
        if not self.ports.lease.release(
            session.interaction_id,
            hold_token,
            reset_idle_timer=reset_idle_timer,
        ):
            self.ports.logger.warn(
                "Voice hold release unavailable: interaction_id=%s"
                % session.interaction_id
            )

    def close_voice_session(self, interaction_id: str, *, reason: str):
        session = self.state.session
        if session is None or not session.matches(interaction_id):
            return
        session.phase = CLOSED
        session.generation += 1
        self.state.generation = max(
            self.state.generation, session.generation
        )
        self.release_voice_hold(session, reset_idle_timer=False)
        self.ports.emotions.defer(interaction_id)
        removed = self.ports.candidates.discard_session(interaction_id)
        self.ports.execution.discard_pending_interaction(interaction_id)
        canceled = self.ports.execution.cancel_current_interaction(
            interaction_id,
            reason="voice_session_closed:%s" % reason,
        )
        self.ports.publish_attention(False, {
            "interaction_id": interaction_id,
            "state_reason": reason,
        })
        self.state.attention_interaction_id = ""
        self.state.attention_mode = "face_body_centering"
        self.ports.emotions.resume()
        self.ports.logger.info(
            "Voice session closed: id=%s reason=%s queued_removed=%d running=%s"
            % (interaction_id, reason, removed, bool(canceled))
        )

    def enter_voice_waiting(self, session: VoiceInteractionSession, *, reason: str):
        current = self.state.session
        if current is None or not current.matches(
            session.interaction_id, session.generation
        ):
            return
        current.phase = WAITING
        # Unknown and stranger wakes remain stationary after the sound turn.
        approach_finished = reason == "arrived"
        self.state.attention_interaction_id = (
            current.interaction_id if approach_finished else ""
        )
        self.state.attention_mode = "face_body_centering"
        self.ports.publish_attention(approach_finished, {
            "interaction_id": current.interaction_id,
            # respond_owner_call already consumed the microphone bearing.  A
            # second fallback turn here would rotate the chassis twice.
            "wake_angle": 0.0,
            "wake_confidence": current.wake_confidence,
            "state_reason": reason,
        })
        self.release_voice_hold(current, reset_idle_timer=True)
        self.ports.emotions.resume()
        self.ports.logger.info(
            "Voice session waiting: id=%s reason=%s target=%s"
            % (
                current.interaction_id,
                reason,
                (
                    current.selected_target.get("target_id")
                    if isinstance(current.selected_target, dict) else "none"
                ),
            )
        )

    def request_wake_speaker(self, session: VoiceInteractionSession):
        session.phase = ACQUIRING_TARGET
        session.metadata["target_query_started_at"] = self._monotonic()
        generation = session.generation
        self.ports.targets.request_wake_speaker(
            lambda target: self.on_wake_speaker_resolved(
                session.interaction_id,
                generation,
                target,
            ),
            # respond_owner_call already turned the camera toward the source.
            reference_bearing_deg=0.0,
            min_confidence=float(
                self.state.config.get("target_min_confidence", 0.3)
            ),
            max_age_ms=float(
                self.state.config.get("target_max_age_ms", 300.0)
            ),
            max_bearing_error_deg=float(
                self.state.config.get(
                    "target_max_bearing_error_deg", 25.0
                )
            ),
            max_snapshot_age_ms=float(
                self.state.config.get(
                    "snapshot_max_age_ms", 500.0
                )
            ),
        )

    def on_wake_speaker_resolved(self, interaction_id: str, generation: int, target: dict | None):
        session = self.state.session
        if (
            session is None
            or not session.matches(interaction_id, generation)
            or session.phase != ACQUIRING_TARGET
            or session.command_received
        ):
            return
        session.metadata.pop("target_query_started_at", None)
        if not isinstance(target, dict):
            self.enter_voice_waiting(session, reason="no_visual_target")
            return

        session.selected_target = dict(target)
        target_id = str(target.get("target_id", ""))
        if (target.get("target_type") != "human"
                or not str(target.get("vision_epoch", ""))
                or not target_id.startswith(str(target["vision_epoch"]) + ":human:")):
            self.enter_voice_waiting(session, reason="invalid_visual_target")
            return
        # Existing Vision identity can veto a definite contradiction.  An
        # unknown face remains eligible because Vision confirmation is optional.
        if target.get("identity_state") == "confirmed_known":
            visual_identity = str(target.get("identity", ""))
            if visual_identity != session.metadata.get("wake_speaker_id"):
                self.enter_voice_waiting(session, reason="identity_conflict")
                return

        candidate = self.ports.build_approach_candidate(
            interaction_id=interaction_id,
            target=target,
            wake_id=str(session.metadata.get("wake_id", "")),
            speaker_id=str(session.metadata.get("wake_speaker_id", "")),
            speaker_role=str(session.metadata.get("wake_speaker_role", "")),
            speaker_status=str(session.metadata.get("wake_speaker_status", "")),
            stand_off_distance_m=float(
                self.state.config.get("stand_off_distance_m", 1.5)
            ),
            timeout_sec=float(
                self.state.config.get("approach_timeout_sec", 160.0)
            ),
            ttl_sec=float(
                self.state.config.get(
                    "approach_candidate_ttl_sec", 3.0
                )
            ),
        )
        if self.ports.candidates.add(candidate):
            session.phase = APPROACHING
        else:
            self.enter_voice_waiting(
                session, reason="approach_candidate_suppressed"
            )

    def handle_voice_behavior_terminal(self, active, completed):
        session = self.state.session
        if session is None or not session.active:
            return
        interaction_id = str(active.params.get("interaction_id", "")).strip()
        active_wake_id = str(active.params.get("wake_id", ""))
        current_wake_id = str(session.metadata.get("wake_id", ""))
        if (active.behavior_name == "respond_owner_call"
                and (interaction_id != session.interaction_id
                     or active_wake_id != current_wake_id)):
            replacement = session.metadata.pop("pending_wake_candidate", None)
            if replacement is not None and session.phase == ORIENTING:
                self.ports.candidates.add(replacement)
            return
        if not session.matches(interaction_id):
            return
        if (active.behavior_name in ("respond_owner_call", "approach_voice_caller")
                and active_wake_id != current_wake_id):
            return
        if active.params.get("session_role") in {
            "voice_command", "voice_social_reaction",
        }:
            session.metadata["command_goal_terminal"] = True
            self.ports.emotions.resume()
        status = str(getattr(completed, "status", "")).upper()
        if active.behavior_name == "respond_owner_call":
            if session.command_received:
                return
            if status in ("SUCCESS", "COMPLETED"):
                session.phase = AWAITING_IDENTITY
                session.metadata["identity_wait_started_at"] = self._monotonic()
                self.continue_wake_after_identity(session)
            else:
                self.enter_voice_waiting(
                    session, reason="wake_orientation_%s" % status.lower()
                )
        elif active.behavior_name == "approach_voice_caller":
            if session.command_received:
                return
            reason = str(getattr(completed, "reason", "")).strip()
            self.enter_voice_waiting(
                session,
                reason=(
                    "arrived" if status in ("SUCCESS", "COMPLETED")
                    else "approach_%s%s" % (
                        status.lower(),
                        ":%s" % reason if reason else "",
                    )
                ),
            )

    def consume_voice_session_turn(self, session, kind: str):
        """Give one accepted command/reaction ownership of the voice turn."""
        session.consume_turn(kind)
        session.metadata["command_goal_terminal"] = False
        session.generation += 1
        self.state.generation = max(
            self.state.generation,
            session.generation,
        )
        interaction_id = session.interaction_id
        self.ports.emotions.defer(interaction_id)
        self.ports.candidates.discard_where(
            lambda queued: (
                queued.get("params", {}).get("interaction_id")
                == interaction_id
                and queued.get("params", {}).get("session_role") in {
                    "wake_approach",
                    "voice_waiting_emotion",
                }
            )
        )
        self.release_voice_hold(session, reset_idle_timer=False)
