"""Vision event vocabulary and sampling; all persistence belongs to observability."""
import logging
import os
import threading
from typing import Any
from marsdog_observability import get_logger as project_logger, set_level as set_log_level

_trace_enabled = True
_trace_context = {}
_trace_logger = project_logger("marsdog_vision_interaction.events")
_timing_trace_interval_ms = 5000.0
_timing_trace_last_ms = {}
_timing_trace_lock = threading.Lock()
_EVENTS = {"runtime_start": "providers.ready", "runtime_stop": "providers.stopped",
           "stage_complete": "stage.completed", "event_publish": "event.published",
           "event_suppressed": "event.suppressed"}


def get_logger(name, module=""):
    return project_logger(name, area=module) if module else project_logger(name)


def configure_event_trace(*, enabled=True, run_id="", case_id="", timing_interval_sec=5.0):
    """Configure domain sampling only; no handlers or files are created here."""
    global _trace_enabled, _trace_context, _timing_trace_interval_ms
    _trace_enabled = bool(enabled)
    _trace_context = {"test_run_id": str(run_id or os.environ.get("MARSDOG_TEST_RUN_ID", "")),
                      "case_id": str(case_id or os.environ.get("MARSDOG_TEST_CASE_ID", ""))}
    _timing_trace_interval_ms = max(0.0, float(timing_interval_sec)) * 1000.0
    with _timing_trace_lock:
        _timing_trace_last_ms.clear()


def vision_trace(record, **fields):
    if not _trace_enabled:
        return
    level = logging.WARNING if fields.get("result") in {"failure", "error", "timeout"} else logging.INFO
    if record == "event_suppressed":
        level = logging.DEBUG
    kind = "metric" if record == "stage_complete" else "event"
    _trace_logger.event("vision." + _EVENTS.get(record, record.replace("_", ".")),
                        level=level, kind=kind, **{**_trace_context, **fields})


def vision_timing_trace(
    *,
    node: str,
    module: str,
    stage: str,
    latency_ms: float,
    result: str = "success",
    force: bool = False,
    **fields: Any,
) -> bool:
    """Emit a rate-limited ``stage_complete`` timing record.

    Continuous vision stages execute several times per second.  Rate limiting
    keeps QA timing evidence available without making file logging part of the
    measured workload.  Set ``timing_interval_sec`` to zero to trace every run;
    on-demand stages may pass ``force=True``.
    """
    if not _trace_enabled:
        return False
    force = bool(force or str(result) not in {"success", "skipped"})
    now_ms = time_monotonic_ms()
    key = (str(node), str(module), str(stage))
    with _timing_trace_lock:
        previous_ms = _timing_trace_last_ms.get(key)
        if (
            not force
            and _timing_trace_interval_ms > 0.0
            and previous_ms is not None
            and now_ms - previous_ms < _timing_trace_interval_ms
        ):
            return False
        _timing_trace_last_ms[key] = now_ms
    vision_trace(
        "stage_complete",
        result=str(result),
        node=str(node),
        module=str(module),
        stage=str(stage),
        latency_ms=round(max(0.0, float(latency_ms)), 3),
        sampled=not force,
        **fields,
    )
    return True


def time_monotonic_ms() -> float:
    """Small wrapper kept separate for deterministic trace tests."""
    import time

    return time.monotonic_ns() / 1_000_000.0
