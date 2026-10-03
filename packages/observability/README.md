# MarsDog observability

Pure Python 3.10+ infrastructure with no runtime third-party dependencies. Install the fixed
0.1.0 distribution independently in each module environment; colcon also installs the same
source as marsdog_observability. No business module imports, source-path injection or ROS
imports on ordinary package import.

Public API: configure(component, log_dir=None, level=None), emit, emit_json, bind_context,
wrap_context, get_stats and shutdown. StructuredLogger and BoundedFileHandler preserve
the existing readable logger interfaces. The optional marsdog_observability.ros.main entry
observes /rosout without changing native ROS filters or call sites.

Records use UTC millisecond timestamps, monotonic_ns, run_id, process instance UUID,
component, PID, sequence, severity, event_name, logger, message and a fields object.
Existing interaction/utterance/candidate/goal/target identities are promoted when present;
they are never synthesized from a behavior name. Fields retain owner-specific meanings.

Normal and important records use separately bounded queues. File writes occur on one
daemon worker per process. Priority is reserved for warning/error and terminal/result
records; even this queue may overflow and exposes its own loss counter. Shutdown drains
with a bounded wait; abrupt termination or a stuck filesystem cannot guarantee delivery.
Health JSON and stderr degradation notices make failures visible without failing behavior.

Each UTF-8 JSONL file defaults to 20 MiB with four backups. Each normalized record is
bounded to 16 KiB; oversized records retain bounded identities and an explicit omission
reason. Sensitive-key redaction covers a small declared set, not arbitrary message text.
Legacy text/trace outputs remain separate compatibility artifacts.

Run tests: python3 -B -m unittest discover -s tests -v from this directory.
Operational configuration, query and retention: ../../docs/development/UNIFIED_LOGGING.md.
