"""核心枚举和类型规范。"""

from __future__ import annotations

from enum import Enum
from typing import Type, TypeVar


class DemandType(str, Enum):
    """需求状态量类型。"""

    HUNGER = "Hunger"
    BLADDER = "Bladder"
    SLEEPINESS = "Sleepiness"
    CLEANLINESS = "Cleanliness"
    ENERGY = "Energy"
    SOCIAL = "Social"
    EXPLORATION = "Exploration"


class EmotionType(str, Enum):
    """对外暴露的情绪类型。"""

    JOY = "Joy"
    EXCITE = "Excite"
    ANXIETY = "Anxiety"
    FEAR = "Fear"
    CURIOUS = "Curious"
    CALM = "Calm"


class PersonalityParam(str, Enum):
    """性格参数类型。"""

    AFFINITY = "A"
    OBEDIENCE = "O"
    EXTRAVERSION = "E"
    COURAGE = "C"


class PriorityMode(str, Enum):
    """行为优先级模式。"""

    NORMAL = "Normal"
    EMERGENCY = "Emergency"
    IDLE = "Idle"


class ActionResultType(str, Enum):
    """行为执行结果类型。"""

    DEMAND_SATISFIED = "DemandSatisfied"
    DEMAND_UNSATISFIED = "DemandUnsatisfied"
    ACTION_INTERRUPTED = "ActionInterrupted"


class ActionFeedbackStatus(str, Enum):
    """具体动作执行反馈状态。"""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    INTERRUPTED = "INTERRUPTED"


class FoodType(str, Enum):
    """食物类型。"""

    PREMIUM_FOOD = "PremiumFood"
    NORMAL_FOOD = "NormalFood"
    SNACK = "Snack"


class EatEfficiencyType(str, Enum):
    """进食效率类型。"""

    FULL = "Full"
    HALF_INTERRUPTED = "HalfInterrupted"


class SleepDepthType(str, Enum):
    """睡眠深度类型。"""

    SHALLOW = "Shallow"
    DEEP = "Deep"


class SocialInitiatorType(str, Enum):
    """社交互动发起方。"""

    OWNER = "Owner"
    DOG = "Dog"


class SocialTargetType(str, Enum):
    """社交互动目标类型。"""

    HUMAN = "Human"
    ANIMAL = "Animal"


class SocialInteractionState(str, Enum):
    """社交互动会话状态。"""

    IDLE = "Idle"
    EXECUTING_ACTION = "ExecutingAction"
    WAITING_RESPONSE = "WaitingResponse"
    COMPLETED = "Completed"
    TIMED_OUT = "TimedOut"
    INTERRUPTED = "Interrupted"
    FAILED = "Failed"


class SocialResponseType(str, Enum):
    """社交互动回应类型。"""

    RESPONDED = "RESPONDED"
    REJECTED = "REJECTED"


class PersonalityProfileType(str, Enum):
    """预设性格类型。"""

    CUSTOM = "Custom"
    GENTLE_COMPANION = "GentleCompanion"
    SUNNY_EXPLORER = "SunnyExplorer"
    LOYAL_GUARDIAN = "LoyalGuardian"
    PROUD_INDEPENDENT = "ProudIndependent"


class ExplorationDiscoveryType(str, Enum):
    """探索发现结果类型。"""

    NEW = "New"
    OLD = "Old"
    COMPLETED = "Completed"


class ExplorationTargetType(str, Enum):
    """探索目标类型。"""

    SPACE = "Space"
    HUMAN = "Human"
    MAP = "Map"
    GENERIC_OBJECT = "GenericObject"
    SLIPPERS_OR_SOCKS = "SlippersOrSocks"
    TRASH_CAN = "TrashCan"
    DELIVERY_BOX = "DeliveryBox"
    TISSUE = "Tissue"
    DOOR = "Door"


