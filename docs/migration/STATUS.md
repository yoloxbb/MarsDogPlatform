# Migration status — 2026-09-28

| Phase | Status | Evidence / remaining gate |
| --- | --- | --- |
| P0 | Approved proposal | Frozen copy in docs/architecture/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md |
| P1 | Baseline / software contract slice complete | 7 source snapshots, 3,074 files, 38 ROS manifests, 48 IDLs; existing tests and known gaps retained |
| P2 | Emotion software migration verified | 19 commits preserved; 350 cases; wheel/ROS installed-state equivalence |
| P3a | BehaviorTree software migration verified | 7 commits preserved; 532 cases; wheel/ROS adapter checks |
| P3b | Action software migration verified with stated transport limits | 5 commits preserved; 418 pure passes / 29 skips; old/new 39 ROS callback cases each; four UDP DDS combinations pass |
| P4 | Environment gate blocked; not migrated | Uncached locked Torch / sherpa-onnx-core; PyPI and checked mirrors time out at TLS handshake; no full regression/model acceptance |
| P5 | Supplemental navigation/interface slice verified | New supplied packages copied; explicit operator recovery release approved/tested; robot_ws / rtabmap_ws unchanged; see P5_NAVIGATION_RECOVERY.md |
| P6 | Not released | No remote/hosted CI run, production profile or hardware acceptance; default Fast DDS issue unresolved |
| P7 | Not started | No uncertain production code retired |

All seven original repositories remain unchanged. Only the three imported modules
have verified all-ref bundles and commit maps; the others are not claimed archived.
No production process, ROS protocol, robot behavior, model runtime or external
motion-control/embedded implementation was replaced.

Each phase's small JSON/JUnit reports are versioned under validation. Larger raw
logs, snapshots, build trees and bundles remain in the original migration workspace.
The committed GitHub workflows have corresponding local command checks, but no
remote run or branch protection has been configured. Actual CODEOWNERS identities
remain UNKNOWN; role ownership is recorded, not represented by invented accounts.

The final integration run passes 20 cases: 13 independent-process result fixtures,
4 baseline drift checks and 3 migrated-module protocol/default-asset guards.

New marsdog_interfaces and waypoint_nav source was supplied and copied as a
supplemental P5 slice; see P5_NAVIGATION_RECOVERY.md. Their production deployment,
production launch/profile, real owner accounts and hardware acceptance still
require real deployment facts. These gates do not
justify weakening independent software regression or changing robot behavior.

Next runnable slice: restore access to the locked artifacts (or supply a verified
offline cache), run original Vision/Voice tests in their separate environments,
then migrate one module at a time. Do not downgrade pins, omit declared dependencies
and call it a full-environment pass, or move implementations before their baseline.
Native Robotics/vendor replay and production hardware gates are still pending.


The supplemental connected navigation gate now covers real BT transport adapter ->
Action node -> waypoint service -> fake Nav2 with 28 tests plus 2 subtests passing.
See P5_NAVIGATION_RECOVERY.md for isolation boundaries and the newly reproduced
Go2 go_home post-arrival missing-mapping defect. No hardware behavior was changed.


Approved go_home arrival-hold correction verified (Action 420 passed / 29 skipped).
Tree voice execution and tree Energy feedback tests now extend the navigation gate;
production arbitration and real battery/charging confirmation remain unverified.
The previous go_home defect is closed; two recharge branches expose a missing task
adapter and an unmeasured default energyValue=100 respectively. See the follow-up
in P5_NAVIGATION_RECOVERY.md; these block claiming a complete robot release.

Final supplemental gate: 31 tests + 2 subtests passed; public Action probe passed.
Review snapshot hashes: validation/navigation-recovery/review-snapshot.json.

Energy truth audit: see ENERGY_SETTLEMENT_DECISION.md and the saved isolated
characterization. Missing/invalid energy and charging_completed=false can all
settle demand to zero today. Coordinated settlement policy approval is pending;
no production fallback was changed in this audit.


Energy settlement policy is now approved and implemented across Action, BT and
Needs. Action no longer fabricates a battery measurement; BT forwards metadata;
Needs requires interfaces/application/BATTERY_OBSERVATION.md evidence, including
on charge interruption and direct Recharge(). Old scalar-only results preserve
Energy. No live battery producer has been wired; real charging/docking remains
unimplemented. The prior energy-audit pending status above is historical.

Energy-policy validation: 22 independent-process contract cases; 31 ROS/navigation
cases + 2 subtests; real installed Needs ROS measured/duplicate/legacy rejection;
three clean wheels passed offline. Updated result-contract CI selects the new
fixtures; original cases.json and all source repositories remain preserved.
