# Versioned migration verification

This directory owns the reusable tools, immutable source baseline and test fixtures.
It is not a business package and is not part of a root Python workspace.
Old copies in the sibling migration directory are retained historical working material;
make further tool changes here, not in both places.

Run from the new repository root on the original verification host:

```bash
export MARSDOG_MIGRATION_WORKSPACE=/home/elephant/MarsDog/migration
export MARSDOG_LEGACY_ROOT=/home/elephant/MarsDog
python3 -B integration/migration/tools/check_baseline.py
MARSDOG_BEHAVIOR_SOURCE="$PWD/modules/behavior" MARSDOG_EMOTION_SOURCE="$PWD/modules/emotion" \
  "$MARSDOG_MIGRATION_WORKSPACE/.venv/bin/python" -B -m pytest integration/migration/tests -q -p no:cacheprovider
"$MARSDOG_MIGRATION_WORKSPACE/.venv/bin/python" -B integration/migration/tools/check_p3_behavior.py
```

The external workspace contains verified snapshots, independent environments, build
prefixes, reports and Git bundles. It can be relocated by the two variables above.
Without those artifacts, original-repository comparisons are BLOCKED, not passed.
The P2/P3 historical smoke scripts currently target the recorded p1-20260928 run;
they are migration evidence runners, not production launchers. Module-only pure
checks and clean-wheel probes in the main README do not require original repos.

The baseline must not be recaptured to make drift pass. `capture_baseline.py` refuses
an existing baseline. History import only filters a disposable verified copy, never
an original repo. bundles, .venv, work and caches must not enter commits.

ROS tests use real generated types and localhost test domains; fake Action servers
never validate chassis motion. A cancel ACK is not a terminal result or proof of stop.
