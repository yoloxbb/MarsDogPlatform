"""Constants for priority levels, status values, and interrupt policies."""

# ── Priority Levels ──────────────────────────────────────────────────────────
# Lower number = higher priority
PRIORITY_LEVELS = {
    "SYSTEM": 0,
    "EXTERNAL_INTERACTION": 1,
    "PHYSIO_URGENT": 2,
    "PHYSIO_NORMAL": 3,
    "PSYCHOLOGICAL": 4,
    "EMOTION_EXPRESSION": 5,
    "IDLE": 6,
}

LEVEL_NAMES = {
    0: "Lv0_System",
    1: "Lv1_ExternalInteraction",
    2: "Lv2_PhysioUrgent",
    3: "Lv3_PhysioNormal",
    4: "Lv4_Psychological",
    5: "Lv5_EmotionExpression",
    6: "Lv6_Idle",
}

# ── Behavior Tree Status ─────────────────────────────────────────────────────
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"
STATUS_RUNNING = "RUNNING"
STATUS_CANCELED = "CANCELED"

# ── ExecuteBehavior Goal lifecycle ──────────────────────────────────────────
# Cancellation acknowledgement is deliberately not a terminal state.  Tree
# keeps ownership of the goal until the Action result is observed.
GOAL_SENDING = "SENDING"
GOAL_RUNNING = "RUNNING"
GOAL_CANCEL_REQUESTED = "CANCEL_REQUESTED"
GOAL_TERMINAL = "TERMINAL"

# ── Interrupt Policies ───────────────────────────────────────────────────────
INTERRUPT_IMMEDIATE = "immediate"
INTERRUPT_SAFE_POINT = "safe_point"
INTERRUPT_NON_INTERRUPTIBLE = "non_interruptible"

# ── Preemption ───────────────────────────────────────────────────────────────
# Min value delta required for same-level preemption
SAME_LEVEL_PREEMPTION_DELTA = 15

# ── Emotion → Behavior Mapping ───────────────────────────────────────────────
# Maps behavior_name → emotion_name for relevance checking.
# Emotion names align with ROS2 /emotion/state fields.
EMOTION_BEHAVIOR_MAP = {
    "expressCalm": "Calm",
    "expressCalmWithHuman": "Calm",
    "expressCalmInPlaceWithHuman": "Calm",
    "expressCalmAlone": "Calm",
    "expressJoy": "Joy",
    "expressJoyWithHuman": "Joy",
    "expressJoyInPlaceWithHuman": "Joy",
    "expressJoyAlone": "Joy",
    "expressExcitement": "Excite",
    "expressExcitementWithHuman": "Excite",
    "expressExcitementInPlaceWithHuman": "Excite",
    "expressExcitementAlone": "Excite",
    "expressAnxiety": "Anxiety",
    "expressAnxietyWithHuman": "Anxiety",
    "expressAnxietyInPlaceWithHuman": "Anxiety",
    "expressAnxietyAlone": "Anxiety",
    "expressFear": "Fear",
    "expressFearWithHuman": "Fear",
    "expressFearInPlaceWithHuman": "Fear",
    "expressFearAlone": "Fear",
    "expressCuriosity": "Curious",
    "expressCuriosityWithHuman": "Curious",
    "expressCuriosityInPlaceWithHuman": "Curious",
    "expressCuriosityAlone": "Curious",
}

