# P3b: Action migration

Status: software migration verified on 2026-09-28 under the recorded test environments.
Production/default-transport/hardware acceptance remains open.

The original source is 20260707_MarsDogAction at
f00c3fdf2945c7a09d5f49ffc3d0df39c37ca2a8.
P1 recorded 414 passing pure-Python tests and 29 skips. A subsequent unmodified full
ROS package build passed using the recorded official nav2_msgs 1.1.20 artifact,
unmodified Voice/Vision installs, and the separate Humble toolchain. The Nav2 deb
was checksum-verified and extracted locally; no system package was installed.

Scope: retain ROS package/type/endpoint/config identity, execution and cancellation
semantics, existing hardware adapters and Python dependency versions. Correct only
ordinary wheel packaging and installed config/resource discovery, then verify the
same tests, generated IDL, real ROS callbacks and result-chain compatibility.

Do not launch the production ActionExecutorNode with its original defaults on this
host: chassis interfaces and production navigation are not available or validated.
Use existing callback unit fixtures and isolated ROS transport without hardware.
Do not create replacement unitree/transfer/marsdog_interfaces packages. Deployment
profiles, true waypoint server, stop and battery semantics remain external gates.

## Implemented slice

All 5 reachable historical commits and refs were restored from a verified bundle.
The prefix-only import matched 131 source files, including Chinese media filenames.
Only the disposable copy was filtered. Full provenance and commit map are in history/.

The wheel now includes config (YAML, images and sound), launch, historical action IDL
and package.xml using Hatch's
[shared-data mapping](https://hatch.pypa.io/latest/plugins/builder/wheel/).
Existing ROS script functions are exposed as Python console entries alongside the
demo. Config and media lookup adds an installation-prefix fallback after existing
paths; explicit missing paths still fail rather than silently selecting defaults.
The demo uses its original source path when present, then the installed location.

CMakeLists.txt, package.xml, action definitions, launch files, default configs/media,
algorithms, hardware adapters, ROS QoS and protocol selection are unchanged.
The original uv.lock and runtime dependencies are unchanged, including NumPy 2.2.6
and the historical pytest runtime dependency; cleanup is a later separate slice.

## Validation

- 418 pure-Python tests pass, 29 skip (original 414 + four new path regressions).
- 39 selected actual installed ROS callback tests pass for each old/new build,
  with Action's NumPy 2.2.6 environment. These exercise the original fake collaborators
  without constructing the production hardware node. The 20 ROS-dependent cases
  skipped in the pure run are covered here; nine Qt cases remain unexecuted.
- Both full ROS packages build, and native Nav2 type support imports successfully.
- Clean wheel install away from source finds all 34 config/media files with exact
  hashes, 74 behavior templates, every display-category image and all three entries.
- All-new Action → BT → Needs passes the 17 independent-process contract/drift checks.
- Three additional module guards verify original ROS manifests, IDL, launch, scripts,
  default configs and media bytes/modes. Final integration count: 20 passing.
- Four old/new BT adapter and full-build Action IDL combinations pass with the
  loopback UDP test profile: feedback, metadata, success, cancel ACK distinct from
  terminal result, and ownership retained until terminal. The server is a fixture,
  not the production Action executor. Old/new actual executor callbacks are checked
  separately by the 39-case suite above.
- Default Fast DDS transport on this host intermittently discovers the action server
  but fails to deliver SendGoal; this also reproduces with baseline code. Serializing
  builds and changing the test domain did not resolve it. Exact root cause UNKNOWN.
  A test-only loopback UDP profile restores communication; production transport is
  untouched. See the matrix report for its explicit transport scope.

The UDP fixture follows the
[Fast DDS transport configuration](https://fast-dds.docs.eprosima.com/en/2.6.x/fastdds/transport/udp/udp.html).
This is an environment diagnostic and controlled compatibility test, not a production
transport change or closure of the default-transport issue. Runtime/hardware gates
remain open even when all controlled software checks pass.

## Reproduction

Run after the P1 source snapshots and Voice/Vision ROS installs exist; never rebuild
an install prefix while another test is using it:

```bash
export MARSDOG_MIGRATION_WORKSPACE=/home/elephant/MarsDog/migration
python3 -B integration/migration/tools/prepare_nav2_fixture.py
"$MARSDOG_MIGRATION_WORKSPACE/.venv/bin/python" -B integration/migration/tools/check_p3_action.py
"$MARSDOG_MIGRATION_WORKSPACE/.venv/bin/python" -B integration/migration/tools/check_action_interop.py --udp-only
```

The pinned deb is only a local build/test interface artifact, not a production Nav2
release selection. Actual chassis interface suppliers and production profiles remain
unresolved; no replacement protocols or hardware implementations were created.
