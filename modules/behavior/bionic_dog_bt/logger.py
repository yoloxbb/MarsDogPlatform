"""BT internal diagnostics; decision_trace owns the INFO decision lifecycle."""
import logging
from enum import Enum
from marsdog_observability import get_logger as project_logger

class LogEvent(str, Enum):
    """Structured event types for behavior tree lifecycle."""
    # Candidate & signal
    CANDIDATE_INJECT = "candidate_inject"
    CANDIDATE_DEDUP = "candidate_dedup"
    CANDIDATE_SELECT = "candidate_select"

    # Behavior execution
    BEHAVIOR_START = "behavior_start"
    BEHAVIOR_COMPLETE = "behavior_complete"
    BEHAVIOR_TIMEOUT = "behavior_timeout"
    BEHAVIOR_COOLDOWN = "behavior_cooldown"

    # Preemption
    PREEMPT = "preempt"
    PREEMPT_BLOCKED = "preempt_blocked"

    # Relevance check
    RELEVANCE_PASS = "relevance_pass"
    RELEVANCE_FAIL = "relevance_fail"

    # Emotion / Need
    EMOTION_STATE = "emotion_state"
    EMOTION_SIGNAL = "emotion_signal"
    NEED_STATE = "need_state"
    NEED_SIGNAL = "need_signal"

    # System
    TREE_TICK = "tree_tick"
    FEEDBACK_PUBLISH = "feedback_publish"



class BTLogger:
    def __init__(self, name):
        self.logger = project_logger(name)

    def __getattr__(self, name):
        return getattr(self.logger, name)

    def event(self, event_type, **fields):
        self.logger.event("behavior.internal." + event_type.value.replace("_", "."),
                          level=logging.DEBUG, kind="diagnostic", **fields)


def get_logger(name):
    return BTLogger("bionic_dog_bt." + name)


def get_bt_logger():
    return get_logger("behavior_tree")


def get_action_logger():
    return get_logger("actions")


def get_condition_logger():
    return get_logger("conditions")


def get_executor_logger():
    return get_logger("executor")


def get_emotion_logger():
    return get_logger("emotion")
