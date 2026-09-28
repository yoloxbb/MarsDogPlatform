# Energy settlement: evidence and pending behavior decision

Status: approved and implemented in the platform working tree. 2026-09-28.
The audit below records pre-change behavior. See the implementation addendum and
interfaces/application/BATTERY_OBSERVATION.md for the current contract.

## Verified current paths

| Layer | Code evidence | Current behavior |
| --- | --- | --- |
| Action | modules/action/marsdog_action_executor/ros_node.py:404,2621,2917 | restInPlace/recharge success reads recharge_result_energy_value parameter, default 100; no BMS read in that helper |
| Lite3 input | modules/action/marsdog_action_executor/adapters/lite3_backend.py:89,172 | subscribes transfer_interfaces/msg/RobotStatus on /robot_status; copies battery_level into backend status; not connected to recharge result helper |
| Completion flag | modules/action/marsdog_action_executor/ros_node.py:2630 | derives charging_completed from Lite3 semantic_effect != simulated; this is not a charger sensor observation |
| BT | modules/behavior/marsdog_behavior/result_event_mapper.py:90,122 | successful recharge missing/invalid metadata becomes energyValue=100 |
| Needs | modules/emotion/marsdog_core/need_system.py:188 | missing completed recharge metadata falls back to rechargeTarget=100 |

Repository search found no charging_completed consumer in BT or Needs source.
No battery/charging publisher was identified in the searched robot_ws source files;
external publisher implementation, deployed type version, units, validity, timestamps,
and the production chassis remain UNKNOWN. Lite3RobotStatus existence is evidence
of an expected input, not evidence that the topic is deployed or accurate.

The recharge candidate ACT_RETURN_TO_CHARGER is a task but the selected adapter
lacks execute_task; its failure must not be hidden. The alternative existing
ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER proxy can succeed and then publish 100 by default.

## Executed characterization

Run integration/migration/tools/audit_energy_settlement.py using an ordinary Python
interpreter. It launches each business module in its own existing .venv, removes
ROS environment contamination and calls the real mapper and Needs adapter. It
reads business configuration but writes no robot state; stdout is the report.
Saved result: validation/navigation-recovery/energy-settlement-audit.json.

Starting Energy demand is 90 (need magnitude, not battery percentage):

| Input to successful recharge mapper | Output energyValue | Final Energy demand |
| --- | --- | --- |
| Missing | 100 | 0 |
| Invalid string | 100 | 0 |
| 100 with charging_completed=false | 100 | 0 |
| 88 without observation provenance | 88 | 12 |
| Direct Needs completed event, no metadata | Needs defaults to 100 | 0 |

Each mapped event applies once and its identical replay is rejected. Deduplication
works; it does not validate the truth of the initial battery observation.

## Recommended decision

A completed action is not battery evidence. Only a valid, non-simulated observation
may update Energy. Missing, invalid, stale or proxy-only evidence preserves the
last demand value. Do not replace the default 100 with 0: that would fabricate an
empty battery instead. No new dock/BMS firmware protocol is proposed here.

This changes existing robot behavior and is awaiting explicit approval. The user
has been asked whether to approve this fail-closed settlement policy. Until then,
all three production fallbacks and existing tests remain unchanged.

After approval, implement a coordinated slice across Action, BT and Needs rather
than removing only Action's fallback (BT and Needs would recreate it). Keep the
existing ROS service/action types and JSON event endpoint; specify any additional
observation metadata as an internal application contract with compatibility tests.
Do not mark old scalar values as measured merely by wrapping them in new fields.

## Boundaries for the next implementation

- Action owns access to any existing chassis observation and its validation. It
  does not declare docking or charge completion based on navigation arrival.
- BT forwards evidence without generating an energy measurement or completing it
  from a launch parameter. Event routing/arbitration remains unchanged.
- Needs validates the application event before updating Energy and continues to
  deduplicate accepted events. Event-ID consumption for rejected evidence must be
  explicitly tested; late evidence must not silently reuse a consumed identifier.
- A battery observation can justify updating battery-derived demand without proving
  that docking completed. Keep action completion and battery value conceptually
  separate; do not use one field as proof of the other.
- Until units/freshness/source semantics are verified, no external battery adapter
  is enabled. Missing hardware code is not invented.

## Verification and rollout

Cover measured finite in-range values, missing/invalid/bool/non-finite/out-of-range
values, stale/future observations, simulation flags, mismatched task/source,
explicit incomplete charging, repeated events and old/new producer-consumer mixes.
Repeat the true tree -> Action -> waypoint -> fake Nav2 tests and independent Needs
process settlement, preserving go_home and cancellation regression results.

This is a behavioral compatibility change even with unchanged ROS IDL. Deploy
Action/BT/Needs together in a known profile; an old mapper or Needs consumer can
restore unsafe defaults. Production release remains blocked pending policy approval
and identification of a real telemetry source. Other module migration can proceed
independently; there is no requirement to invent a BMS to continue platform work.


## Implementation addendum (supersedes pending wording above)

User approval was received. Action no longer consumes its configured percentage
as a reading; BT no longer repairs metadata; Needs validates the versioned
battery_observation envelope before any recharge-result adjustment. Charge
cancellation/timeouts and direct Recharge() also require evidence. Other needs'
interrupted-result rules are unchanged. Existing initialization and explicit
simulation setters are outside this settlement change.

No live producer was enabled; without a verified observation Energy is unchanged.
This closes the false-full-battery path but does not implement docking or the
missing execute_task handler. Proxy success remains behavior success while no
longer settling battery-derived demand. This was verified through the real tree
execution/Action/navigation test with an isolated Needs process.

Validation commands use separate environments. Historical cases.json is retained;
set MARSDOG_RESULT_FIXTURE to energy-evidence-cases.json when testing migrated
sources. CI has this override; no hosted CI run has been performed.

Clean-wheel checks for all three modules passed with UV_OFFLINE=1 and the retained
migration/.cache/uv. Actual installed Needs ROS check passed: measured 88 -> Energy
12; duplicate stays 12; subsequent legacy scalar 100 stays 12. This is a synthetic
observation, not a hardware reading. The navigation test uses modified BT source;
its separate public Action probe still intentionally checks the retained installed
BT adapter transport, whose old mapper is not used by that probe.

Rollback must be coordinated across consumers/producers: reverting only Needs
restores the old missing-value full-charge behavior. Preserve persisted state;
do not compensate by writing a fake 0 or 100. Production remains unvalidated.
