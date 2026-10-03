# MarsDog observability 0.2

Standard-library-only infrastructure for Python 3.10+. Each business module installs the
fixed 0.2.0 wheel in its independent environment; colcon installs the same source as
marsdog_observability. Imports do not start threads, create files or import ROS/models.

Public API: configure, get_logger, emit, bind_context, wrap_context, set_level,
current_log_path, enabled, get_stats, shutdown. get_logger returns an explicit
LoggerAdapter; no global Logger subclass replacement. Ordinary stdlib logging is
captured by the same root handler after configure. No legacy text/TRACE/BT JSON sink.

One bounded asynchronous writer owns each process's canonical JSONL file and rotation.
Console output is a view of the same records. lifecycle and warning/error records use a
reserved bounded queue. Queue/sink failures do not fail business operations; health
counters and rate-limited stderr warnings expose loss. Defaults: 20 MiB, four backups,
16 KiB maximum record, shutdown drain up to three seconds. The optional ros.main
collector adapts native /rosout without wrapping RcutilsLogger or changing call sites.

```python
from marsdog_observability import configure, get_logger, bind_context, shutdown

configure("action")  # once, in the process entrypoint
log = get_logger(__name__)
with bind_context(goal_id="existing-goal"):
    log.event("action.execution.started", kind="lifecycle", behavior_name="sit_down")
    log.info("Waiting for adapter", adapter="chassis")
shutdown()
```

[Protocol v2](../../interfaces/observability/README.md) ·
[operation, configuration and extension](../../docs/development/UNIFIED_LOGGING.md).
Run `python3 -B -m unittest discover -s tests -v` from this directory.
