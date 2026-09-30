"""Voice session and hold coordination through the node-owned state and lock ports.

The node remains the single state owner; clocks and callback order are preserved.
"""
from __future__ import annotations
import math
import time
import uuid
from typing import Any
from .interaction_state_machine import Trigger


def begin_interaction(self, interaction_id: str | None=None, *, source: str='unknown'):
    """Start one session and return its immutable interaction ID."""
    with self._interaction_lock:
        if self._interaction_active:
            return self._interaction_id
        self._interaction_id = interaction_id or uuid.uuid4().hex
        self._interaction_active = True
        self._interaction_holds.clear()
        started_monotonic = time.monotonic()
        self._interaction_started_time = started_monotonic
        self._last_interaction_time = started_monotonic
        self._last_interaction_activity_reason = "interaction_start"
        self._state_machine.trigger(Trigger.WAKEUP)
        started_id = self._interaction_id
    self._trace(
        "interaction_start",
        result="started",
        source=source,
        interaction_id=started_id,
        state=self._state_machine.state.value,
    )
    return started_id


def refresh_interaction_activity(self, now: float | None=None, *, reason: str='activity'):
    with self._interaction_lock:
        if self._interaction_active:
            self._last_interaction_time = (
                time.monotonic() if now is None else now
            )
            self._last_interaction_activity_reason = reason


def is_interaction_active(self):
    with self._interaction_lock:
        return self._interaction_active


def prune_interaction_holds_locked(self, now: float, *, logger):
    expired = [
        token for token, hold in self._interaction_holds.items()
        if float(hold["deadline_monotonic"]) <= now
    ]
    for token in expired:
        hold = self._interaction_holds.pop(token, {})
        logger.info("Interaction hold lease expired: token=%s", token)
        self._trace(
            "interaction_hold",
            operation="expire",
            result="expired",
            interaction_id=self._interaction_id,
            hold_token=token,
            reason=str(hold.get("reason", "")),
        )


def timeout_interaction_id(self, now: float):
    """Return the session ID only when it is safe to idle-timeout."""
    with self._interaction_lock:
        if not self._interaction_active:
            return ""
        started = getattr(self, "_interaction_started_time", 0.0)
        max_duration = getattr(self, "_max_interaction_duration", 0.0)
        if started and max_duration and now - started > max_duration:
            return self._interaction_id
        self._prune_interaction_holds_locked(now)
        if self._interaction_holds:
            return ""
        if self._idle_timeout <= 0.0:
            return ""
        if now - self._last_interaction_time <= self._idle_timeout:
            return ""
        return self._interaction_id


def hold_interaction(self, params: dict[str, Any]):
    interaction_id = str(params.get("interaction_id", "")).strip()
    hold_token = str(params.get("hold_token", "")).strip()
    reason = str(params.get("reason", "")).strip()
    try:
        lease_sec = float(params.get("lease_sec", 0.0))
    except (TypeError, ValueError):
        lease_sec = float("nan")
    if not interaction_id:
        return {"ok": False, "error": "interaction_id is required"}
    if not hold_token:
        return {"ok": False, "error": "hold_token is required"}
    if not math.isfinite(lease_sec) or lease_sec <= 0.0:
        return {"ok": False, "error": "lease_sec must be finite and > 0"}
    if lease_sec > self._hold_max_lease_sec:
        return {
            "ok": False,
            "error": (
                "lease_sec exceeds hold_max_lease_sec="
                f"{self._hold_max_lease_sec:g}"
            ),
        }
    now = time.monotonic()
    with self._interaction_lock:
        self._prune_interaction_holds_locked(now)
        if not self._interaction_active:
            return {"ok": False, "error": "interaction is not active"}
        if interaction_id != self._interaction_id:
            return {"ok": False, "error": "interaction_id mismatch"}
        renewed = hold_token in self._interaction_holds
        self._interaction_holds[hold_token] = {
            "reason": reason,
            "deadline_monotonic": now + lease_sec,
        }
        self._trace(
            "interaction_hold",
            operation="renew" if renewed else "acquire",
            result="held",
            interaction_id=interaction_id,
            hold_token=hold_token,
            reason=reason,
            lease_sec=lease_sec,
        )
        return {
            "ok": True,
            "interaction_id": interaction_id,
            "hold_token": hold_token,
            "held": True,
            "renewed": renewed,
            "lease_sec": lease_sec,
            "expires_in_sec": lease_sec,
        }


def release_interaction_hold(self, params: dict[str, Any]):
    interaction_id = str(params.get("interaction_id", "")).strip()
    hold_token = str(params.get("hold_token", "")).strip()
    reset_idle_timer = bool(params.get("reset_idle_timer", False))
    if not interaction_id:
        return {"ok": False, "error": "interaction_id is required"}
    if not hold_token:
        return {"ok": False, "error": "hold_token is required"}
    now = time.monotonic()
    with self._interaction_lock:
        self._prune_interaction_holds_locked(now)
        if not self._interaction_active:
            return {"ok": False, "error": "interaction is not active"}
        if interaction_id != self._interaction_id:
            return {"ok": False, "error": "interaction_id mismatch"}
        released = self._interaction_holds.pop(hold_token, None) is not None
        if released and reset_idle_timer:
            self._refresh_interaction_activity(
                now=now,
                reason="interaction_hold_release",
            )
        self._trace(
            "interaction_hold",
            operation="release",
            result="released" if released else "not_found",
            interaction_id=interaction_id,
            hold_token=hold_token,
            idle_timer_reset=bool(released and reset_idle_timer),
        )
        return {
            "ok": True,
            "interaction_id": interaction_id,
            "hold_token": hold_token,
            "held": False,
            "released": released,
            "idle_timer_reset": bool(released and reset_idle_timer),
        }


def interaction_state(self):
    now_monotonic = time.monotonic()
    with self._interaction_lock:
        self._prune_interaction_holds_locked(now_monotonic)
        holds = [
            {
                "hold_token": token,
                "reason": str(hold.get("reason", "")),
                "expires_in_sec": max(
                    0.0,
                    float(hold["deadline_monotonic"]) - now_monotonic,
                ),
            }
            for token, hold in sorted(self._interaction_holds.items())
        ]
        idle_elapsed = (
            max(0.0, now_monotonic - self._last_interaction_time)
            if self._interaction_active else 0.0
        )
        active_elapsed = (
            max(0.0, now_monotonic - self._interaction_started_time)
            if self._interaction_active else 0.0
        )
        return {
            "ok": True,
            "listening": self._interaction_active,
            "interaction_active": self._interaction_active,
            "interaction_id": self._interaction_id,
            "state": self._state_machine.state.value,
            "idle_timeout_sec": self._idle_timeout,
            "refresh_on_any_speech": getattr(
                self,
                "_refresh_on_any_speech",
                False,
            ),
            "idle_elapsed_sec": idle_elapsed,
            "max_duration_sec": getattr(
                self,
                "_max_interaction_duration",
                0.0,
            ),
            "active_elapsed_sec": active_elapsed,
            "last_activity_reason": getattr(
                self,
                "_last_interaction_activity_reason",
                "",
            ),
            "hold_active": bool(holds),
            "holds": holds,
        }
