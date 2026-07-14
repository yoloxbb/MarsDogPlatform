"""State Event Refiner — coarse event + state → fine-grained intent.

Handles cases where the upstream node publishes coarse events
(e.g. NEED_SOCIAL_TRIGGERED) but the product requires fine-grained
distinctions based on value ranges and perception targets.

All temporary numeric thresholds are centralized here. They do NOT
leak into selector, candidate_pool, or tree node modules.
"""

from __future__ import annotations

from typing import Optional

from bionic_dog_bt.logger import get_logger

_log = get_logger("refiner")


class StateEventRefiner:
    """Refines coarse upstream events into fine-grained intents."""

    def __init__(self, intent_mapper=None):
        self._mapper = intent_mapper

    def refine_social(self, social_value: float,
                      has_animal_target: bool = False,
                      has_human_target: bool = False) -> Optional[dict]:
        """Refine NEED_SOCIAL_TRIGGERED based on value and perception targets.

        Returns dict with: intent, behavior_name, variant, target_required,
        interactive, priority_level, sub_priority.
        Returns None if no refinement needed (let intent_mapper handle it).
        """

        # ── 61–70: boundary test / resource interaction ──────────────────
        if social_value <= 70:
            if has_animal_target:
                return {
                    "intent": "animal_boundary_test",
                    "behavior_name": "testAnimalBoundary",
                    "variant": "boundary",
                    "target_required": True,
                    "interactive": True,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_BOUNDARY_TEST",
                        "demand_type": "Social",
                    },
                }
            elif has_human_target:
                return {
                    "intent": "human_resource_interaction",
                    "behavior_name": "requestResourceFromHuman",
                    "variant": "resource",
                    "target_required": True,
                    "interactive": True,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_RESOURCE_SHARE",
                        "demand_type": "Social",
                    },
                }
            else:
                return {
                    "intent": "social_seek",
                    "behavior_name": "seekHumanInteraction",
                    "variant": "general",
                    "target_required": False,
                    "interactive": False,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_ATTENTION_SEEK",
                        "demand_type": "Social",
                    },
                }

        # ── 71–85: greet / attention ─────────────────────────────────────
        elif social_value <= 85:
            if has_animal_target:
                return {
                    "intent": "animal_social_greet",
                    "behavior_name": "greetAnimal",
                    "variant": "greeting",
                    "target_required": True,
                    "interactive": True,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_SOCIAL_GREET",
                        "demand_type": "Social",
                    },
                }
            elif has_human_target:
                return {
                    "intent": "human_attention_interaction",
                    "behavior_name": "seekHumanInteraction",
                    "variant": "attention",
                    "target_required": True,
                    "interactive": True,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_ATTENTION_SEEK",
                        "demand_type": "Social",
                    },
                }
            else:
                return {
                    "intent": "social_seek",
                    "behavior_name": "seekHumanInteraction",
                    "variant": "seeking",
                    "target_required": False,
                    "interactive": False,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_ATTENTION_SEEK",
                        "demand_type": "Social",
                    },
                }

        # ── 86–100: play invite ──────────────────────────────────────────
        else:
            if has_animal_target:
                return {
                    "intent": "animal_play_invite",
                    "behavior_name": "inviteAnimalToPlay",
                    "variant": "play",
                    "target_required": True,
                    "interactive": True,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_PLAY_INVITE",
                        "demand_type": "Social",
                    },
                }
            elif has_human_target:
                return {
                    "intent": "human_play_invite",
                    "behavior_name": "inviteHumanToPlay",
                    "variant": "play",
                    "target_required": True,
                    "interactive": True,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_PLAY_INVITE",
                        "demand_type": "Social",
                    },
                }
            else:
                return {
                    "intent": "social_seek",
                    "behavior_name": "seekHumanInteraction",
                    "variant": "seeking",
                    "target_required": False,
                    "interactive": False,
                    "priority_level": 4,
                    "sub_priority": 0,
                    "result_mapping": {
                        "action_type": "ACTION_ATTENTION_SEEK",
                        "demand_type": "Social",
                    },
                }