# ── Need → Behavior Mapping ──────────────────────────────────────────────────
# Maps behavior_name → need_name for relevance checking.
# Need names align with ROS2 /internal_need/state demands fields.
NEED_BEHAVIOR_MAP = {
    "seek_food_or_water": "Hunger",
    "eatNormally": "Hunger",
    "eatExcitedly": "Hunger",
    "seekFood": "Hunger",
    "seekFoodUrgently": "Hunger",
    "excretion_request": "Bladder",
    "barkShortAlert": "Bladder",
    "defecate": "Bladder",
    "sleep_request": "Sleepiness",
    "sleepOnSide": "Sleepiness",
    "sleepNow": "Sleepiness",
    "clean_self": "Cleanliness",
    "lickPaws": "Cleanliness",
    "cleanSelf": "Cleanliness",
    "restInPlace": "Energy",
    "recharge": "Energy",
    "seek_social_interaction": "Social",
    "seekHumanInteraction": "Social",
    "seekInteraction": "Social",
    "testAnimalBoundary": "Social",
    "greetAnimal": "Social",
    "inviteAnimalToPlay": "Social",
    "inviteHumanToPlay": "Social",
    "explore_environment": "Exploration",
    "exploreRoom": "Exploration",
    "inspectObject": "Exploration",
    "inspectFamiliarPlayItem": "Exploration",
    "inspectTrashCan": "Exploration",
    "inspectDeliveryBox": "Exploration",
    "inspectTissuePaper": "Exploration",
    "inspectDoor": "Exploration",
    "inspectDogFood": "Exploration",
}

# ── Emotion Defaults (ROS2-aligned) ──────────────────────────────────────────
# trigger_threshold values are defined by the emotion V2 single-threshold
# protocol. Decay rates are only used by the standalone simulator; production
# state is mirrored from /emotion/state.
DEFAULT_EMOTION_CONFIG = {
    "Joy":      {"trigger_threshold": 30.0, "decay_rate": 2.0},
    "Excite":   {"trigger_threshold": 40.0, "decay_rate": 3.0},
    "Anxiety":  {"trigger_threshold": 25.0, "decay_rate": 1.5},
    "Fear":     {"trigger_threshold": 30.0, "decay_rate": 4.0},
    "Curious":  {"trigger_threshold": 20.0, "decay_rate": 2.0},
    "Calm":     {"trigger_threshold": 0.0, "decay_rate": 0.0},
}

# Lower = higher priority when multiple emotions trigger simultaneously
# Fear > Anxiety > Excite > Joy > Curious > Calm
EMOTION_PRIORITY = {
    "Fear": 0,
    "Anxiety": 1,
    "Excite": 2,
    "Joy": 3,
    "Curious": 4,
    "Calm": 5,
}

EMOTION_V2_EVENT_TO_NAME = {
    "EMO_JOY_TRIGGERED": "Joy",
    "EMO_EXCITE_TRIGGERED": "Excite",
    "EMO_ANXIETY_TRIGGERED": "Anxiety",
    "EMO_FEAR_TRIGGERED": "Fear",
    "EMO_CURIOUS_TRIGGERED": "Curious",
    "EMO_CALM_TRIGGERED": "Calm",
}

# ── Need Defaults (ROS2-aligned) ─────────────────────────────────────────────
# V2 uses demand intensity for every channel, including Energy. All operators
# are strict ``gt``. Missing urgent/overflow lines are represented by None.
DEFAULT_NEED_CONFIG = {
    "Hunger":      {"trigger_threshold": 70, "trigger_op": "gt",
                    "overflow_threshold": 90, "overflow_op": "gt"},
    "Bladder":     {"trigger_threshold": 75, "trigger_op": "gt",
                    "overflow_threshold": None, "overflow_op": None},
    "Sleepiness":  {"trigger_threshold": 65, "trigger_op": "gt",
                    "overflow_threshold": 90, "overflow_op": "gt"},
    "Cleanliness": {"trigger_threshold": 70, "trigger_op": "gt",
                    "overflow_threshold": None, "overflow_op": None},
    "Energy":      {"trigger_threshold": 80, "trigger_op": "gt",
                    "overflow_threshold": 90, "overflow_op": "gt"},
    "Social":      {"trigger_threshold": 60, "trigger_op": "gt",
                    "urgent_threshold": 70, "urgent_op": "gt",
                    "overflow_threshold": 85, "overflow_op": "gt"},
    "Exploration": {"trigger_threshold": 60, "trigger_op": "gt",
                    "overflow_threshold": None, "overflow_op": None},
}

