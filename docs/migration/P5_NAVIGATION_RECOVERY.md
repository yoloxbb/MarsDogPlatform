# P5 supplemental navigation/interface slice - 2026-09-28

## Scope and provenance

The user supplied two source directories without Git metadata. Their independent
history and upstream authorship remain UNKNOWN. We copied their source files,
excluding .pytest_cache and __pycache__, rather than moving originals:

| Original | Platform destination |
| --- | --- |
| marsdog_interfaces/marsdog_interfaces | interfaces/ros2/marsdog_interfaces |
| slam/waypoint_nav | robotics/ros2/src/waypoint_nav |

new_navigation_baseline.json records every original file hash. No original Git
history was fabricated. Seven existing source repositories passed their previous
baseline check; both newly supplied directories also match captured hashes.
robot_ws and rtabmap_ws have not been migrated by this slice.

## Approved behavior correction

The user approved separating automatic cancel from explicit operator recovery
release. Previously any cancel during RECOVERY_REQUIRED immediately released the
lock, despite the Action client sending that same operation automatically.

The copied dispatcher now keeps the recovery lock on ordinary cancel and waits
for a Nav2 terminal result. release_recovery is a distinct task_type requiring
operator_confirmed_stopped=true (strict JSON boolean), plus existing task ownership,
active-task and recovery-state checks. It emits INTERRUPTED/RECOVERY_RELEASED.
The Action parser recognizes that explicit interruption; it is not navigation
success or evidence that Nav2 confirmed a stop. Automated Action code never emits
release_recovery. Persistence precedes terminal publication and lock release.

This is operator attestation over the existing VoiceTask endpoint, not new
operator authentication or a physical-stop detector. The operator must observe
that the robot is stopped before issuing it. Production access control remains
a deployment concern. Old Action parsers reject this terminal code, so deploy
the updated Action and server together. No production deployment was performed.

## Interface boundaries

waypoint_nav remains an ament_python package: VoiceTask service, String JSON
status, OccupancyGrid map input, NavigateToPose client, SQLite/WAL persistence.
The dependency on marsdog_voice_interaction/srv/VoiceTask remains explicit;
extracting that type would change ROS type identity and is a separate migration.

The public ExecuteBehavior IDL has the same uncommented fields as the historical
Action-local IDL, but package-qualified ROS identities are different. Only a
coordinated BT/Action overlay should activate the public type. New typed behavior
messages are definitions, not replacements for the current BT-to-Needs String
JSON topic. This slice does not activate those typed topics.

## Validation

- Isolated colcon build: marsdog_interfaces and waypoint_nav both passed.
- Navigation suite and real Action-client wire test: 22 passed plus 2 subtests,
  zero skips, using fake Nav2 and temporary SQLite databases.
- Action full pure regression: 419 passed, 29 skipped (ROS/Qt cases). Skips are
  not counted as coverage; selected real ROS navigation tests run separately.
- Installed BT adapter with public ExecuteBehavior against fake Action server:
  success, feedback, metadata, cancel ACK ownership and delayed terminal passed.
- Action's real lazy type resolver selected marsdog_interfaces in the same overlay.
- Original repository baseline and supplemental source hashes passed.

ROS checks use localhost domain 89 and the existing loopback UDP test profile.
They do not resolve the previously observed default Fast DDS transport problem.
This is segmented integration, not one complete live BT/Action/Nav2 robot run.
Real hardware stop, deployed configuration, access control and board restart
acceptance remain unverified. No dependencies or ROS distributions were upgraded.

## Reproduce using retained fixtures

On the existing Linux Humble host, use the isolated build tool environment:

