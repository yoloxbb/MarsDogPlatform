"""Single logging API; no ROS/model imports or import-time I/O."""
from .runtime import (bind_context, configure, current_log_path, emit, enabled, get_stats,
                      set_level, shutdown, wrap_context)
from .logger import get_logger

__version__ = "0.2.0"
__all__ = ["bind_context", "configure", "current_log_path", "emit", "enabled", "get_stats",
           "set_level", "shutdown", "wrap_context", "get_logger"]