# ── Need Level Constants ─────────────────────────────────────────────────────
NEED_LEVEL_NORMAL = "NORMAL"
NEED_LEVEL_TRIGGERED = "TRIGGERED"
NEED_LEVEL_URGENT = "URGENT"
NEED_LEVEL_OVERFLOW = "OVERFLOW"

NEED_V2_ACTIVE_LEVELS = {
    "Hunger": frozenset({NEED_LEVEL_TRIGGERED, NEED_LEVEL_OVERFLOW}),
    "Bladder": frozenset({NEED_LEVEL_TRIGGERED}),
    "Sleepiness": frozenset({NEED_LEVEL_TRIGGERED, NEED_LEVEL_OVERFLOW}),
    "Cleanliness": frozenset({NEED_LEVEL_TRIGGERED}),
    "Energy": frozenset({NEED_LEVEL_TRIGGERED, NEED_LEVEL_OVERFLOW}),
    "Social": frozenset({
        NEED_LEVEL_TRIGGERED,
        NEED_LEVEL_URGENT,
        NEED_LEVEL_OVERFLOW,
    }),
    "Exploration": frozenset({NEED_LEVEL_TRIGGERED}),
}

NEED_V2_EVENT_TO_STATE = {
    **{
        f"NEED_{demand.upper()}_{level}": (demand, level)
        for demand, levels in NEED_V2_ACTIVE_LEVELS.items()
        for level in levels
    },
    **{
        f"NEED_{demand.upper()}_RECOVERED": (demand, NEED_LEVEL_NORMAL)
        for demand in NEED_V2_ACTIVE_LEVELS
    },
}

