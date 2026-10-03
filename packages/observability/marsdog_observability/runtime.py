"""Bounded per-process JSONL logging; writing never runs on the caller thread."""
from __future__ import annotations
import atexit
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from datetime import datetime, timezone
import itertools
import json
import logging
import os
from pathlib import Path
import queue
import re
import socket
import sys
import threading
import time
import uuid

from .sinks import BoundedFileHandler
from .formatting import render_record

_context = ContextVar("marsdog_log_context", default={})
_session = None
_handler = None
_config_lock = threading.RLock()
_IDS = ("interaction_id", "utterance_id", "wake_id", "candidate_id", "goal_id",
        "behavior_id", "target_id", "vision_epoch", "request_id", "case_id", "test_run_id")
_SECRET = {"password", "authorization", "api_key", "access_token", "refresh_token"}


def _safe(value, depth=0):
    if depth > 5:
        return "[depth limit]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else str(value)
    if isinstance(value, str):
        return value[:4096]
    if isinstance(value, dict):
        return {str(k)[:128]: "[redacted]" if str(k).lower() in _SECRET else _safe(v, depth + 1)
                for k, v in itertools.islice(value.items(), 64)}
    if isinstance(value, (list, tuple)):
        return [_safe(v, depth + 1) for v in value[:64]]
    return repr(value)[:512]


@contextmanager
def bind_context(**fields):
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def wrap_context(function):
    """Capture submission context for a thread/callback; isolate every invocation."""
    captured = copy_context()
    def wrapped(*args, **kwargs):
        return captured.copy().run(function, *args, **kwargs)
    return wrapped


