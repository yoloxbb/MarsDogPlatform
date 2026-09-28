# P3a: BehaviorTree software migration

Status: independently verified on 2026-09-28. P3b Action is still pending.

The source is 20260702_MarsDogTree at 9f2eb0dee84f84bb84a4e497aba4e3effe4d10da.
All 7 reachable commits and original refs were restored from a verified bundle.
The prefix-only import preserved all 90 tracked file contents/modes. See
history/behavior-import.json and behavior-commit-map.txt for full provenance.

## Scope

- Keep marsdog_behavior / bionic_dog_bt, ROS package and every existing launch,
  message type, endpoint, config byte and default behavior.
- Fix ordinary Python wheel config discovery with a final sys.prefix/share
  fallback; preserve explicit, environment, source and ROS share precedence.
- Add the existing behavior_tree_node console entry to PEP 621 metadata so it is
  no longer lost during modern wheel builds. Keep both demos.
- Pin the validated wheel backend. The module's original uv.lock is unchanged.

No arbitration, voice session, attention, goal lifecycle, result mapping, action
ownership, or cancellation implementation was changed. BT chooses behavior; Action
remains the execution provider, and Needs remains the authoritative demand state.

## Evidence

| Check | Result and scope |
| --- | --- |
| Full original suite + four config regressions | 532 passed; no skips; module-isolated Python environment |
| Old Action → new BT → new Needs | 17 passed; three independent processes; existing result semantics |
| Clean installed wheel | All seven YAML hashes unchanged; three callable entry points; 106 behavior specs; no ROS |
| ROS Humble colcon build | Passed using the separate Humble tool lock |
| Old and new installed ActionClientAdapter | Real generated original ExecuteBehavior IDL + DDS, fake server; success metadata and feedback preserved |
| Cancel lifecycle | Both retain ownership after CancelGoal ACK, ignore premature removal, and release only after terminal result; measured delay about 0.36 seconds |
| Original sources | Seven repositories still match the immutable baseline |

Small reports are in validation/p3-behavior. The reproducible historical comparison
runner is integration/migration/tools/check_p3_behavior.py; raw logs and build
prefixes are retained in the external migration workspace. The checked ROS transport
is the marsdog_action_executor/action/ExecuteBehavior fallback; the production
presence/type of external marsdog_interfaces remains UNKNOWN.

The complete BT/Action runtime and hardware have not been certified. The original
BT repository/install remains available for rollback; there has been no robot switch.

## Review

Only packaging/config discovery changed after the mechanical import. No new business
dependency or common module was added. The runtime dependency graph did not change.
The same fixtures pass with legacy and migrated consumers. Runtime release approval
remains separate from these software checks.