# ── Need event → Behavior Mapping (standalone/mock only) ────────────────────
# Exact event types are intentionally duplicated from event_intent_map.yaml so
# the pure-Python mock exercises the same event-strength semantics.
NEED_EVENT_BEHAVIOR_MAP = {
    "NEED_HUNGER_TRIGGERED": {
        "behavior_name": "eatNormally",
        "need_name": "Hunger",
        "priority_level": 3,
        "need_type": "physiological",
        "variant": "food_visible",
        "visual_routes": {
            "dog_food": {
                "behavior_name": "eatNormally",
                "variant": "food_visible",
            },
            "no_dog_food": {
                "behavior_name": "seekFood",
                "variant": "food_search",
            },
        },
    },
    "NEED_HUNGER_OVERFLOW": {
        "behavior_name": "eatExcitedly",
        "need_name": "Hunger",
        "priority_level": 3,
        "need_type": "physiological",
        "variant": "food_visible_urgent",
        "visual_routes": {
            "dog_food": {
                "behavior_name": "eatExcitedly",
                "variant": "food_visible_urgent",
            },
            "no_dog_food": {
                "behavior_name": "seekFoodUrgently",
                "variant": "food_search_urgent",
                "executor_behavior_name": "seekFood",
            },
        },
    },
    "NEED_BLADDER_TRIGGERED": {
        "behavior_name": "barkShortAlert",
        "need_name": "Bladder",
        "priority_level": 2,
        "need_type": "physiological_urgent",
        "variant": "request",
    },
    "NEED_SLEEPINESS_TRIGGERED": {
        "behavior_name": "sleepOnSide",
        "need_name": "Sleepiness",
        "priority_level": 2,
        "need_type": "physiological_urgent",
        "variant": "light",
    },
    "NEED_SLEEPINESS_OVERFLOW": {
        "behavior_name": "sleepNow",
        "need_name": "Sleepiness",
        "priority_level": 2,
        "need_type": "physiological_urgent",
        "variant": "deep",
    },
    "NEED_CLEANLINESS_TRIGGERED": {
        "behavior_name": "lickPaws",
        "need_name": "Cleanliness",
        "priority_level": 3,
        "need_type": "physiological",
        "variant": "light",
    },
    "NEED_ENERGY_TRIGGERED": {
        "behavior_name": "restInPlace",
        "need_name": "Energy",
        "priority_level": 0,
        "need_type": "system",
        "variant": "low_energy",
    },
    "NEED_ENERGY_OVERFLOW": {
        "behavior_name": "recharge",
        "need_name": "Energy",
        "priority_level": 0,
        "need_type": "system",
        "variant": "critical",
    },
    "NEED_SOCIAL_TRIGGERED": {
        "behavior_name": "seekHumanInteraction",
        "need_name": "Social",
        "priority_level": 4,
        "need_type": "psychological",
        "sub_priority": 2,
        "variant": "seek",
        "visual_routes": {
            "human": {
                "behavior_name": "seekHumanInteraction",
                "variant": "human_seek",
            },
            "animal": {
                "behavior_name": "testAnimalBoundary",
                "variant": "animal_boundary",
            },
        },
    },
    "NEED_SOCIAL_URGENT": {
        "behavior_name": "seekInteraction",
        "need_name": "Social",
        "priority_level": 4,
        "need_type": "psychological",
        "sub_priority": 1,
        "variant": "engage",
        "visual_routes": {
            "human": {
                "behavior_name": "seekInteraction",
                "variant": "human_engage",
            },
            "animal": {
                "behavior_name": "greetAnimal",
                "variant": "animal_greet",
            },
        },
    },
    "NEED_SOCIAL_OVERFLOW": {
        "behavior_name": "inviteHumanToPlay",
        "need_name": "Social",
        "priority_level": 4,
        "need_type": "psychological",
        "sub_priority": 0,
        "variant": "intense",
        "visual_routes": {
            "human": {
                "behavior_name": "inviteHumanToPlay",
                "variant": "human_play",
            },
            "animal": {
                "behavior_name": "inviteAnimalToPlay",
                "variant": "animal_play",
            },
        },
    },
    "NEED_EXPLORATION_TRIGGERED": {
        "behavior_name": "exploreRoom",
        "need_name": "Exploration",
        "priority_level": 4,
        "need_type": "psychological",
        "variant": "room",
        "visual_routes": {
            "play_item": {
                "behavior_name": "inspectFamiliarPlayItem",
                "variant": "play_item",
            },
            "trash_can": {
                "behavior_name": "inspectTrashCan",
                "variant": "trash_can",
            },
            "delivery_box": {
                "behavior_name": "inspectDeliveryBox",
                "variant": "delivery_box",
            },
            "tissue": {
                "behavior_name": "inspectTissuePaper",
                "variant": "tissue",
            },
            "door": {
                "behavior_name": "inspectDoor",
                "variant": "door",
            },
            "dog_food": {
                "behavior_name": "inspectDogFood",
                "variant": "dog_food",
            },
            "unfamiliar_object": {
                "behavior_name": "inspectObject",
                "variant": "unfamiliar",
            },
            "empty": {
                "behavior_name": "exploreRoom",
                "variant": "room",
            },
        },
    },
}

# ── Emotion event → Behavior Mapping (standalone/mock only) ─────────────────
EMOTION_EVENT_BEHAVIOR_MAP = {
    "EMO_CALM_TRIGGERED": {
        "emotion_name": "Calm",
        "level": "LOW",
        "variant": "calm",
        "routes": {
            "human": {
                "behavior_name": "expressCalmWithHuman",
            },
            "solo": {
                "behavior_name": "expressCalmAlone",
            },
        },
    },
    "EMO_JOY_TRIGGERED": {
        "emotion_name": "Joy",
        "level": "LOW",
        "variant": "joy",
        "routes": {
            "human": {
                "behavior_name": "expressJoyWithHuman",
            },
            "solo": {
                "behavior_name": "expressJoyAlone",
            },
        },
    },
    "EMO_EXCITE_TRIGGERED": {
        "emotion_name": "Excite",
        "level": "LOW",
        "variant": "excitement",
        "routes": {
            "human": {
                "behavior_name": "expressExcitementWithHuman",
            },
            "solo": {
                "behavior_name": "expressExcitementAlone",
            },
        },
    },
    "EMO_ANXIETY_TRIGGERED": {
        "emotion_name": "Anxiety",
        "level": "LOW",
        "variant": "anxiety",
        "routes": {
            "human": {
                "behavior_name": "expressAnxietyWithHuman",
            },
            "solo": {
                "behavior_name": "expressAnxietyAlone",
            },
        },
    },
    "EMO_FEAR_TRIGGERED": {
        "emotion_name": "Fear",
        "level": "LOW",
        "variant": "fear",
        "routes": {
            "human": {
                "behavior_name": "expressFearWithHuman",
            },
            "solo": {
                "behavior_name": "expressFearAlone",
            },
        },
    },
    "EMO_CURIOUS_TRIGGERED": {
        "emotion_name": "Curious",
        "level": "LOW",
        "variant": "curiosity",
        "routes": {
            "human": {
                "behavior_name": "expressCuriosityWithHuman",
            },
            "solo": {
                "behavior_name": "expressCuriosityAlone",
            },
        },
    },
}

