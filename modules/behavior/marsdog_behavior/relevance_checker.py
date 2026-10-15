"""Compatibility entrypoint for the shared source-aware BT relevance policy.

Candidate TTL and session/target validity remain owned by their existing gates.
"""
from bionic_dog_bt.relevance import is_trigger_relevant


def is_behavior_relevant(candidate: dict, blackboard) -> bool:
    """Validate unstarted candidates against their authoritative state owner."""
    return is_trigger_relevant(
        candidate.get("behavior_name", ""),
        candidate.get("need_type", ""),
        candidate.get("params", {}),
        blackboard,
    )
