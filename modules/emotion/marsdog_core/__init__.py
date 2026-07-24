"""Marsdog 内部需求与情绪计算核心包。"""

from .emotion_system import MarsdogEmotionSystem
from .need_system import MarsdogNeedSystem
from .personality_system import MarsdogPersonalitySystem
from .time_controller import MarsdogTimeController, VirtualTickScheduler
from .types import (
    ActionType,
    DemandType,
    EatEfficiencyType,
    EmotionType,
    FoodType,
    PersonalityProfileType,
    SleepDepthType,
)

__all__ = [
    "ActionType",
    "DemandType",
    "EatEfficiencyType",
    "EmotionType",
    "FoodType",
    "MarsdogEmotionSystem",
    "MarsdogNeedSystem",
    "MarsdogPersonalitySystem",
    "PersonalityProfileType",
    "SleepDepthType",
    "MarsdogTimeController",
    "VirtualTickScheduler",
]