class ActionType(str, Enum):
    """顶层行为类型。"""

    ACTION_EAT = "ACTION_EAT"
    ACTION_DEFECATE = "ACTION_DEFECATE"
    ACTION_SLEEP = "ACTION_SLEEP"
    ACTION_GROOM = "ACTION_GROOM"
    ACTION_RECHARGE = "ACTION_RECHARGE"
    ACTION_PET = "ACTION_PET"
    ACTION_VOICE_INTERACT = "ACTION_VOICE_INTERACT"
    ACTION_GIVE_TOY = "ACTION_GIVE_TOY"
    ACTION_EXPLORE = "ACTION_EXPLORE"
    ACTION_PLAY_INVITE = "ACTION_PLAY_INVITE"
    ACTION_SOCIAL_GREET = "ACTION_SOCIAL_GREET"
    ACTION_BOUNDARY_TEST = "ACTION_BOUNDARY_TEST"
    ACTION_ATTENTION_SEEK = "ACTION_ATTENTION_SEEK"
    ACTION_RESOURCE_SHARE = "ACTION_RESOURCE_SHARE"
    ACTION_SPACE_EXPLORE = "ACTION_SPACE_EXPLORE"
    ACTION_OBJECT_EXPLORE = "ACTION_OBJECT_EXPLORE"
    ACTION_FLEE = "ACTION_FLEE"
    ACTION_HIDE = "ACTION_HIDE"
    ACTION_WAG_TAIL = "ACTION_WAG_TAIL"
    ACTION_ZOOM = "ACTION_ZOOM"
    ACTION_PACE = "ACTION_PACE"
    ACTION_SNIFF = "ACTION_SNIFF"
    ACTION_LOAF = "ACTION_LOAF"


