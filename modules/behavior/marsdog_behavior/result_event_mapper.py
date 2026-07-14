"""Result Event Mapper — maps behavior execution results to /behavior/result_event.

Publishes structured JSON events for demand-related behaviors (hunger, bladder,
sleep, cleanliness, social, exploration). Also publishes STARTED events.

Non-demand behaviors (pure emotion expressions, voice commands, idle) are excluded
from this topic but can still be logged internally.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from bionic_dog_bt.constants import BEHAVIOR_ACTION_MAP
from bionic_dog_bt.logger import get_logger

_log = get_logger("result_mapper")

# BT internal status → result_type mapping
_RESULT_TYPE_MAP = {
    "SUCCESS":  "COMPLETED",
    "FAILURE":  "FAILED",
    "TIMEOUT":  "TIMEOUT",
    "CANCELED": "INTERRUPTED",
}


class ResultEventMapper:
    """Maps behavior execution outcomes to /behavior/result_event JSON payloads.

    Only publishes for behaviors listed in BEHAVIOR_ACTION_MAP (demand behaviors).
    Pure emotion expressions, voice commands, and idle behaviors are excluded.
    """

    def __init__(self):
        self._seq: int = 0
        self._last_published_event_id: str = ""

    def build_started_event(self, behavior_name: str) -> Optional[str]:
        """Build a STARTED event JSON payload. Returns None if not a demand behavior."""
        mapping = BEHAVIOR_ACTION_MAP.get(behavior_name)
        if mapping is None:
            return None

        action_type, demand_type, default_metadata = mapping
        event_id = f"result-{self._seq:06d}"
        self._seq += 1

        payload = json.dumps({
            "event_id": event_id,
            "timestamp": time.time(),
            "action_type": action_type,
            "demand_type": demand_type,
            "result_type": "STARTED",
            "metadata": dict(default_metadata),
        })
        self._last_published_event_id = event_id
        return payload

    def build_result_event(self, behavior_name: str, status: str) -> Optional[str]:
        """Build a result event JSON payload. Returns None if not a demand behavior."""
        mapping = BEHAVIOR_ACTION_MAP.get(behavior_name)
        if mapping is None:
            return None

        action_type, demand_type, default_metadata = mapping
        result_type = _RESULT_TYPE_MAP.get(status, "FAILED")

        event_id = f"result-{self._seq:06d}"
        self._seq += 1

        payload = json.dumps({
            "event_id": event_id,
            "timestamp": time.time(),
            "action_type": action_type,
            "demand_type": demand_type,
            "result_type": result_type,
            "metadata": dict(default_metadata),
        })
        self._last_published_event_id = event_id

        _log.info(f"/behavior/result_event: {action_type}/{demand_type} → {result_type}")
        return payload

    @property
    def last_published_event_id(self) -> str:
        return self._last_published_event_id


def should_publish_result(behavior_name: str) -> bool:
    """Check if a behavior should generate /behavior/result_event messages."""
    return behavior_name in BEHAVIOR_ACTION_MAP
