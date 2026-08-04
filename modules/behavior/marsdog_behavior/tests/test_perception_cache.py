from __future__ import annotations

import json
import threading
import time

from marsdog_behavior.perception_client_adapter import PerceptionClientAdapter


class _Message:
    def __init__(self, value: dict) -> None:
        self.data = json.dumps(value)


class _Logger:
    def debug(self, *args, **kwargs) -> None:
        pass


def _adapter() -> PerceptionClientAdapter:
    adapter = object.__new__(PerceptionClientAdapter)
    adapter._ros2_ready = True
    adapter._logger = _Logger()
    adapter._on_visual_event = None
    adapter._person_present = False
    adapter._active_identity = "unknown"
    adapter._cached_humans = []
    adapter._cached_objects = []
    adapter._visual_cache_updated_at = 0.0
    adapter._lock = threading.Lock()
    return adapter


def test_person_cache_expires_when_visual_node_stops_publishing() -> None:
    adapter = _adapter()
    adapter._on_visual_ros2(_Message({
        "humans": [{"track_id": 1, "confidence": 0.9}],
        "active_target": {
            "identity": "owner",
            "tracking_state": "tracking",
            "last_seen_age_ms": 10.0,
        },
    }))
    assert adapter.check_person()["present"] is True

    adapter._visual_cache_updated_at = (
        time.monotonic() - adapter.VISUAL_CACHE_TIMEOUT_SEC - 0.1
    )
    assert adapter.check_person() == {
        "present": False,
        "count": 0,
        "identity": "unknown",
    }
    assert adapter.is_person_present() is False
    assert adapter.get_active_identity() == "unknown"


def test_temporarily_lost_identity_is_not_a_present_person() -> None:
    adapter = _adapter()
    adapter._on_visual_ros2(_Message({
        "humans": [],
        "active_target": {
            "identity": "owner",
            "is_registered": True,
            "tracking_state": "temporarily_lost",
            "last_seen_age_ms": 600.0,
        },
    }))
    assert adapter.check_person()["present"] is False
