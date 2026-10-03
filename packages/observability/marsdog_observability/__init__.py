"""Infrastructure only: no ROS/model/business imports and no import-time I/O."""
from .runtime import bind_context, configure, emit, emit_json, enabled, get_stats, shutdown, wrap_context
from .formatting import BoundedFileHandler, StructuredLogger

__version__ = "0.1.0"
__all__ = ["bind_context", "configure", "emit", "emit_json", "enabled", "get_stats", "shutdown",
           "wrap_context", "BoundedFileHandler", "StructuredLogger"]