# ── Voice event → Behavior Mapping (standalone/mock only) ───────────────────
VOICE_EVENT_BEHAVIOR_MAP = {
    "EVT_VOICE_WAKEUP": "respond_owner_call",
    "EVT_VOICE_COMMAND_WALK": "walk_to_random_point",
    "EVT_VOICE_COMMAND_PLAY_ALONE": "play_alone",
    "EVT_VOICE_COMMAND_GO_OUT": "go_out_to_play",
    "EVT_VOICE_COMMAND_GO_HOME": "go_home",
    "EVT_VOICE_COMMAND_APPROACH": "approach_owner",
    "EVT_VOICE_COMMAND_BACK_UP": "back_up",
    "EVT_VOICE_COMMAND_SIT": "sit_down",
    "EVT_VOICE_COMMAND_LIE_DOWN": "lie_down",
    "EVT_VOICE_COMMAND_STAND_UP": "stand_up",
    "EVT_VOICE_COMMAND_STAND_STILL": "stand_still",
    "EVT_VOICE_COMMAND_HOLD_POSITION": "hold_position",
    "EVT_VOICE_COMMAND_WAIT": "wait_in_place",
    "EVT_VOICE_COMMAND_COME": "come_to_owner",
    "EVT_VOICE_COMMAND_FOLLOW": "follow_owner",
    "EVT_VOICE_COMMAND_SHAKE_HAND": "give_paw",
    "EVT_VOICE_COMMAND_HIGH_FIVE": "high_five",
    "EVT_VOICE_COMMAND_ROLL_OVER": "roll_over",
    "EVT_VOICE_COMMAND_SPIN": "spin_around",
    "EVT_VOICE_COMMAND_RETURN": "return_to_owner",
    "EVT_VOICE_COMMAND_DROP": "drop_object",
    "EVT_VOICE_COMMAND_QUIET": "quiet",
    "EVT_VOICE_COMMAND_TOILET": "barkShortAlert",
    "EVT_VOICE_COMMAND_CLEAN": "lickPaws",
    "EVT_VOICE_COMMAND_SLEEP": "sleepOnSide",
    "EVT_VOICE_COMMAND_PLAY_DEAD": "play_dead",
    "EVT_VOICE_COMMAND_BRING": "bring_object",
    "EVT_VOICE_COMMAND_FETCH": "fetch_object",
    "EVT_VOICE_COMMAND_STOP": "emergency_stop",
}