class ConcreteActionType(str, Enum):
    """具体动作类型。"""

    ACT_RUN_TO_BOWL = "ACT_RUN_TO_BOWL"
    ACT_SNIFF_BOWL_EDGE = "ACT_SNIFF_BOWL_EDGE"
    ACT_PAW_AT_BOWL = "ACT_PAW_AT_BOWL"
    ACT_SIT_OR_LIE_BY_BOWL = "ACT_SIT_OR_LIE_BY_BOWL"
    ACT_LICK_FOOD = "ACT_LICK_FOOD"
    ACT_CHEW_OR_CARRY_FOOD = "ACT_CHEW_OR_CARRY_FOOD"
    ACT_SCRATCH_FOOD = "ACT_SCRATCH_FOOD"
    ACT_LICK_LIPS_AND_SWALLOW = "ACT_LICK_LIPS_AND_SWALLOW"
    ACT_TURN_HEAD_AND_WIPE_MOUTH = "ACT_TURN_HEAD_AND_WIPE_MOUTH"
    ACT_PAUSE_AND_LOOK_AT_OWNER = "ACT_PAUSE_AND_LOOK_AT_OWNER"
    ACT_CHASE_ROLLING_FOOD = "ACT_CHASE_ROLLING_FOOD"
    ACT_CHANGE_POSTURE = "ACT_CHANGE_POSTURE"
    ACT_GROWL_WHILE_EATING = "ACT_GROWL_WHILE_EATING"
    ACT_BURP = "ACT_BURP"
    ACT_LICK_LIPS_OR_NOSE = "ACT_LICK_LIPS_OR_NOSE"
    ACT_SHAKE_HEAD = "ACT_SHAKE_HEAD"
    ACT_WALK_AWAY_OR_LIE_DOWN = "ACT_WALK_AWAY_OR_LIE_DOWN"
    ACT_SNIFF_GROUND_FOR_CRUMBS = "ACT_SNIFF_GROUND_FOR_CRUMBS"
    ACT_FAST_LICK_AND_SWALLOW = "ACT_FAST_LICK_AND_SWALLOW"
    ACT_CIRCLE_AROUND = "ACT_CIRCLE_AROUND"
    ACT_SCRATCH_BED_OR_GROUND = "ACT_SCRATCH_BED_OR_GROUND"
    ACT_LIE_ON_SIDE_AND_STRETCH = "ACT_LIE_ON_SIDE_AND_STRETCH"
    ACT_LICK_FUR_OR_PAWS = "ACT_LICK_FUR_OR_PAWS"
    ACT_FLIP_BODY = "ACT_FLIP_BODY"
    ACT_WHINE_SOFTLY = "ACT_WHINE_SOFTLY"
    ACT_TWITCH_OR_KICK_LEGS = "ACT_TWITCH_OR_KICK_LEGS"
    ACT_SHAKE_HEAD_OR_SMACK_LIPS = "ACT_SHAKE_HEAD_OR_SMACK_LIPS"
    ACT_WAG_TAIL = "ACT_WAG_TAIL"
    ACT_YAWN = "ACT_YAWN"
    ACT_GETUP_CRAWL = "ACT_GETUP_CRAWL"
    ACT_GETUP_ROLL = "ACT_GETUP_ROLL"
    ACT_GETUP_BOUNCE = "ACT_GETUP_BOUNCE"
    ACT_GETUP_STRETCH = "ACT_GETUP_STRETCH"
    ACT_GETUP_SIT = "ACT_GETUP_SIT"
    ACT_SNIFF_AND_CIRCLE = "ACT_SNIFF_AND_CIRCLE"
    ACT_SCRATCH_GROUND = "ACT_SCRATCH_GROUND"
    ACT_SQUAT_TO_PEE = "ACT_SQUAT_TO_PEE"
    ACT_SQUAT_TO_POOP = "ACT_SQUAT_TO_POOP"
    ACT_HESITATE = "ACT_HESITATE"
    ACT_TENSE_BODY = "ACT_TENSE_BODY"
    ACT_TAIL_MOVEMENT = "ACT_TAIL_MOVEMENT"
    ACT_SLIGHT_TREMOR = "ACT_SLIGHT_TREMOR"
    ACT_LOWER_HEAD_OR_TURN = "ACT_LOWER_HEAD_OR_TURN"
    ACT_STAND_UP_WITH_HIND_LEGS = "ACT_STAND_UP_WITH_HIND_LEGS"
    ACT_SCRATCH_SOIL_OR_GROUND = "ACT_SCRATCH_SOIL_OR_GROUND"
    ACT_SNIFF_EXCREMENT = "ACT_SNIFF_EXCREMENT"
    ACT_WALK_AWAY_OR_SHAKE_HEAD = "ACT_WALK_AWAY_OR_SHAKE_HEAD"
    ACT_LICK_PAWS_OR_FUR = "ACT_LICK_PAWS_OR_FUR"
    ACT_SCRATCH = "ACT_SCRATCH"
    ACT_SHAKE_OFF_WATER = "ACT_SHAKE_OFF_WATER"
    ACT_STRETCH_LAZILY = "ACT_STRETCH_LAZILY"
    ACT_ROLL_OVER = "ACT_ROLL_OVER"
    ACT_RUB_AGAINST_OBJECT = "ACT_RUB_AGAINST_OBJECT"
    ACT_PANT = "ACT_PANT"
    ACT_PANT_IN_PLACE = "ACT_PANT_IN_PLACE"
    ACT_RESIST_WALKING = "ACT_RESIST_WALKING"
    ACT_SLOW_MOVEMENT = "ACT_SLOW_MOVEMENT"
    ACT_RETURN_TO_CHARGER = "ACT_RETURN_TO_CHARGER"
    ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER = "ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER"
    ACT_SEARCH_FOR_PERSON = "ACT_SEARCH_FOR_PERSON"
    ACT_RUB_AGAINST_LEG_OR_LEAN = "ACT_RUB_AGAINST_LEG_OR_LEAN"
    ACT_NUDGE_HAND_WITH_HEAD = "ACT_NUDGE_HAND_WITH_HEAD"
    ACT_SIT_OR_LIE_AT_FEET = "ACT_SIT_OR_LIE_AT_FEET"
    ACT_LICK_HAND_OR_FACE = "ACT_LICK_HAND_OR_FACE"
    ACT_DROP_TOY_IN_FRONT_OF_OWNER = "ACT_DROP_TOY_IN_FRONT_OF_OWNER"
    ACT_WHINE_OR_BARK_SOFTLY = "ACT_WHINE_OR_BARK_SOFTLY"
    ACT_PAW_AT_ARM_OR_PANTS = "ACT_PAW_AT_ARM_OR_PANTS"
    ACT_JUMP_ON_PERSON = "ACT_JUMP_ON_PERSON"
    ACT_FOLLOW_AND_CLING = "ACT_FOLLOW_AND_CLING"
    ACT_GUARD_FOOD_BOWL_OR_SNACK_CABINET = "ACT_GUARD_FOOD_BOWL_OR_SNACK_CABINET"
    ACT_SCRATCH_FOOD_BOWL_OR_SNACK_CABINET = "ACT_SCRATCH_FOOD_BOWL_OR_SNACK_CABINET"
    ACT_CARRY_LEASH_OR_SHOE = "ACT_CARRY_LEASH_OR_SHOE"
    ACT_STARE_AT_FOOD_IN_HAND = "ACT_STARE_AT_FOOD_IN_HAND"
    ACT_PRESS_BELL_OR_TRIGGER_MECHANISM = "ACT_PRESS_BELL_OR_TRIGGER_MECHANISM"
    ACT_PLAY_BOW = "ACT_PLAY_BOW"
    ACT_SHAKE_TOY_WITH_MOUTH = "ACT_SHAKE_TOY_WITH_MOUTH"
    ACT_RUN_IN_CIRCLES_OR_ZOOMIES = "ACT_RUN_IN_CIRCLES_OR_ZOOMIES"
    ACT_NIP_GENTLY_AT_PANTS_OR_HAND = "ACT_NIP_GENTLY_AT_PANTS_OR_HAND"
    ACT_PLACE_PAW_ON_KNEE = "ACT_PLACE_PAW_ON_KNEE"
    ACT_CARRY_AND_SHAKE_OBJECT = "ACT_CARRY_AND_SHAKE_OBJECT"
    ACT_POUNCE_GENTLY = "ACT_POUNCE_GENTLY"
    ACT_RUN_IN_CIRCLES_OR_CHASE = "ACT_RUN_IN_CIRCLES_OR_CHASE"
    ACT_PAW_GENTLY_AT_OTHER = "ACT_PAW_GENTLY_AT_OTHER"
    ACT_SNIFF_FACE_OR_EARS = "ACT_SNIFF_FACE_OR_EARS"
    ACT_SNIFF_BUTT_OR_TAIL = "ACT_SNIFF_BUTT_OR_TAIL"
    ACT_TOUCH_NOSE_OR_HEAD_GENTLY = "ACT_TOUCH_NOSE_OR_HEAD_GENTLY"
    ACT_APPROACH_SLOWLY_SIDEWAYS = "ACT_APPROACH_SLOWLY_SIDEWAYS"
    ACT_LOWER_HEAD_FLOP_EARS_WAG_TAIL = "ACT_LOWER_HEAD_FLOP_EARS_WAG_TAIL"
    ACT_LIE_BESIDE_OTHER_ANIMAL = "ACT_LIE_BESIDE_OTHER_ANIMAL"
    ACT_BARK_OR_HOWL = "ACT_BARK_OR_HOWL"
    ACT_STARE_AND_TILT_HEAD = "ACT_STARE_AND_TILT_HEAD"
    ACT_TROT_AND_LOOK_AROUND = "ACT_TROT_AND_LOOK_AROUND"
    ACT_WALK_SLOWLY_AND_SNIFF_GROUND = "ACT_WALK_SLOWLY_AND_SNIFF_GROUND"
    ACT_CRAWL_THROUGH_LOW_GAP = "ACT_CRAWL_THROUGH_LOW_GAP"
    ACT_STAND_AND_SCRATCH_HIGH = "ACT_STAND_AND_SCRATCH_HIGH"
    ACT_SCRATCH_DOOR_OR_FENCE = "ACT_SCRATCH_DOOR_OR_FENCE"
    ACT_FIND_COOL_SPOT_AND_LIE_DOWN = "ACT_FIND_COOL_SPOT_AND_LIE_DOWN"
    ACT_IGNORE_SLIPPERS_OR_SOCKS = "ACT_IGNORE_SLIPPERS_OR_SOCKS"
    ACT_BITE_SLIPPERS_OR_SOCKS = "ACT_BITE_SLIPPERS_OR_SOCKS"
    ACT_POUNCE_ON_SLIPPERS_OR_SOCKS = "ACT_POUNCE_ON_SLIPPERS_OR_SOCKS"
    ACT_CARRY_SLIPPERS_OR_SOCKS_TO_PERSON = "ACT_CARRY_SLIPPERS_OR_SOCKS_TO_PERSON"
    ACT_SCRATCH_SLIPPERS_OR_SOCKS_WITH_PAW = "ACT_SCRATCH_SLIPPERS_OR_SOCKS_WITH_PAW"
    ACT_SNIFF_SLIPPERS_OR_SOCKS = "ACT_SNIFF_SLIPPERS_OR_SOCKS"
    ACT_IGNORE_TRASH_CAN = "ACT_IGNORE_TRASH_CAN"
    ACT_RUMMAGE_THROUGH_TRASH_CAN = "ACT_RUMMAGE_THROUGH_TRASH_CAN"
    ACT_SNIFF_TRASH_CAN = "ACT_SNIFF_TRASH_CAN"
    ACT_IGNORE_DELIVERY_BOX = "ACT_IGNORE_DELIVERY_BOX"
    ACT_SNIFF_DELIVERY_BOX = "ACT_SNIFF_DELIVERY_BOX"
    ACT_BITE_DELIVERY_BOX = "ACT_BITE_DELIVERY_BOX"
    ACT_CARRY_DELIVERY_BOX_TO_PERSON = "ACT_CARRY_DELIVERY_BOX_TO_PERSON"
    ACT_SCRATCH_DELIVERY_BOX_WITH_PAW = "ACT_SCRATCH_DELIVERY_BOX_WITH_PAW"
    ACT_IGNORE_TISSUE = "ACT_IGNORE_TISSUE"
    ACT_SNIFF_TISSUE = "ACT_SNIFF_TISSUE"
    ACT_SCRATCH_TISSUE_WITH_PAW = "ACT_SCRATCH_TISSUE_WITH_PAW"
    ACT_CARRY_TISSUE_TO_PERSON = "ACT_CARRY_TISSUE_TO_PERSON"
    ACT_IGNORE_DOOR = "ACT_IGNORE_DOOR"
    ACT_LEAN_AGAINST_DOOR = "ACT_LEAN_AGAINST_DOOR"
    ACT_LIE_BY_DOOR = "ACT_LIE_BY_DOOR"
    ACT_SCRATCH_DOOR = "ACT_SCRATCH_DOOR"
    ACT_SNIFF_AROUND_DOOR = "ACT_SNIFF_AROUND_DOOR"
    ACT_TOUCH_OR_CARRY_OBJECT_WITH_MOUTH = "ACT_TOUCH_OR_CARRY_OBJECT_WITH_MOUTH"
    ACT_BARK_AT_OBJECT = "ACT_BARK_AT_OBJECT"
    ACT_KNOCK_OVER_OBJECT = "ACT_KNOCK_OVER_OBJECT"
    ACT_NIBBLE_OBJECT = "ACT_NIBBLE_OBJECT"


