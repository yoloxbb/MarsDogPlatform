"""Mock perception client for need-driven visual routing.

Provides people, animal, and object observations for behavior routing.

In ROS2, these observations come from ``/perception/vision/task``. Here they
are configurable so Social and Exploration routes work without ROS2/vision.
"""

from __future__ import annotations


class MockPerceptionClient:
    """Simulates ``check_person`` and ``detect_objects`` visual tasks.

    It also remains the standalone person-presence source for emotion
    interaction-mode selection.
    """

    def __init__(self):
        self._person_present: bool = False
        self._person_count: int = 0
        self._person_identity: str = "unknown"
        self._active_target: dict = {}
        self._objects: list[dict] = []

    # ── State Setters (for mock control) ─────────────────────────────────────

    def set_person_present(self, present: bool = True, identity: str = "owner",
                           count: int = 1) -> None:
        """Simulate a person being detected."""
        self._person_present = present
        self._person_count = count if present else 0
        self._person_identity = identity if present else "unknown"
        self._active_target = (
            {
                "identity": identity,
                "is_registered": identity != "unknown",
                "track_id": 1,
            }
            if present
            else {}
        )

    def set_no_person(self) -> None:
        """Simulate no person in view."""
        self._person_present = False
        self._person_count = 0
        self._person_identity = "unknown"
        self._active_target = {}

    def set_objects(self, objects: list[dict]) -> None:
        """Configure virtual ``detect_objects`` results."""
        self._objects = [
            dict(item) for item in objects if isinstance(item, dict)
        ]

    def set_animals(self, animals: list[str | dict]) -> None:
        """Replace visible cat/dog results while preserving other objects."""
        retained = [
            item
            for item in self._objects
            if str(item.get("label", "")).lower() not in ("cat", "dog")
        ]
        normalized = []
        for index, animal in enumerate(animals):
            if isinstance(animal, dict):
                item = dict(animal)
            else:
                item = {
                    "label": str(animal),
                    "confidence": 0.9,
                    "track_id": f"animal-{index + 1}",
                }
            normalized.append(item)
        self._objects = retained + normalized

    def clear_scene(self) -> None:
        """Clear people, animals, and objects from the virtual frame."""
        self.set_no_person()
        self._objects = []

    # ── Service Mock Methods ─────────────────────────────────────────────────

    def check_person(self) -> dict:
        """Simulate a check_person service call.

        Returns a dict with present/count/identity, matching the normalized
        visual-service response used by the behavior adapter.
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

    def detect_objects(self, confidence: float = 0.5) -> list[dict]:
        """Simulate the visual service's ``detect_objects`` task."""
        return [
            dict(item)
            for item in self._objects
            if float(item.get("confidence", 1.0)) >= confidence
        ]