def _integer(name, default, minimum, maximum):
    try:
        return min(maximum, max(minimum, int(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


class _Sink(BoundedFileHandler):
    def handleError(self, record):
        raise OSError("structured log sink failed")


class Session:
    def __init__(self, component, directory, run_id, level=logging.INFO, capacity=1024,
                 priority_capacity=128, max_bytes=20 * 1024 * 1024, backups=4, sink=None, console=False):
        self.console = console
        self.component, self.directory, self.run_id, self.level = component, Path(directory), str(run_id)[:128], level
        self.pid, self.instance_id = os.getpid(), uuid.uuid4().hex
        self.host = socket.gethostname()
        self.sequence = itertools.count(1)
        self.normal, self.priority = queue.Queue(capacity), queue.Queue(priority_capacity)
        self.wake, self.stop = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.stats = {"written": 0, "dropped": 0, "priority_dropped": 0, "sink_errors": 0,
                      "oversized": 0, "coalesced": 0}
        self.last = {}
        self.sink = sink
        self.max_bytes, self.backups = max_bytes, backups
        self.path = self.directory / f"{component}-{self.instance_id}.jsonl"
        self.health_path = self.path.with_suffix(".health.json")
        self.last_warning = 0.0
        self.thread = threading.Thread(target=self._run, name="marsdog-log-writer", daemon=True)
        self.thread.start()

    def record(self, event_name, fields=None, *, level=logging.INFO, message="", logger="", repeat_key=None, exception=None, kind="event", source=None):
        if self.stop.is_set() or level < self.level:
            return False
        try:
            fields = _safe({**_context.get(), **(fields or {})})
            key = (event_name, str(repeat_key)) if repeat_key is not None else None
            signature = json.dumps(fields, sort_keys=True, ensure_ascii=False) if key else None
            context = {key: fields.pop(key) for key in _IDS if key in fields}
            row = {"log_schema_version": 2, "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                   "monotonic_ns": time.monotonic_ns(), "host": self.host, "run_id": self.run_id,
                   "component": self.component, "instance_id": self.instance_id, "pid": self.pid,
                   "sequence": next(self.sequence), "level": logging.getLevelName(level),
                   "kind": kind, "event_name": str(event_name)[:128], "logger": str(logger)[:256], "message": str(message)[:4096],
                   "context": context, "fields": fields}
            if source:
                row["source"] = _safe(source)
            if exception:
                row["exception"] = str(exception)[:8192]
            line = json.dumps(row, ensure_ascii=False, allow_nan=False)
            if len(line.encode("utf-8")) > min(16384, self.max_bytes) - 1:
                with self.lock:
                    self.stats["oversized"] += 1
                row["message"], row["fields"] = "[oversized log record]", {"reason": "record_size_limit"}
                row.pop("exception", None)
                # Identity values themselves may be large; bound the fallback too.
                row["context"] = {key: str(value).encode("utf-8")[:64].decode("utf-8", errors="ignore")
                                  for key, value in context.items()}
                row.pop("source", None)
                for key in ("run_id", "logger", "event_name"):
                    row[key] = row[key].encode("utf-8")[:128].decode("utf-8", errors="ignore")
                line = json.dumps(row, ensure_ascii=False)
            important = level >= logging.WARNING or kind == "lifecycle"
            destination = self.priority if important else self.normal
            with self.lock:
                if self.stop.is_set():
                    return False
                if key and self.last.get(key) == signature:
                    self.stats["coalesced"] += 1
                    return True
                try:
                    destination.put_nowait((row, line))
                except queue.Full:
                    self.stats["priority_dropped" if important else "dropped"] += 1
                    self.wake.set()
                    return False
                # Only accepted records suppress repeats; a full queue must allow retry.
                if key:
                    if len(self.last) >= 4096 and key not in self.last:
                        self.last.pop(next(iter(self.last)))
                    self.last[key] = signature
            self.wake.set()
            return True
        except Exception:
            with self.lock:
                self.stats["dropped"] += 1
            return False

    def _warning(self):
        now = time.monotonic()
        if now - self.last_warning >= 30:
            self.last_warning = now
            try:
                sys.stderr.write("MarsDog structured logging degraded; inspect log health counters.\n")
            except Exception:
                pass

    def _write(self, line):
        try:
            if self.console:
                try:
                    sys.stderr.write(render_record(json.loads(line)) + "\n")
                except Exception:
                    pass
            if self.sink is None:
                self.directory.mkdir(parents=True, exist_ok=True)
                self.sink = _Sink(self.path, max_bytes=self.max_bytes, backups=self.backups)
                self.sink.setFormatter(logging.Formatter("%(message)s"))
            self.sink.emit(logging.LogRecord("marsdog", logging.INFO, "", 0, line, (), None))
            with self.lock:
                self.stats["written"] += 1
        except Exception:
            with self.lock:
                self.stats["sink_errors"] += 1
            self._warning()

    def snapshot(self):
        with self.lock:
            return {**self.stats, "pending": self.normal.qsize() + self.priority.qsize(),
                    "run_id": self.run_id, "instance_id": self.instance_id, "component": self.component,
                    "pid": self.pid, "writer_alive": self.thread.is_alive()}

    def _health(self, final=False):
        health = self.snapshot()
        health["closed"] = final
        if final:
            health["writer_alive"] = False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.health_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(health) + "\n", encoding="utf-8")
            temporary.replace(self.health_path)
        except Exception:
            self._warning()
        if health["dropped"] or health["priority_dropped"] or health["sink_errors"]:
            self._warning()

    def _run(self):
        last_health = 0
        while not self.stop.is_set() or not self.priority.empty() or not self.normal.empty():
            self.wake.clear()
            # One from each queue avoids starving normal logs during error bursts.
            processed = False
            for pending in (self.priority, self.normal):
                try:
                    _, line = pending.get_nowait()
                except queue.Empty:
                    continue
                self._write(line)
                pending.task_done()
                processed = True
            if time.monotonic() - last_health > 5:
                self._health()
                last_health = time.monotonic()
            if not processed:
                self.wake.wait(0.1)
        if self.sink is not None:
            try:
                self.sink.close()
            except Exception:
                self._warning()
        self._health(final=True)

    def close(self, timeout=3):
        with self.lock:
            self.stop.set()
        self.wake.set()
        self.thread.join(timeout)
        if self.thread.is_alive():
            self._warning()
        return not self.thread.is_alive()


class _Handler(logging.Handler):
    def emit(self, record):
        session = _session
        if session is None:
            return
        try:
            exception = logging.Formatter().formatException(record.exc_info) if record.exc_info else None
            session.record(getattr(record, "marsdog_event", "log.message"),
                           getattr(record, "marsdog_fields", {}), level=record.levelno,
                           logger=record.name, message=record.getMessage(), exception=exception,
                           kind=getattr(record, "marsdog_kind", "diagnostic"),
                           repeat_key=getattr(record, "marsdog_repeat_key", None),
                           source={"file": record.pathname, "line": record.lineno, "function": record.funcName})
        except Exception:
            pass


def configure(component, log_dir=None, *, level=None, console=None, node=None):
    """Idempotent per process. Explicit env overrides node-local defaults."""
    global _session, _handler
    if os.environ.get("MARSDOG_LOG_DISABLED") == "1":
        return None
    with _config_lock:
        if _session is not None and _session.pid == os.getpid():
            return _session
        try:
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", component):
                raise ValueError("invalid log component")
            directory = os.environ.get("MARSDOG_LOG_DIR") or str(Path(log_dir or "log") / "structured")
            level_name = os.environ.get("MARSDOG_LOG_LEVEL", level or "INFO").upper()
            numeric = getattr(logging, level_name, logging.INFO)
            if not isinstance(numeric, int):
                numeric = logging.INFO
            _session = Session(component, directory, os.environ.get("MARSDOG_RUN_ID") or uuid.uuid4().hex, numeric,
                               _integer("MARSDOG_LOG_QUEUE_SIZE", 1024, 8, 8192),
                               _integer("MARSDOG_LOG_PRIORITY_QUEUE_SIZE", 128, 8, 1024),
                               _integer("MARSDOG_LOG_MAX_BYTES", 20*1024*1024, 4096, 100*1024*1024),
                               _integer("MARSDOG_LOG_BACKUPS", 4, 1, 20),
                               console=(os.environ.get("MARSDOG_LOG_CONSOLE") == "1" if "MARSDOG_LOG_CONSOLE" in os.environ
                                        else (sys.stderr.isatty() if console is None else console)))
            root = logging.getLogger()
            if _handler is not None:
                root.removeHandler(_handler)
            _handler = _Handler()
            root.addHandler(_handler)
            root.setLevel(numeric)
            _session.record("runtime.started", {"library_version": "0.2.0", "node": node}, kind="lifecycle")
            return _session
        except Exception:
            return None


def set_level(level):
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logging.getLogger().setLevel(numeric)
    if _session is not None:
        _session.level = numeric


def current_log_path():
    return str(_session.path) if enabled() else ""


def enabled():
    return _session is not None and not _session.stop.is_set()


def emit(event_name, fields=None, *, level=logging.INFO, repeat_key=None, kind="event", **details):
    if not enabled():
        return False
    try:
        return _session.record(event_name, {**(fields or {}), **details}, level=level, repeat_key=repeat_key, kind=kind)
    except Exception:
        return False


def get_stats():
    return _session.snapshot() if _session is not None else {}


def shutdown(timeout=3):
    global _session, _handler
    with _config_lock:
        session, _session = _session, None
        if _handler is not None:
            logging.getLogger().removeHandler(_handler)
            _handler = None
        if session is None:
            return True
        session.record("runtime.stopped", kind="lifecycle")
        return session.close(timeout)


atexit.register(shutdown)