DEMAND_CHINESE_NAMES = {
    DemandType.HUNGER.value: "饥渴值",
    DemandType.BLADDER.value: "排泄值",
    DemandType.SLEEPINESS.value: "困倦值",
    DemandType.CLEANLINESS.value: "清洁值",
    DemandType.ENERGY.value: "精力值",
    DemandType.SOCIAL.value: "社交值",
    DemandType.EXPLORATION.value: "探索值",
}

EMOTION_INTERNAL_NAMES = {
    EmotionType.JOY.value: "emo_joy",
    EmotionType.EXCITE.value: "emo_excite",
    EmotionType.ANXIETY.value: "emo_anxiety",
    EmotionType.FEAR.value: "emo_fear",
    EmotionType.CURIOUS.value: "emo_curious",
    EmotionType.CALM.value: "emo_calm",
}

EMOTION_CHINESE_NAMES = {
    EmotionType.JOY.value: "愉悦",
    EmotionType.EXCITE.value: "兴奋",
    EmotionType.ANXIETY.value: "焦虑",
    EmotionType.FEAR.value: "恐惧",
    EmotionType.CURIOUS.value: "好奇",
    EmotionType.CALM.value: "平静",
}

PERSONALITY_CHINESE_NAMES = {
    PersonalityParam.AFFINITY.value: "亲人度",
    PersonalityParam.OBEDIENCE.value: "服从性",
    PersonalityParam.EXTRAVERSION.value: "活泼度",
    PersonalityParam.COURAGE.value: "胆量",
}

