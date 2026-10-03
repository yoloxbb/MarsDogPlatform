"""Legacy-readable text helpers shared by Voice, Vision and Behavior."""
import logging
from logging.handlers import RotatingFileHandler


class StructuredLogger(logging.Logger):
    def _log_with_kwargs(self, level, msg, *args, **kwargs):
        standard = {key: kwargs.pop(key) for key in tuple(kwargs)
                    if key in {"exc_info", "extra", "stack_info", "stacklevel"}}
        if kwargs:
            extra = dict(standard.get("extra") or {})
            extra["marsdog_fields"] = {**extra.get("marsdog_fields", {}), **kwargs}
            standard["extra"] = extra
            msg = str(msg) + "  " + "  ".join(f"{key}={value!r}" for key, value in kwargs.items())
        self._log(level, msg, args, **standard)

    def debug(self, msg, *args, **kwargs):
        if self.isEnabledFor(logging.DEBUG):
            self._log_with_kwargs(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        if self.isEnabledFor(logging.INFO):
            self._log_with_kwargs(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        if self.isEnabledFor(logging.WARNING):
            self._log_with_kwargs(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        if self.isEnabledFor(logging.ERROR):
            self._log_with_kwargs(logging.ERROR, msg, *args, **kwargs)


class BoundedFileHandler(RotatingFileHandler):
    """UTF-8 byte bounds including an oversized-record replacement."""
    def __init__(self, filename, max_bytes=20 * 1024 * 1024, backups=4,
                 oversized_message='{"record":"log_record_omitted","reason":"exceeds_file_limit"}'):
        super().__init__(filename, maxBytes=max_bytes, backupCount=backups, encoding="utf-8", delay=True)
        self.oversized_message = oversized_message

    def emit(self, record):
        try:
            if len((self.format(record) + self.terminator).encode("utf-8")) > self.maxBytes:
                record = logging.makeLogRecord(dict(record.__dict__))
                record.msg, record.args = self.oversized_message, ()
                record.exc_info = record.exc_text = record.stack_info = None
            super().emit(record)
        except Exception:
            self.handleError(record)

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        return self.stream.tell() + len((self.format(record) + self.terminator).encode("utf-8")) > self.maxBytes
