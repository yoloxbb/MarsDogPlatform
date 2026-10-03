"""Opt-in local decision evidence. Never participates in behavior decisions."""
from __future__ import annotations
import json
from marsdog_observability import emit as observe, enabled
import logging
import os
from pathlib import Path
import threading
import time

_LOCK = threading.Lock()
_LAST = {}
_WARNED = False
_FIELDS = ("interaction_id", "utterance_id", "wake_id", "event_type", "trigger_event",
           "command_id", "intent", "source", "behavior_name", "candidate_id",
           "behavior_id", "goal_id", "priority_level", "value", "status", "result", "reason")


def emit(stage, item=None, *, repeat_key=None, **details):
    """Write one JSONL observation when MARSDOG_DECISION_TRACE_DIR is explicit.

    Records contain existing identities, no added wire fields. Diagnostics fail
    open, and repeated wait reasons are coalesced without changing the queue.
    """
    directory = os.environ.get("MARSDOG_DECISION_TRACE_DIR")
    if not directory and not enabled():
        return
    global _WARNED
    try:
        get = item.get if isinstance(item, dict) else lambda k, d=None: getattr(item, k, d)
        params = get("params", {}) or {}
        record = {key: get(key, params.get(key)) for key in _FIELDS
                  if isinstance(get(key, params.get(key)), (str, int, float, bool))}
        record.update(details)
        record.update(schema_version=1, component="behavior", stage=stage, pid=os.getpid())
        signature = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with _LOCK:
            key = (directory, stage, repeat_key)
            if repeat_key is not None and _LAST.get(key) == signature:
                return
            record.update(timestamp=time.time(), monotonic_ns=time.monotonic_ns())
            observe("behavior." + stage, record)
            if directory:
                path = Path(directory)
                path.mkdir(parents=True, exist_ok=True)
                with (path / ("behavior-" + str(os.getpid()) + ".jsonl")).open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            if repeat_key is not None:
                if len(_LAST) >= 4096:
                    _LAST.pop(next(iter(_LAST)))
                _LAST[key] = signature
    except Exception:
        # An unavailable sink or malformed diagnostic value must not change
        # action ownership, lifecycle, timing decisions or event authorization.
        if not _WARNED:
            logging.getLogger(__name__).warning("Decision trace unavailable; behavior processing continues")
            _WARNED = True