EnumType = TypeVar("EnumType", bound=Enum)


def ClampValue(value: int) -> int:
    """将状态值限制在 0-100 范围内。"""
    return max(0, min(100, int(value)))


def NormalizeEnumValue(enumClass: Type[EnumType], value: object) -> str:
    """把枚举对象、枚举名或枚举值统一转换为字符串值。"""
    if isinstance(value, enumClass):
        return str(value.value)
    if isinstance(value, str):
        for item in enumClass:
            if value == item.value or value == item.name:
                return str(item.value)
    raise ValueError(f"Unknown {enumClass.__name__}: {value}")


def NormalizeDemandType(demandType: object) -> str:
    """规范化需求类型。"""
    return NormalizeEnumValue(DemandType, demandType)


def NormalizeEmotionType(emotionType: object) -> str:
    """规范化情绪类型。"""
    return NormalizeEnumValue(EmotionType, emotionType)


def NormalizePersonalityParam(paramName: object) -> str:
    """规范化性格参数名。"""
    return NormalizeEnumValue(PersonalityParam, paramName)


def NormalizeActionType(actionType: object) -> str:
    """规范化顶层行为类型。"""
    return NormalizeEnumValue(ActionType, actionType)


def NormalizePriorityMode(mode: object) -> str:
    """规范化行为优先级模式。"""
    return NormalizeEnumValue(PriorityMode, mode)


