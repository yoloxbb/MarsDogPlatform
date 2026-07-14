"""Action catalog: maps behavior_name → randomized action sequences.

.. deprecated::
    This module is DEPRECATED. Specific action sequences belong in marsdog_action_executor.
    Kept ONLY for MockActionExecutor fallback during development/testing.

Each behavior has multiple phases. Each phase has a pool of possible
action IDs. The executor randomly picks one action per phase at goal
creation time, so the same behavior looks slightly different each run.

Organized by ROS2 event categories:
  - 生理需求: hunger, excretion, grooming, sleep, energy
  - 心理需求: social_animal, social_human, exploration
  - 情绪表达: happy, fear, curiosity
  - 外部交互: owner_call, touch_head, danger, emergency
  - 空闲: idle

Each phase spec: {
    "phase": str,           # phase name for logging
    "duration": (min, max), # seconds, uniform random
    "safe_to_interrupt": bool,
    "actions": [str, ...],  # pool of action IDs, one randomly picked
}
"""

from __future__ import annotations

import random
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Action Catalog
# ═══════════════════════════════════════════════════════════════════════════════

BEHAVIOR_ACTION_CATALOG: dict[str, list[dict]] = {

    # ── Lv3: 饥渴 >70 正常进食 ──────────────────────────────────────────────
    "seek_food_or_water": [
        {
            "phase": "准备动作",
            "duration": (2.0, 4.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_SNIFF_BOWL_EDGE",
                "ACT_PAW_AT_BOWL",
                "ACT_SIT_OR_LIE_BY_BOWL",
            ],
        },
        {
            "phase": "进食动作",
            "duration": (3.0, 8.0),
            "safe_to_interrupt": False,
            "actions": [
                "ACT_LICK_FOOD",
                "ACT_CHEW_OR_CARRY_FOOD",
                "ACT_SCRATCH_FOOD",
                "ACT_LICK_LIPS_AND_SWALLOW",
                "ACT_TURN_HEAD_AND_WIPE_MOUTH",
            ],
        },
        {
            "phase": "中途互动",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_PAUSE_AND_LOOK_AT_OWNER",
                "ACT_CHASE_ROLLING_FOOD",
                "ACT_CHANGE_POSTURE",
                "ACT_GROWL_WHILE_EATING",
                "ACT_BURP",
            ],
        },
        {
            "phase": "结束动作",
            "duration": (1.0, 2.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_LICK_LIPS_OR_NOSE",
                "ACT_SHAKE_HEAD",
                "ACT_WALK_AWAY_OR_LIE_DOWN",
                "ACT_SNIFF_GROUND_FOR_CRUMBS",
            ],
        },
    ],

    # ── 饥渴 >90 激动进食 ──────────────────────────────────────────────────
    "seek_food_or_water_urgent": [
        {
            "phase": "激动进食",
            "duration": (2.0, 5.0),
            "safe_to_interrupt": False,
            "actions": [
                "ACT_FAST_LICK_AND_SWALLOW",
            ],
        },
    ],

    # ── Lv1: 排泄 ───────────────────────────────────────────────────────────
    "excretion_request": [
        {
            "phase": "准备动作",
            "duration": (3.0, 8.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_SNIFF_AND_CIRCLE",
                "ACT_SCRATCH_GROUND",
                "ACT_SQUAT_TO_PEE",
                "ACT_SQUAT_TO_POOP",
                "ACT_HESITATE",
            ],
        },
        {
            "phase": "排泄中",
            "duration": (3.0, 6.0),
            "safe_to_interrupt": False,
            "actions": [
                "ACT_TENSE_BODY",
                "ACT_TAIL_MOVEMENT",
                "ACT_SLIGHT_TREMOR",
                "ACT_LOWER_HEAD_OR_TURN",
            ],
        },
        {
            "phase": "结束动作",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_STAND_UP_WITH_HIND_LEGS",
                "ACT_SCRATCH_SOIL_OR_GROUND",
                "ACT_SNIFF_EXCREMENT",
                "ACT_WALK_AWAY_OR_SHAKE_HEAD",
            ],
        },
    ],

    # ── Lv3: 清洁 ───────────────────────────────────────────────────────────
    "clean_self": [
        {
            "phase": "处理毛发",
            "duration": (2.0, 6.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_LICK_PAWS_OR_FUR",
                "ACT_SCRATCH",
                "ACT_SHAKE_OFF_WATER",
                "ACT_STRETCH_LAZILY",
                "ACT_ROLL_OVER",
                "ACT_RUB_AGAINST_OBJECT",
                "ACT_PANT",
            ],
        },
    ],

    # ── Lv1: 困倦/睡觉 ─────────────────────────────────────────────────────
    "sleep_request": [
        {
            "phase": "准备入睡",
            "duration": (2.0, 5.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_CIRCLE_AROUND",
                "ACT_SCRATCH_BED_OR_GROUND",
                "ACT_LIE_ON_SIDE_AND_STRETCH",
                "ACT_LICK_FUR_OR_PAWS",
            ],
        },
        {
            "phase": "浅睡",
            "duration": (5.0, 15.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_FLIP_BODY",
                "ACT_WHINE_SOFTLY",
                "ACT_TWITCH_OR_KICK_LEGS",
                "ACT_SHAKE_HEAD_OR_SMACK_LIPS",
                "ACT_WAG_TAIL",
                "ACT_YAWN",
            ],
        },
        {
            "phase": "起床",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_GETUP_CRAWL",
                "ACT_GETUP_ROLL",
                "ACT_GETUP_BOUNCE",
                "ACT_GETUP_STRETCH",
                "ACT_GETUP_SIT",
            ],
        },
    ],

    # ── 精力低 <20 ──────────────────────────────────────────────────────────
    "energy_low": [
        {
            "phase": "低能量表现",
            "duration": (2.0, 5.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_PANT_IN_PLACE",
                "ACT_RESIST_WALKING",
                "ACT_SLOW_MOVEMENT",
            ],
        },
    ],

    # ── 精力低 <10 ──────────────────────────────────────────────────────────
    "energy_critical": [
        {
            "phase": "紧急充电",
            "duration": (3.0, 8.0),
            "safe_to_interrupt": False,
            "actions": [
                "ACT_RETURN_TO_CHARGER",
                "ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER",
            ],
        },
    ],

    # ── Lv4: 社交 — 狗与动物互动 ───────────────────────────────────────────
    "seek_social_interaction": [
        {
            "phase": "社交问候",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_SNIFF_FACE_OR_EARS",
                "ACT_SNIFF_BUTT_OR_TAIL",
                "ACT_TOUCH_NOSE_OR_HEAD_GENTLY",
                "ACT_APPROACH_SLOWLY_SIDEWAYS",
                "ACT_LOWER_HEAD_FLOP_EARS_WAG_TAIL",
                "ACT_LIE_BESIDE_OTHER_ANIMAL",
            ],
        },
        {
            "phase": "邀请玩耍",
            "duration": (2.0, 5.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_PLAY_BOW",
                "ACT_CARRY_AND_SHAKE_OBJECT",
                "ACT_POUNCE_GENTLY",
                "ACT_RUN_IN_CIRCLES_OR_CHASE",
                "ACT_PAW_GENTLY_AT_OTHER",
            ],
        },
    ],

    # ── Lv4: 社交 — 狗与人互动（关注互动）──────────────────────────────────
    "seek_social_interaction_human": [
        {
            "phase": "关注互动",
            "duration": (1.0, 4.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_SEARCH_FOR_PERSON",
                "ACT_RUB_AGAINST_LEG_OR_LEAN",
                "ACT_NUDGE_HAND_WITH_HEAD",
                "ACT_SIT_OR_LIE_AT_FEET",
                "ACT_LICK_HAND_OR_FACE",
                "ACT_DROP_TOY_IN_FRONT_OF_OWNER",
                "ACT_WHINE_OR_BARK_SOFTLY",
                "ACT_PAW_AT_ARM_OR_PANTS",
                "ACT_JUMP_ON_PERSON",
                "ACT_FOLLOW_AND_CLING",
            ],
        },
        {
            "phase": "邀请玩耍",
            "duration": (2.0, 5.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_PLAY_BOW_INVITE",
                "ACT_SHAKE_TOY_WITH_MOUTH",
                "ACT_RUN_IN_CIRCLES_OR_ZOOMIES",
                "ACT_NIP_GENTLY_AT_PANTS_OR_HAND",
                "ACT_PLACE_PAW_ON_KNEE",
            ],
        },
    ],

    # ── Lv4: 探索 — 空间探索 ───────────────────────────────────────────────
    "explore_environment": [
        {
            "phase": "空间探索",
            "duration": (3.0, 8.0),
            "safe_to_interrupt": False,
            "actions": [
                "ACT_TROT_AND_LOOK_AROUND",
                "ACT_WALK_SLOWLY_AND_SNIFF_GROUND",
                "ACT_CRAWL_THROUGH_LOW_GAP",
                "ACT_STAND_AND_SCRATCH_HIGH",
                "ACT_SCRATCH_DOOR_OR_FENCE",
                "ACT_FIND_COOL_SPOT_AND_LIE_DOWN",
            ],
        },
        {
            "phase": "物品探索",
            "duration": (1.0, 4.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_SNIFF_OBJECT",
                "ACT_PUSH_OBJECT_WITH_PAW",
                "ACT_SCRATCH_OBJECT_GENTLY",
                "ACT_CARRY_AND_HIDE_OBJECT",
                "ACT_DROP_AND_CARRY_OBJECT_AGAIN",
                "ACT_TOUCH_OR_CARRY_OBJECT_WITH_MOUTH",
                "ACT_BARK_AT_OBJECT",
                "ACT_KNOCK_OVER_OBJECT",
                "ACT_NIBBLE_OBJECT",
            ],
        },
    ],

    # ── Lv5: 情绪表达 — 开心 ───────────────────────────────────────────────
    "express_happy": [
        {
            "phase": "开心表达",
            "duration": (1.5, 4.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_PLAY_BOW_INVITE",
                "ACT_RUN_IN_CIRCLES_OR_ZOOMIES",
                "ACT_WAG_TAIL",
                "ACT_STRETCH_LAZILY",
                "ACT_ROLL_OVER",
            ],
        },
    ],

    # ── Lv5: 情绪表达 — 恐惧 ───────────────────────────────────────────────
    "express_fear": [
        {
            "phase": "恐惧表达",
            "duration": (2.0, 5.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_LOWER_HEAD_OR_TURN",
                "ACT_HESITATE",
                "ACT_WHINE_SOFTLY",
                "ACT_TENSE_BODY",
                "ACT_SLIGHT_TREMOR",
            ],
        },
    ],

    # ── Lv5: 情绪表达 — 好奇 ───────────────────────────────────────────────
    "express_curiosity": [
        {
            "phase": "好奇探索",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_STARE_AND_TILT_HEAD",
                "ACT_SNIFF_OBJECT",
                "ACT_PUSH_OBJECT_WITH_PAW",
                "ACT_TOUCH_OR_CARRY_OBJECT_WITH_MOUTH",
                "ACT_TROT_AND_LOOK_AROUND",
            ],
        },
    ],

    # ── Lv2: 外部交互 — 响应主人呼唤 ───────────────────────────────────────
    "respond_owner_call": [
        {
            "phase": "响应呼唤",
            "duration": (0.5, 2.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_TROT_AND_LOOK_AROUND",
                "ACT_STARE_AND_TILT_HEAD",
                "ACT_SEARCH_FOR_PERSON",
            ],
        },
        {
            "phase": "靠近主人",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": False,
            "actions": [
                "ACT_FOLLOW_AND_CLING",
                "ACT_RUB_AGAINST_LEG_OR_LEAN",
                "ACT_SIT_OR_LIE_AT_FEET",
            ],
        },
        {
            "phase": "回应",
            "duration": (0.5, 1.5),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_WAG_TAIL",
                "ACT_LICK_HAND_OR_FACE",
                "ACT_PLAY_BOW_INVITE",
            ],
        },
    ],

    # ── Lv2: 外部交互 — 响应摸头 ───────────────────────────────────────────
    "respond_touch_head": [
        {
            "phase": "接受抚摸",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_RUB_AGAINST_LEG_OR_LEAN",
                "ACT_NUDGE_HAND_WITH_HEAD",
                "ACT_WAG_TAIL",
                "ACT_LICK_HAND_OR_FACE",
            ],
        },
    ],

    # ── Lv0: 系统 — 紧急停止 ───────────────────────────────────────────────
    "emergency_stop": [
        {
            "phase": "紧急停止",
            "duration": (0.1, 0.5),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_TENSE_BODY",
                "ACT_SIT_OR_LIE_BY_BOWL",
            ],
        },
    ],

    # ── Lv0: 系统 — 躲避危险 ───────────────────────────────────────────────
    "avoid_danger": [
        {
            "phase": "警觉",
            "duration": (0.3, 1.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_STARE_AND_TILT_HEAD",
                "ACT_TENSE_BODY",
            ],
        },
        {
            "phase": "躲避",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": False,
            "actions": [
                "ACT_WALK_AWAY_OR_LIE_DOWN",
                "ACT_FIND_COOL_SPOT_AND_LIE_DOWN",
                "ACT_CRAWL_THROUGH_LOW_GAP",
            ],
        },
    ],

    # ── Lv6: 空闲 — 环顾四周 ───────────────────────────────────────────────
    "idle_look_around": [
        {
            "phase": "环顾",
            "duration": (1.0, 3.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_TROT_AND_LOOK_AROUND",
                "ACT_WALK_SLOWLY_AND_SNIFF_GROUND",
                "ACT_STARE_AND_TILT_HEAD",
                "ACT_YAWN",
                "ACT_STRETCH_LAZILY",
            ],
        },
        {
            "phase": "小动作",
            "duration": (1.0, 2.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_LICK_PAWS_OR_FUR",
                "ACT_SHAKE_HEAD",
                "ACT_WAG_TAIL",
                "ACT_PANT",
            ],
        },
    ],

    # ── Lv6: 空闲 — 休息 ───────────────────────────────────────────────────
    "idle_rest": [
        {
            "phase": "趴下休息",
            "duration": (5.0, 15.0),
            "safe_to_interrupt": True,
            "actions": [
                "ACT_LIE_ON_SIDE_AND_STRETCH",
                "ACT_YAWN",
                "ACT_FLIP_BODY",
            ],
        },
    ],

    # ── Lv5: 情绪驱动 — Calm 平静 ──────────────────────────────────────────
    "restInPlace": [
        {"phase": "板鸭趴", "duration": (5.0, 15.0), "safe_to_interrupt": True,
         "actions": ["ACT_FLIP_BODY", "ACT_LIE_ON_SIDE_AND_STRETCH"]},
    ],
    "sleepOnSide": [
        {"phase": "侧躺休息", "duration": (5.0, 20.0), "safe_to_interrupt": True,
         "actions": ["ACT_LIE_ON_SIDE_AND_STRETCH"]},
    ],
    "stretchLazily": [
        {"phase": "伸懒腰", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_STRETCH_LAZILY"]},
    ],
    "lickPaws": [
        {"phase": "舔爪子", "duration": (2.0, 5.0), "safe_to_interrupt": True,
         "actions": ["ACT_LICK_PAWS_OR_FUR"]},
    ],
    "yawnSlowly": [
        {"phase": "打哈欠", "duration": (1.0, 2.0), "safe_to_interrupt": True,
         "actions": ["ACT_YAWN"]},
    ],
    "exposeBelly": [
        {"phase": "肚皮朝天", "duration": (3.0, 8.0), "safe_to_interrupt": True,
         "actions": ["ACT_ROLL_OVER"]},
    ],
    "waitAtDoor": [
        {"phase": "守在门口", "duration": (5.0, 20.0), "safe_to_interrupt": True,
         "actions": ["ACT_SCRATCH_DOOR_OR_FENCE", "ACT_LIE_BY_DOOR", "ACT_LEAN_AGAINST_DOOR"]},
    ],
    "cuddlePose": [
        {"phase": "贴靠", "duration": (3.0, 10.0), "safe_to_interrupt": True,
         "actions": ["ACT_RUB_AGAINST_LEG_OR_LEAN", "ACT_SIT_OR_LIE_AT_FEET"]},
    ],
    "pawAtOwner": [
        {"phase": "扒拉主人", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_PAW_AT_ARM_OR_PANTS", "ACT_NUDGE_HAND_WITH_HEAD"]},
    ],

    # ── Lv5: 情绪驱动 — Joy 愉悦 ───────────────────────────────────────────
    "wagTailGently": [
        {"phase": "轻轻摇尾", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_WAG_TAIL"]},
    ],
    "wagTailFast": [
        {"phase": "快速摇尾踱步", "duration": (1.5, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_WAG_TAIL", "ACT_TROT_AND_LOOK_AROUND"]},
    ],
    "hopInPlace": [
        {"phase": "原地跳跃", "duration": (1.0, 2.5), "safe_to_interrupt": True,
         "actions": ["ACT_RUN_IN_CIRCLES_OR_ZOOMIES"]},
    ],
    "nudgeWithNose": [
        {"phase": "鼻子轻蹭", "duration": (1.0, 2.0), "safe_to_interrupt": True,
         "actions": ["ACT_NUDGE_HAND_WITH_HEAD", "ACT_RUB_AGAINST_LEG_OR_LEAN"]},
    ],
    "playBow": [
        {"phase": "玩耍鞠躬", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_PLAY_BOW_INVITE"]},
    ],
    "tailUpAndWag": [
        {"phase": "尾巴高翘快摆", "duration": (1.5, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_WAG_TAIL"]},
    ],
    "spinInCircle": [
        {"phase": "兴奋转圈", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_RUN_IN_CIRCLES_OR_ZOOMIES"]},
    ],
    "pounceForward": [
        {"phase": "扑跳", "duration": (0.5, 1.5), "safe_to_interrupt": False,
         "actions": ["ACT_JUMP_ON_PERSON", "ACT_PLAY_BOW_INVITE"]},
    ],
    "barkShortExcited": [
        {"phase": "兴奋吠叫", "duration": (0.5, 1.5), "safe_to_interrupt": True,
         "actions": ["ACT_WHINE_OR_BARK_SOFTLY", "ACT_BARK_OR_HOWL"]},
    ],
    "runBackAndForth": [
        {"phase": "来回奔跑", "duration": (2.0, 5.0), "safe_to_interrupt": False,
         "actions": ["ACT_RUN_IN_CIRCLES_OR_ZOOMIES", "ACT_CHASE_ROLLING_FOOD"]},
    ],
    "rollOverShowBelly": [
        {"phase": "打滚露肚皮", "duration": (1.5, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_ROLL_OVER"]},
    ],

    # ── Lv5: 情绪驱动 — Excite 兴奋 ────────────────────────────────────────
    "begForFood": [
        {"phase": "索求", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_STARE_AT_FOOD_IN_HAND", "ACT_WHINE_OR_BARK_SOFTLY",
                      "ACT_PRESS_BELL_OR_TRIGGER_MECHANISM"]},
    ],
    "carryAndShake": [
        {"phase": "物品摇晃", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_CARRY_AND_SHAKE_OBJECT", "ACT_SHAKE_TOY_WITH_MOUTH"]},
    ],
    "wiggleBody": [
        {"phase": "扭身摇尾", "duration": (1.0, 2.5), "safe_to_interrupt": True,
         "actions": ["ACT_WAG_TAIL"]},
    ],
    "trotAndBounce": [
        {"phase": "小跑弹跳", "duration": (1.5, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_TROT_AND_LOOK_AROUND", "ACT_RUN_IN_CIRCLES_OR_ZOOMIES"]},
    ],
    "moveRapidly": [
        {"phase": "高频移动", "duration": (2.0, 5.0), "safe_to_interrupt": False,
         "actions": ["ACT_RUN_IN_CIRCLES_OR_ZOOMIES", "ACT_TROT_AND_LOOK_AROUND"]},
    ],
    "jumpOnPerson": [
        {"phase": "跳跃扑人", "duration": (0.5, 1.5), "safe_to_interrupt": False,
         "actions": ["ACT_JUMP_ON_PERSON"]},
    ],
    "circleAround": [
        {"phase": "绕圈转", "duration": (1.5, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_RUN_IN_CIRCLES_OR_CHASE", "ACT_CIRCLE_AROUND"]},
    ],
    "zoomiesRun": [
        {"phase": "魔鬼跑", "duration": (2.0, 5.0), "safe_to_interrupt": False,
         "actions": ["ACT_RUN_IN_CIRCLES_OR_ZOOMIES"]},
    ],
    "barkOrWhine": [
        {"phase": "吠叫回应", "duration": (0.5, 2.0), "safe_to_interrupt": True,
         "actions": ["ACT_WHINE_OR_BARK_SOFTLY", "ACT_BARK_OR_HOWL"]},
    ],
    "mouthingGently": [
        {"phase": "轻咬裤腿", "duration": (1.0, 2.0), "safe_to_interrupt": True,
         "actions": ["ACT_NIP_GENTLY_AT_PANTS_OR_HAND"]},
    ],
    "pawOnKnee": [
        {"phase": "前爪搭膝", "duration": (1.0, 2.0), "safe_to_interrupt": True,
         "actions": ["ACT_PLACE_PAW_ON_KNEE", "ACT_PAW_AT_ARM_OR_PANTS"]},
    ],
    "fetchToy": [
        {"phase": "叼玩具", "duration": (1.5, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_DROP_TOY_IN_FRONT_OF_OWNER", "ACT_SHAKE_TOY_WITH_MOUTH"]},
    ],

    # ── Lv5: 情绪驱动 — Anxiety 焦虑 ───────────────────────────────────────
    "paceBackAndForth": [
        {"phase": "来回踱步", "duration": (2.0, 6.0), "safe_to_interrupt": True,
         "actions": ["ACT_RUN_IN_CIRCLES_OR_ZOOMIES", "ACT_TROT_AND_LOOK_AROUND"]},
    ],
    "whineLow": [
        {"phase": "低哼唧", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_WHINE_SOFTLY"]},
    ],
    "stareIntently": [
        {"phase": "凝视", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_STARE_AND_TILT_HEAD"]},
    ],
    "headTilt": [
        {"phase": "歪头", "duration": (0.5, 1.5), "safe_to_interrupt": True,
         "actions": ["ACT_STARE_AND_TILT_HEAD"]},
    ],
    "scratchFrequently": [
        {"phase": "频繁抓挠", "duration": (1.5, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_SCRATCH", "ACT_SCRATCH_OBJECT_GENTLY"]},
    ],
    "whineHigh": [
        {"phase": "高声哀鸣", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_WHINE_SOFTLY", "ACT_BARK_OR_HOWL"]},
    ],
    "bodyStiffen": [
        {"phase": "身体紧绷", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_TENSE_BODY"]},
    ],
    "tuckTail": [
        {"phase": "夹尾", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_TAIL_MOVEMENT"]},
    ],
    "dilatePupils": [
        {"phase": "瞳孔放大", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_STARE_AND_TILT_HEAD"]},
    ],
    "hideAway": [
        {"phase": "躲藏", "duration": (3.0, 10.0), "safe_to_interrupt": False,
         "actions": ["ACT_CRAWL_THROUGH_LOW_GAP", "ACT_FIND_COOL_SPOT_AND_LIE_DOWN"]},
    ],

    # ── Lv5: 情绪驱动 — Fear 恐惧 ──────────────────────────────────────────
    "freezeAlert": [
        {"phase": "僵直警觉", "duration": (1.0, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_TENSE_BODY", "ACT_STARE_AND_TILT_HEAD"]},
    ],
    "walkAway": [
        {"phase": "走开", "duration": (1.5, 4.0), "safe_to_interrupt": False,
         "actions": ["ACT_WALK_AWAY_OR_LIE_DOWN", "ACT_FIND_COOL_SPOT_AND_LIE_DOWN"]},
    ],
    "retreatWithTailTucked": [
        {"phase": "夹尾后退", "duration": (1.0, 3.0), "safe_to_interrupt": False,
         "actions": ["ACT_WALK_AWAY_OR_LIE_DOWN"]},
    ],
    "growlLow": [
        {"phase": "低吼", "duration": (0.5, 2.0), "safe_to_interrupt": True,
         "actions": ["ACT_GROWL_WHILE_EATING", "ACT_BARK_OR_HOWL"]},
    ],
    "fleeQuickly": [
        {"phase": "快速逃窜", "duration": (1.0, 3.0), "safe_to_interrupt": False,
         "actions": ["ACT_RUN_IN_CIRCLES_OR_ZOOMIES", "ACT_WALK_AWAY_OR_LIE_DOWN"]},
    ],
    "avoidAndHide": [
        {"phase": "躲避藏匿", "duration": (2.0, 6.0), "safe_to_interrupt": False,
         "actions": ["ACT_CRAWL_THROUGH_LOW_GAP", "ACT_FIND_COOL_SPOT_AND_LIE_DOWN"]},
    ],
    "trembleShake": [
        {"phase": "发抖", "duration": (1.0, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_SLIGHT_TREMOR", "ACT_TENSE_BODY"]},
    ],
    "loseControl": [
        {"phase": "失禁", "duration": (0.5, 1.5), "safe_to_interrupt": False,
         "actions": ["ACT_SQUAT_TO_PEE"]},
    ],

    # ── Lv5: 情绪驱动 — Curious 好奇 ───────────────────────────────────────
    "tailWagLevel": [
        {"phase": "尾巴平摆", "duration": (1.0, 2.5), "safe_to_interrupt": True,
         "actions": ["ACT_WAG_TAIL"]},
    ],
    "approachSlowly": [
        {"phase": "缓慢靠近", "duration": (1.5, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_APPROACH_SLOWLY_SIDEWAYS", "ACT_WALK_SLOWLY_AND_SNIFF_GROUND"]},
    ],
    "sniffGround": [
        {"phase": "嗅闻", "duration": (1.0, 3.0), "safe_to_interrupt": True,
         "actions": ["ACT_SNIFF_GROUND_FOR_CRUMBS", "ACT_SNIFF_OBJECT"]},
    ],
    "pawAtObject": [
        {"phase": "爪子拨弄", "duration": (1.0, 2.5), "safe_to_interrupt": True,
         "actions": ["ACT_PUSH_OBJECT_WITH_PAW", "ACT_SCRATCH_OBJECT_GENTLY"]},
    ],
    "followMovement": [
        {"phase": "跟随移动", "duration": (1.5, 4.0), "safe_to_interrupt": False,
         "actions": ["ACT_FOLLOW_AND_CLING", "ACT_TROT_AND_LOOK_AROUND"]},
    ],
    "circleInspect": [
        {"phase": "绕行观察", "duration": (1.5, 4.0), "safe_to_interrupt": True,
         "actions": ["ACT_CIRCLE_AROUND", "ACT_STARE_AND_TILT_HEAD"]},
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Build randomized action sequence from catalog
# ═══════════════════════════════════════════════════════════════════════════════

def build_action_sequence(behavior_name: str,
                          interactive: bool = False) -> list[dict]:
    """Build a randomized action sequence for a behavior.

    For each phase in the catalog, randomly picks one action.
    Duration is also randomized within the specified range.

    For social behaviors, if interactive=True, prefers human-interaction
    variant; otherwise uses the default (animal-interaction).
    """
    # Resolve interactive variants
    catalog_name = behavior_name
    if behavior_name == "seek_social_interaction" and interactive:
        catalog_name = "seek_social_interaction_human"

    phases = BEHAVIOR_ACTION_CATALOG.get(catalog_name)
    if phases is None:
        return []

    sequence = []
    for phase in phases:
        action = random.choice(phase["actions"])
        duration = random.uniform(*phase["duration"])
        sequence.append({
            "node": phase["phase"],
            "action": action,
            "duration": round(duration, 2),
            "safe_to_interrupt": phase["safe_to_interrupt"],
        })
    return sequence


def get_action_choices(behavior_name: str) -> Optional[list[dict]]:
    """Get the full catalog entry (with all action choices) for a behavior."""
    return BEHAVIOR_ACTION_CATALOG.get(behavior_name)
