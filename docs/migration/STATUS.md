# Migration status — 2026-09-28

| Phase | Status | Evidence / remaining gate |
| --- | --- | --- |
| P0 | Approved proposal | Frozen copy in docs/architecture/ARCHITECTURE_AND_MIGRATION_PROPOSAL.md |
| P1 | Baseline / software contract slice complete | 7 source snapshots, 3,074 files, 38 ROS manifests, 48 IDLs; existing tests and known gaps retained |
| P2 | Emotion software migration verified | 19 commits preserved; 350 cases; wheel/ROS installed-state equivalence |
| P3a | BehaviorTree software migration verified | 7 commits preserved; 532 cases; wheel/ROS adapter checks |
| P3b | Action software migration verified with stated transport limits | 5 commits preserved; 418 pure passes / 29 skips; old/new 39 ROS callback cases each; four UDP DDS combinations pass |
| P4 | Environment gate blocked; not migrated | Uncached locked Torch / sherpa-onnx-core; PyPI and checked mirrors time out at TLS handshake; no full regression/model acceptance |
| P5 | Not migrated | robot_ws / rtabmap_ws unchanged; vendor provenance and native replay gates pending |
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

Production launch/profile, external marsdog_interfaces/waypoint server, real owner
accounts and hardware acceptance require real deployment facts. These gates do not
justify weakening independent software regression or changing robot behavior.

Next runnable slice: restore access to the locked artifacts (or supply a verified
offline cache), run original Vision/Voice tests in their separate environments,
then migrate one module at a time. Do not downgrade pins, omit declared dependencies
and call it a full-environment pass, or move implementations before their baseline.
Native Robotics/vendor replay and production hardware gates are still pending.