def NormalizeActionResultType(resultType: object) -> str:
    """规范化行为执行结果类型。"""
    return NormalizeEnumValue(ActionResultType, resultType)


def NormalizeActionFeedbackStatus(status: object) -> str:
    """规范化具体动作执行反馈状态。"""
    return NormalizeEnumValue(ActionFeedbackStatus, status)


def NormalizeFoodType(foodType: object) -> str:
    """规范化食物类型。"""
    foodAliases = {
        "优质粮": FoodType.PREMIUM_FOOD.value,
        "普通粮": FoodType.NORMAL_FOOD.value,
        "零食": FoodType.SNACK.value,
    }
    if isinstance(foodType, str) and foodType in foodAliases:
        return foodAliases[foodType]
    return NormalizeEnumValue(FoodType, foodType)


def NormalizeEatEfficiencyType(eatEfficiency: object) -> str:
    """规范化进食效率类型。"""
    efficiencyAliases = {
        "吃满时长": EatEfficiencyType.FULL.value,
        "吃一半被打断": EatEfficiencyType.HALF_INTERRUPTED.value,
    }
    if isinstance(eatEfficiency, str) and eatEfficiency in efficiencyAliases:
        return efficiencyAliases[eatEfficiency]
    return NormalizeEnumValue(EatEfficiencyType, eatEfficiency)


