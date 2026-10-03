# Unified log envelope v2

`marsdog-observability==0.2.0` writes one UTF-8 JSON object per line. This deliberately
replaces all project log formats; it does not change ROS messages, actions or services.
Readers require `log_schema_version=2`. Historical v1 files are neither rewritten nor deleted.

| Field | Meaning |
| --- | --- |
| log_schema_version | Integer 2 |
| timestamp | Observation time, UTC ISO-8601 milliseconds |
| monotonic_ns | Local monotonic observation clock, integer nanoseconds |
| run_id | Shared run identity assigned by the launcher |
| component | voice / vision / emotion / behavior / action / ros |
| instance_id, pid, host | Fresh process instance UUID, process ID, hostname |
| sequence | Increasing within an instance; priority queues can reorder file lines |
| level | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| kind | event / lifecycle / diagnostic / metric |
| event_name | Stable dotted name, e.g. action.execution.completed |
| logger, message | Source logger and human-readable message; may be empty for events |
| context | Existing correlation IDs, never synthesized business IDs |
| fields | Domain attributes; no duplicate promoted identity fields |
| source | Optional file / line / function, plus transport for ROS |
| exception | Optional formatted Python traceback |

`context` accepts interaction_id, utterance_id, wake_id, candidate_id, goal_id,
behavior_id, target_id, vision_epoch, request_id, case_id and test_run_id.
Absent identities stay absent. `test_run_id` identifies a QA round; it is distinct from
the launcher-owned `run_id`. Domain fields such as event_type, stage, reason, status,
latency_ms retain their owning module's semantics. Log event names are not EVT_* business events.

`event` describes an observed domain transition; `lifecycle` marks process/goal terminal
or boundary records and reserves queue capacity; `diagnostic` is implementation detail;
`metric` is a sampled timing observation. Severity is independent of kind.

ROS records use `event_name=ros.message`, `component=ros`, `source.transport=rosout`;
fields.source_component identifies the original node's registered module and
fields.source_timestamp_ns preserves the original timestamp. Native ROS once/throttle
semantics are untouched. Arbitrary ROS text cannot reliably supply business context.

Do not compare monotonic clocks across hosts/boots or infer causality solely from adjacent
lines. Query by context and instance/sequence. Logs are observations, not execution or
settlement evidence: authoritative results remain on the original DDS/Action interfaces.
Missing records and dropped counters never prove an action did not occur.

See [usage and event ownership](../../docs/development/UNIFIED_LOGGING.md).
Tests: packages/observability/tests and integration/platform/tests/test_unified_logging.py.