```bash
cd /home/elephant/MarsDog
source /opt/ros/humble/setup.bash
source migration/work/p1-20260928/ros-voice/install/local_setup.bash
export AMENT_PREFIX_PATH="$PWD/migration/work/nav2-msgs-1.1.20/extracted/opt/ros/humble:$AMENT_PREFIX_PATH"
export CMAKE_PREFIX_PATH="$PWD/migration/work/nav2-msgs-1.1.20/extracted/opt/ros/humble:$CMAKE_PREFIX_PATH"
migration/ros-tools/.venv/bin/colcon --log-base migration/work/navigation-recovery/log build --base-paths marsdog-platform/interfaces/ros2/marsdog_interfaces marsdog-platform/robotics/ros2/src/waypoint_nav --build-base migration/work/navigation-recovery/build --install-base migration/work/navigation-recovery/install --executor sequential --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
bash marsdog-platform/tools/check_navigation_slice.sh
```

The acceptance script requires the previous isolated Voice/BT installs and pinned
Nav2 interface fixture. It uses reserved test domain 89: do not run another test
or robot there concurrently. ROS tests live in integration/ros/tests so the existing
ROS-free contract CI does not accidentally start nodes. Reports are in
validation/navigation-recovery. No hosted CI run is claimed.

## Next gate

Before deployment, test a complete BT/Action/waypoint/Nav2 simulation with injected
restart, lost statuses and simultaneous cancellation, then perform supervised
hardware acceptance of the operator-release procedure. Keep robot_ws/rtabmap_ws,
Vision/Voice environment migration and vendor provenance as separate work slices.


## Follow-up: connected chain fault injection

The connected test is in integration/ros/tests/test_behavior_navigation_chain.py.
It uses the real BT ActionClientAdapter, real ActionExecutorNode, real
WaypointNavDispatcher and generated ROS types. A fake Nav2 server and an in-memory
SportMode publisher are the external test doubles. Temporary configuration disables
audio, UWB, wake orientation and attention/visual tracking. The random destination
pool is limited to fixture point A; original configuration files remain unchanged.

The ROS tests now run under Action's own locked .venv (including its NumPy version),
not the migration tool environment. Nodes communicate over real local DDS, but
share a process; this does not prove process crash isolation or full BT decision
logic. Dispatcher restart is orderly node destruction/reconstruction with the same
SQLite database, not power-loss simulation. Board restarts remain an open gate.

Six connected scenarios:

| Scenario | Observed/asserted outcome |
| --- | --- |
| walk_to_random_point complete behavior | Navigation and outer behavior succeed |
| go_home arrival, existing Go2 mapping | Navigation succeeds; outer behavior fails on unmapped ACT_NAV_GO_HOME |
| All waypoint status publications dropped | Action queries durable state; arrival preserved, same known go_home stage failure |
| Cancel with delayed Nav2 result | BT retains ownership after ACK; terminal follows actual Nav2 cancellation |
| Nav2 success races outer cancel | Nav2 SUCCEEDED remains intact; outer behavior cancels before remaining stage |
| Dispatcher rebuilt while moving | Recovers stored UUID, cancels that goal, no duplicate navigation; outer goal terminates without success |

Final combined acceptance: 28 tests and 2 subtests passed, no skips. Public
ExecuteBehavior probe also passed. The previous fixture destroyed nodes while the
executor could still hold their handles, causing intermittent InvalidHandle errors.
Dispatcher fixtures now use their own SingleThreadedExecutor and stop/join it before
node destruction; the fake Nav2 executor remains alive to represent ongoing motion.
This correction changes tests only, not production executor behavior.

### Open functional defect: Go2 go_home post-arrival mapping

behavior_tree_actions.yaml routes go_home to ACT_NAV_GO_HOME. navigation_waypoints.yaml
lists that unit as a post-arrival stage, and BehaviorMobilityAdapter.execute_step
passes it to Go2ChassisBackend.execute_step. go2_sport.yaml has no sequence for that
unit, so the backend fails closed after the robot has reached the destination.
The chain test explicitly preserves this failure as evidence; it is not acceptance
of go_home as a working behavior. No missing motion sequence was fabricated.

Deciding whether this stage should merely confirm arrival or execute a platform
motion must precede a production fix. The catalog describes arrival confirmation;
a likely minimal solution is to reuse the existing stationary completion path,
but this has not been applied or treated as an approved behavior change.

The whole BT scheduler, production process orchestration, power-loss durability,
hardware stopping and operator access control remain outside this software gate.