def NormalizeSleepDepthType(sleepDepth: object) -> str:
    """规范化睡眠深度类型。"""
    sleepAliases = {
        "浅睡": SleepDepthType.SHALLOW.value,
        "深睡": SleepDepthType.DEEP.value,
    }
    if isinstance(sleepDepth, str) and sleepDepth in sleepAliases:
        return sleepAliases[sleepDepth]
    return NormalizeEnumValue(SleepDepthType, sleepDepth)


def NormalizeSocialTargetType(targetType: object) -> str:
    """规范化社交目标类型。"""
    return NormalizeEnumValue(SocialTargetType, targetType)


def NormalizeSocialResponseType(responseType: object) -> str:
    """规范化社交回应类型。"""
    return NormalizeEnumValue(SocialResponseType, responseType)


def NormalizePersonalityProfileType(profileName: object) -> str:
    """规范化预设性格名称。"""
    profileAliases = {
        "温柔陪伴者": PersonalityProfileType.GENTLE_COMPANION.value,
        "阳光探险家": PersonalityProfileType.SUNNY_EXPLORER.value,
        "忠诚护卫者": PersonalityProfileType.LOYAL_GUARDIAN.value,
        "傲娇独立者": PersonalityProfileType.PROUD_INDEPENDENT.value,
        "自定义": PersonalityProfileType.CUSTOM.value,
    }
    if isinstance(profileName, str) and profileName in profileAliases:
        return profileAliases[profileName]
    return NormalizeEnumValue(PersonalityProfileType, profileName)


def NormalizeExplorationDiscoveryType(discoveryType: object) -> str:
    """规范化探索发现结果类型。"""
    aliases = {
        "新": ExplorationDiscoveryType.NEW.value,
        "新事物": ExplorationDiscoveryType.NEW.value,
        "旧": ExplorationDiscoveryType.OLD.value,
        "旧事物": ExplorationDiscoveryType.OLD.value,
        "完成": ExplorationDiscoveryType.COMPLETED.value,
    }
    if isinstance(discoveryType, str) and discoveryType in aliases:
        return aliases[discoveryType]
    return NormalizeEnumValue(ExplorationDiscoveryType, discoveryType)


def NormalizeExplorationTargetType(targetType: object) -> str:
    """规范化探索目标类型。"""
    aliases = {
        "空间": ExplorationTargetType.SPACE.value,
        "人": ExplorationTargetType.HUMAN.value,
        "地图": ExplorationTargetType.MAP.value,
        "物品": ExplorationTargetType.GENERIC_OBJECT.value,
        "拖鞋": ExplorationTargetType.SLIPPERS_OR_SOCKS.value,
        "袜子": ExplorationTargetType.SLIPPERS_OR_SOCKS.value,
        "垃圾桶": ExplorationTargetType.TRASH_CAN.value,
        "快递盒子": ExplorationTargetType.DELIVERY_BOX.value,
        "纸巾": ExplorationTargetType.TISSUE.value,
        "门": ExplorationTargetType.DOOR.value,
    }
    if isinstance(targetType, str) and targetType in aliases:
        return aliases[targetType]
    return NormalizeEnumValue(ExplorationTargetType, targetType)


def GetEmotionInternalName(emotionType: object) -> str:
    """获取情绪类型对应的内部变量名。"""
    return EMOTION_INTERNAL_NAMES[NormalizeEmotionType(emotionType)]
