"""Project logger API without global Logger subclass registration."""
import logging


class ProjectLogger(logging.LoggerAdapter):
    def log(self, level, msg, *args, **kwargs):
        if not self.isEnabledFor(level):
            return
        standard = {k: kwargs.pop(k) for k in tuple(kwargs)
                    if k in {"exc_info", "extra", "stack_info", "stacklevel"}}
        extra = dict(standard.get("extra") or {})
        extra["marsdog_fields"] = {**self.extra, **extra.get("marsdog_fields", {}), **kwargs}
        standard["extra"] = extra
        standard["stacklevel"] = standard.get("stacklevel", 1) + 1
        self.logger.log(level, msg, *args, **standard)

    def event(self, name, *, level=logging.INFO, kind="event", repeat_key=None, **fields):
        fields.setdefault("stacklevel", 2)  # skip this adapter's event frame as well
        self.log(level, "", extra={"marsdog_event": name, "marsdog_kind": kind,
                                  "marsdog_repeat_key": repeat_key}, **fields)

    def bind(self, **fields):
        return ProjectLogger(self.logger, {**self.extra, **fields})


def get_logger(name, **fields):
    return ProjectLogger(logging.getLogger(name), fields)
