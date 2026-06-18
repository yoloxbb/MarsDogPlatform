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


def GetEmotionInternalName(emotionType: object) -> str:
    """获取情绪类型对应的内部变量名。"""
    return EMOTION_INTERNAL_NAMES[NormalizeEmotionType(emotionType)]