# ── Behavior → Action Result Mapping ─────────────────────────────────────────
# Maps behavior_name → (action_type, demand_type, metadata_keys)
# Only behaviors in this map get published to /behavior/result_event.
# Pure emotion expressions are NOT included — result_mapping=null.
BEHAVIOR_ACTION_MAP = {
    # Physiological
    "eatNormally": ("ACTION_EAT", "Hunger",
                    {"foodType": "NormalFood", "portions": 1, "eatEfficiency": "Full"}),
    "eatExcitedly": ("ACTION_EAT", "Hunger",
                     {"foodType": "NormalFood", "portions": 1, "eatEfficiency": "Excited"}),
    "seekFood": ("ACTION_FOOD_SEEK", "Hunger",
                 {"searchUrgency": "triggered"}),
    "seekFoodUrgently": ("ACTION_FOOD_SEEK", "Hunger",
                         {"searchUrgency": "overflow"}),
    "barkShortAlert": ("ACTION_DEFECATE", "Bladder",
                       {"eliminationMode": "request", "urgency": "triggered"}),
    "defecate": ("ACTION_DEFECATE", "Bladder", {}),
    "sleepOnSide": ("ACTION_SLEEP", "Sleepiness", {"sleepDepth": "light"}),
    "sleepNow": ("ACTION_SLEEP", "Sleepiness", {"sleepDepth": "deep"}),
    "lickPaws": ("ACTION_GROOM", "Cleanliness", {"groomIntensity": "light"}),
    "cleanSelf": ("ACTION_GROOM", "Cleanliness", {"groomIntensity": "thorough"}),
    "restInPlace": ("ACTION_RECHARGE", "Energy", {"recoveryMode": "passive"}),
    "recharge": ("ACTION_RECHARGE", "Energy", {"recoveryMode": "charging"}),
    # Psychological
    "seekHumanInteraction": ("ACTION_ATTENTION_SEEK", "Social",
                              {"socialOutcome": "OwnerInteraction"}),
    "seekInteraction": ("ACTION_ATTENTION_SEEK", "Social",
                        {"socialOutcome": "ActiveEngagement"}),
    "requestResourceFromHuman": ("ACTION_RESOURCE_SHARE", "Social", {}),
    "testAnimalBoundary": ("ACTION_BOUNDARY_TEST", "Social", {}),
    "greetAnimal": ("ACTION_SOCIAL_GREET", "Social", {}),
    "inviteAnimalToPlay": ("ACTION_PLAY_INVITE", "Social", {}),
    "inviteHumanToPlay": ("ACTION_PLAY_INVITE", "Social", {}),
    "exploreRoom": ("ACTION_SPACE_EXPLORE", "Exploration", {}),
    "inspectObject": ("ACTION_OBJECT_EXPLORE", "Exploration", {}),
    "inspectFamiliarPlayItem": (
        "ACTION_OBJECT_EXPLORE", "Exploration",
        {"objectCategory": "play_item"},
    ),
    "inspectTrashCan": (
        "ACTION_OBJECT_EXPLORE", "Exploration",
        {"objectCategory": "trash_can"},
    ),
    "inspectDeliveryBox": (
        "ACTION_OBJECT_EXPLORE", "Exploration",
        {"objectCategory": "delivery_box"},
    ),
    "inspectTissuePaper": (
        "ACTION_OBJECT_EXPLORE", "Exploration",
        {"objectCategory": "tissue"},
    ),
    "inspectDoor": (
        "ACTION_OBJECT_EXPLORE", "Exploration",
        {"objectCategory": "door"},
    ),
    "inspectDogFood": (
        "ACTION_OBJECT_EXPLORE", "Exploration",
        {"objectCategory": "dog_food"},
    ),
    # Legacy aliases (kept for backward compat)
    "seek_food_or_water": ("ACTION_EAT", "Hunger",
                           {"foodType": "NormalFood", "portions": 1, "eatEfficiency": "Full"}),
    "excretion_request": ("ACTION_DEFECATE", "Bladder", {}),
    "sleep_request": ("ACTION_SLEEP", "Sleepiness", {}),
    "clean_self": ("ACTION_GROOM", "Cleanliness", {}),
    "seek_social_interaction": ("ACTION_ATTENTION_SEEK", "Social",
                                {"socialOutcome": "OwnerInteraction"}),
    "explore_environment": ("ACTION_SPACE_EXPLORE", "Exploration", {}),
}

# ── Default Behaviors ────────────────────────────────────────────────────────
DEFAULT_IDLE_BEHAVIOR = "idle_look_around"
