"""One source-aware relevance rule for BT nodes and application callers."""
from .constants import EMOTION_BEHAVIOR_MAP, NEED_BEHAVIOR_MAP
from .drive_policy import resolve_drive
from .logger import get_logger, LogEvent

_log = get_logger("relevance")


def is_trigger_relevant(behavior_name, need_type, params, blackboard) -> bool:
    """Gate unstarted state-owned candidates, never stop a running Goal.

    Direct candidates use existing TTL/session/target gates; borrowing an
    emotion template does not make them depend on the internal emotion state.
    """
    domain = resolve_drive(params, need_type).state_domain
    if domain == "emotion":
        name = params.get("source_emotion")
        if name is None:
            name = EMOTION_BEHAVIOR_MAP.get(behavior_name)
        if name is None:
            _log.event(LogEvent.RELEVANCE_FAIL, behavior_name=behavior_name,
                       reason="missing_source_emotion")
            return False
        if not blackboard.emotion_module.is_triggered(name):
            state = blackboard.emotion_module.get_emotion(name)
            _log.event(LogEvent.RELEVANCE_FAIL, behavior_name=behavior_name,
                       emotion=name, current=round(state.current_value if state else 0.0, 1),
                       triggered=False)
            return False
        _log.event(LogEvent.RELEVANCE_PASS, behavior_name=behavior_name,
                   emotion=name, triggered=True)
    elif domain == "need":
        name = params.get("source_need")
        if name is None:
            name = NEED_BEHAVIOR_MAP.get(behavior_name)
        # Retain the old compatibility behavior for an unnamed legacy need.
        if name is not None:
            if not blackboard.need_module.is_triggered(name):
                _log.event(LogEvent.RELEVANCE_FAIL, behavior_name=behavior_name,
                           need=name, need_level=blackboard.need_module.get_level(name))
                return False
            _log.event(LogEvent.RELEVANCE_PASS, behavior_name=behavior_name,
                       need=name, triggered=True)
    return True
