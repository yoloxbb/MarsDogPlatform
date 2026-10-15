"""Order legacy V2 snapshots/signals without changing their public envelope.

Both topics carry the producer's wall timestamp. Track it per domain/channel,
not globally: one emotion's event must not suppress another emotion's snapshot.
Equal timestamps remain admissible (one clock sample can cover several changes).
Unstamped legacy payloads remain compatible and do not reset a known watermark.

This is not an epoch/revision protocol: producer clock rollback and consumers
restarting require a future versioned contract, not a guessed timeout unlock.
"""
from __future__ import annotations

import math


class StateInputOrder:
    def __init__(self):
        self._latest: dict[tuple[str, str], float] = {}

    def accept(self, domain: str, channel: str, payload: dict) -> bool:
        stamp = payload.get("timestamp")
        if stamp is None:
            return True
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            return False
        stamp = float(stamp)
        if not math.isfinite(stamp):
            return False
        key = (domain, channel)
        if stamp < self._latest.get(key, -math.inf):
            return False
        self._latest[key] = stamp
        return True


def accept_state_input(node, domain: str, channel: str, payload: dict) -> bool:
    """Compatibility wrapper for existing callback harnesses and the ROS shell."""
    guard = getattr(node, "_state_input_order", None)
    if not isinstance(guard, StateInputOrder):
        guard = StateInputOrder()
        node._state_input_order = guard
    accepted = guard.accept(domain, channel, payload)
    if not accepted:
        node._logger.debug(f"Ignored stale/invalid {domain} input for {channel}")
    return accepted
