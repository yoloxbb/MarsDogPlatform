# MarsDog Platform

Incremental migration in progress. Only Emotion/Needs has been imported here.
Vision, Voice, BehaviorTree, Action and Robotics remain in their original repositories.
This repository is not yet a complete robot release.

## Current module

- modules/emotion: existing marsdog_core, marsdog_ros2, and ROS package
  marsdog_need_emotion. Algorithms, ROS interfaces and default behavior are preserved.
- docs/migration/history: original commit/ref provenance and old-to-new commit map.

The first import preserved 19 reachable commits through a prefix-only transformation
of a disposable clone. The original repository and a verified all-ref bundle remain
untouched. Imported SHAs differ; see the commit map.

## Local Python verification

Use Python 3.10 and uv. Module environments are independent; there is no root uv workspace.

~~~bash
uv sync --project modules/emotion --locked --python /usr/bin/python3.10
uv run --project modules/emotion --locked python -B -m pytest modules/emotion/tests -q -p no:cacheprovider
python3 tools/check_emotion_install.py --uv uv
~~~

ROS build verification uses the separate Humble build-tool project under
platform/humble-build-tools. Do not replace the system ROS Python or install all
modules into one environment. Read docs/migration/P2_EMOTION.md for the validated
scope and remaining platform gates.