## Approved go_home correction and tree/Needs follow-up

The user approved completion by holding still after confirmed arrival.
BehaviorMobilityAdapter.execute_step now handles only the exact
(go_home, navigation, ACT_NAV_GO_HOME) combination through existing hold_position,
after route and allowed-unit validation. A failed hold remains failure. There is
no new platform motion sequence. The old open Go2 go_home defect above is resolved
by this follow-up; the earlier observations remain historical evidence.

The connected go_home and dropped-status cases now assert SUCCESS and only
SportMode stop requests (API 1003). Action full regression: 420 passed, 29 skipped.
The independent module result-contract suite: 20 passed using migrated module
source overrides and their separate environments.

Two additional tree entry paths use build_tree with the REAL ActionClientAdapter,
not MockActionExecutor. The existing MockInputProvider injects configured voice
and Energy events and selects the candidate. This covers tree execution and the
provider's selection, not the production ROS node's entire candidate arbitration.
The tree consumes the result itself (get_result is destructive), and its feedback
is passed through ResultEventMapper. Needs runs in its own locked Python process
through the real ApplyBehaviorResultMessage implementation; JSON stdin is TEST
transport, not a new production interface. A 30-second test behavior budget and
fixture route B->A are explicit temporary overrides; no default budget was changed.

- EVT_VOICE_COMMAND_GO_HOME selects go_home; tree completes SUCCESS; the mapper
  emits no Needs event, as required for this voice command.
- NEED_ENERGY_OVERFLOW selects recharge. After full configuration validation, the test instance restricts the existing
  random candidate list to each member separately; real eligibility/execution remain active.
- ACT_RETURN_TO_CHARGER fails because its task adapter lacks execute_task.
  The FAILED event and its replay both return false from the Needs adapter and leave Energy demand unchanged.
- ACT_BARK_AND_LIE_DOWN_IF_NO_CHARGER completes the existing proxy. Current Action
  reports energyValue=100; current Needs settles Energy demand to 0, exactly once.

### Unresolved recharge semantics: deployment blocker

These are observations, not a claim that the robot has charged. The proxy branch's
success and configured default energyValue=100 are not measured battery evidence.
No charging, docking or embedded implementation was invented. Before production
release, decide which actual external observation confirms charging completion and
whether proxy rest should settle Energy at all. Implementing a task handler or
changing energy settlement requires a separate behavior decision, beyond the
approved go_home correction. The integration gate must not conceal either branch.

## Review and rollback

No original directories, ROS type definitions, production launch defaults or model
runtimes were modified by the go_home correction. Current work is a local reviewable
working-tree slice, not a deployed or tagged robot release. Run
`bash tools/check_navigation_slice.sh` with the retained fixtures described above.
The installed waypoint package is the isolated migration install, not a production
workspace. Do not source it in production as an implicit interface migration.

If go_home needs rollback before deployment, remove the exact arrival-hold branch
in navigation_adapter.py together with its arrival regression expectations; this
restores the previously observed failure, not a working charging/navigation skill.
For deployed rollout/rollback, keep BT and Action on matching ExecuteBehavior type
packages and deploy the recovery-release server with its compatible Action parser.
Do not erase SQLite task state or unlock unresolved motion as a rollback shortcut.

Final follow-up acceptance: **31 tests and 2 subtests passed, zero skips**, plus
the public ExecuteBehavior success/cancellation probe. This supersedes the earlier
28-case count. No hardware deployment or release tag was created.


## Approved energy policy supersedes prior proxy settlement

The former proxy-success -> energyValue=100 -> Energy=0 behavior above is now
historical. Action/BT no longer synthesize that scalar; Needs requires a valid
battery_observation. Both recharge branches without observation leave Energy
unchanged, including after cancellation/timeout. The missing docking/task handler
is still not implemented. See ENERGY_SETTLEMENT_DECISION.md and
interfaces/application/BATTERY_OBSERVATION.md. The connected tests assert these
new semantics and load the modified BT source, not its old installed mapper.
