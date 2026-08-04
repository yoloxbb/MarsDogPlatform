"""Interaction Resolver — determines interactive vs solo execution mode.

Checks whether a person is present before executing emotion-triggered
behaviors. Uses cached state from /perception/visual_event for fast
lookup, falling back to /perception/perception_task service call only
when cache is stale or unavailable.
"""

from __future__ import annotations

from typing import Optional


class InteractionResolver:
    """Resolves whether the current execution context is interactive or solo.

    Wraps a perception client (MockPerceptionClient or PerceptionClientAdapter)
    and provides a consistent interface for check_person() calls.
    """

    def __init__(self, perception_client):
        """Args:
            perception_client: Object with check_person() and is_person_present()
        """
        self._perception = perception_client

    def check_person(self) -> dict:
        """Check if a person is present. Returns {present, count, identity}."""
        return self._perception.check_person()

    def is_person_present(self) -> bool:
        """Quick check — is a person currently visible?"""
        return self._perception.is_person_present()

    def resolve_interaction(self, behavior_name: str, params: dict,
                            need_type: str) -> dict:
        """Resolve whether the behavior should run in interactive or solo mode.

        Only applies to emotion-triggered behaviors. Direct audio events
        already have their source set and shouldn't be overridden.

        Args:
            behavior_name: name of the behavior
            params: behavior params dict (may be modified in place)
            need_type: behavior trigger type

        Returns:
            Updated params dict with 'interactive' and 'target_identity' set.
        """
        if need_type != "emotional":
            return params

        # Direct audio events already carry their interaction context.
        if params.get("source") == "audio_direct":
            return params

        person = self.check_person()
        if person.get("present", False):
            params["interactive"] = True
            params["target_identity"] = person.get("identity", "unknown")
        else:
            params["interactive"] = False

        return params
