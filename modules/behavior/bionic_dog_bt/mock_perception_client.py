"""Mock perception client: simulates /perception/perception_task service.

Provides check_person() to determine if a person is visible/interacting.
Used by emotion-triggered behaviors to decide interactive vs solo mode.

In ROS2, this would be a service call to /perception/perception_task
with task_type="check_person". Here we mock it with configurable state.
"""

from __future__ import annotations


class MockPerceptionClient:
    """Simulates the /perception/perception_task ROS2 service.

    Used to check whether there's a person present before executing
    emotion-triggered behaviors. If a person is present, the behavior
    runs in interactive mode (targeting the person). Otherwise, it
    runs in solo expression mode.
    """

    def __init__(self):
        self._person_present: bool = False
        self._person_count: int = 0
        self._person_identity: str = "unknown"
        self._active_target: dict = {}

    # ── State Setters (for mock control) ─────────────────────────────────────

    def set_person_present(self, present: bool = True, identity: str = "owner",
                           count: int = 1) -> None:
        """Simulate a person being detected."""
        self._person_present = present
        self._person_count = count
        self._person_identity = identity
        self._active_target = {
            "identity": identity,
            "is_registered": identity != "unknown",
            "track_id": 1,
        }

    def set_no_person(self) -> None:
        """Simulate no person in view."""
        self._person_present = False
        self._person_count = 0
        self._person_identity = "unknown"
        self._active_target = {}

    # ── Service Mock Methods ─────────────────────────────────────────────────

    def check_person(self) -> dict:
        """Simulate a check_person service call.

        Returns a dict with present/count/identity — mirrors the
        /perception/perception_task result_json format.
        """
        return {
            "present": self._person_present,
            "count": self._person_count,
            "identity": self._person_identity,
            "active_target": dict(self._active_target),
        }

    def is_person_present(self) -> bool:
        """Quick check: is there a person to interact with?"""
        return self._person_present
