"""Voice event vocabulary; storage, formatting and logger configuration are shared."""
import logging
from marsdog_observability import get_logger as project_logger
from marsdog_observability import current_log_path as get_log_file_path, set_level as set_log_level

_EVENTS = {"runtime_start": "providers.ready", "runtime_stop": "providers.stopped",
           "interaction_start": "interaction.started", "interaction_end": "interaction.ended",
           "stage_start": "stage.started", "stage_complete": "stage.completed",
           "event_publish": "event.published", "utterance_complete": "utterance.completed"}


def get_logger(name, module=""):
    return project_logger(name, area=module) if module else project_logger(name)


def log_trace(logger, record, **fields):
    event = _EVENTS.get(record, record.replace("_", "."))
    level = logging.WARNING if fields.get("result") in {"error", "failure", "timeout"} else logging.INFO
    logger.event("voice." + event, level=level, **{k: v for k, v in fields.items() if v != ""})
