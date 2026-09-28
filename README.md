# MarsDog Platform

Incremental migration in progress. Emotion/Needs, BehaviorTree and Action have been imported here.
Vision, Voice and Robotics remain in their original repositories.
This repository is not yet a complete robot release.

## Current module

- modules/emotion: existing marsdog_core, marsdog_ros2, and ROS package
  marsdog_need_emotion. Algorithms, ROS interfaces and default behavior are preserved.
- docs/migration/history: original commit/ref provenance and old-to-new commit map.
- modules/behavior: existing marsdog_behavior and bionic_dog_bt, including the
  marsdog_behavior ROS package. Decision and cancellation semantics are preserved.

The first import preserved 19 reachable commits through a prefix-only transformation
of a disposable clone. The original repository and a verified all-ref bundle remain
untouched. Imported SHAs differ; see the commit map.
The BehaviorTree import additionally preserved 7 commits and verified all 90 files.
The Action import preserved 5 commits and verified all 131 files, including media.

## Local Python verification

Use Python 3.10 and uv. Module environments are independent; there is no root uv workspace.

~~~bash
uv sync --project modules/emotion --locked --python /usr/bin/python3.10
(cd modules/emotion && uv run --locked python -B -m pytest tests -q -p no:cacheprovider)
python3 tools/check_emotion_install.py --uv uv
~~~

ROS build verification uses the separate Humble build-tool project under
platform/humble-build-tools. Do not replace the system ROS Python or install all
modules into one environment. Read docs/migration/P2_EMOTION.md for the validated
scope and remaining platform gates.

On an Ubuntu 22.04 / ROS Humble host, from this repository:

~~~bash
python3 -B tools/check_emotion_ros.py --uv uv
~~~

This builds an isolated install and launches only the real Needs node with every
business topic remapped into a random test prefix on a localhost test domain.
It does not launch tactile hardware or a robot bringup. Results are under out/.

The Emotion GitHub workflow runs the pure regressions and clean-wheel probe. It is
committed for a future remote; no hosted CI run has happened yet. ROS and hardware
acceptance are separate from that job. The checkout action is pinned to the verified
[official v4.4.0 release](https://github.com/actions/checkout/releases/tag/v4.4.0).

## BehaviorTree verification

~~~bash
uv sync --project modules/behavior --locked --python /usr/bin/python3.10
(cd modules/behavior && uv run --locked python -B -m pytest tests marsdog_behavior/tests -q -p no:cacheprovider)
python3 -B tools/check_behavior_install.py --uv uv
~~~

See docs/migration/P3_BEHAVIOR.md for the old/new installed ROS adapter comparison.
That test uses real DDS and historical generated IDL with a fake Action server;
it does not prove hardware execution or navigation availability.

## Migration tooling and retained evidence

integration/migration contains the versioned baseline, tools and compatibility
fixtures. Historical sources, raw logs, bundles and large build trees remain in the
original aggregate workspace. Set MARSDOG_MIGRATION_WORKSPACE to its migration
directory to rerun versioned tools using those artifacts; set MARSDOG_LEGACY_ROOT
if the original repositories move to a different aggregate directory.

No root Python workspace combines module environments. No production launch has
been switched. This repository currently has no remote and no hosted CI history.

## Action verification

~~~bash
uv sync --project modules/action --locked --no-editable --python /usr/bin/python3.10
(cd modules/action && .venv/bin/python -B -m pytest tests -q -p no:cacheprovider)
python3 -B tools/check_action_install.py --uv uv
~~~

Action retains its NumPy 2.2.6 lock in a separate environment. `--no-editable` verifies
wheel installation without adding an editable-build dependency. ROS callbacks were
also checked with this module runtime; the Humble build toolchain remains separate.
Read docs/migration/P3_ACTION.md before running ROS tests. Do not launch robot defaults
on a development host or mistake fake-server transport checks for hardware acceptance.
