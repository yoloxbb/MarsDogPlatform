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


class ActionResultType(str, Enum):
    """行为执行结果类型。"""

    DEMAND_SATISFIED = "DemandSatisfied"
    DEMAND_UNSATISFIED = "DemandUnsatisfied"
    ACTION_INTERRUPTED = "ActionInterrupted"


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


def NormalizeActionResultType(resultType: object) -> str:
    """规范化行为执行结果类型。"""
    return NormalizeEnumValue(ActionResultType, resultType)


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
