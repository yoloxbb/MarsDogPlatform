# Unified log envelope v1

Infrastructure records use log_schema_version=1. This is not a new ROS or application
message version; audio-event-v2, visual-event-v1 and ExecuteBehavior remain unchanged.

Required fields: timestamp (UTC ISO-8601 milliseconds), monotonic_ns (integer), host,
run_id, component, instance_id (fresh for each process), pid, sequence, level, event_name,
logger, message and fields (object). A normalized record is one UTF-8 JSON line.

Optional promoted identities: interaction_id, utterance_id, wake_id, candidate_id,
behavior_id, goal_id, target_id, vision_epoch. A missing identity stays absent.
The fields object retains domain data. Log event_name (e.g. action.terminal) and business
event_type (e.g. EVT_VOICE_COMMAND_SIT) are separate names.

Python exceptions are captured in exception without losing the standard exc_info API.
Timestamp describes when the record was observed. ROS collector records additionally
carry source_timestamp_ns, source_logger, source_component and original source location.
Do not compare monotonic clocks between different hosts/boots or infer causality solely
from adjacent timestamps. An instance_id plus sequence distinguishes repeated messages.

VOICE_TRACE, VISION_TRACE, BTLogger event JSON and decision-trace-v1 are retained in their
legacy outputs. Their normalized counterparts reference the same input identities;
old trace parsers do not consume the new envelope.

Log schemas and log levels never authorize motion or settle demand. Acceptance uses
actual DDS/Action results. Missing records, drop counters or sink errors mean an
incomplete diagnostic view, never proof that an action did not occur.

Tests: packages/observability/tests and integration/platform/tests/test_unified_logging.py.
