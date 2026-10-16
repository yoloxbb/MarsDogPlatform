# Fast DDS 2.6.12 fragmented-reader fix

## Failure addressed

Fast DDS 2.6.12 can retain an incomplete fragmented sample on a matched-writer
record when that writer is removed. The sample has not entered `ReaderHistory`,
so repeated writer removals can consume the reader's `CacheChangePool`. Large
camera frames may then stop reaching an already-running subscription while a
new subscriber still receives frames.

The local patch releases that incomplete sample before deleting the writer
record. It does not change the ROS interfaces, image QoS, camera behavior, or
the platform's default Cyclone DDS profile.

## Build once on this checkout

From the main repository's `modules/vision` directory on ROS 2 Humble:

```bash
source /opt/ros/humble/setup.bash
./scripts/build_fastdds.sh
```

The builder pins Fast DDS 2.6.12 and Asio 1.18.1, verifies both source archive
SHA-256 digests, applies the patch in a local build copy, and installs to
`~/.local/opt/marsdog-fastdds-2.6.12`. It does not write into `/opt/ros/humble`.
Use `MARSDOG_FASTDDS_PREFIX` to select another isolated install prefix and
`MARSDOG_FASTDDS_BUILD_JOBS` to change the default parallelism of two jobs.

Rebuild the overlay only when its source patch or builder changes. A normal
Vision package rebuild is separate:

```bash
colcon build --base-paths . --packages-select marsdog_vision_interaction
```

## Load it when starting ROS participants

In each terminal that starts a standalone camera or another external Fast DDS
participant, source the environment script from this checkout:

```bash
source scripts/fastdds_env.sh
```

`vision.launch.py` and `vision_debug.launch.py` set the same overlay for their
child nodes automatically. The script and launch files leave the system ROS
installation untouched. If the overlay is absent, they preserve the existing
system-library behavior; build it before running the camera image pipeline.
Set `MARSDOG_FASTDDS_DISABLE_OVERLAY=1` to explicitly remove the overlay from a
terminal environment.

To confirm which library a running ROS node loaded, inspect its process map:

```bash
grep 'libfastrtps.so.2.6' /proc/<pid>/maps
```

The path should point to the selected overlay prefix. This check establishes
the loaded library only; it does not claim camera, model, or hardware
acceptance.

## Prior evidence

This exact patch and overlay implementation were previously validated in the
retained Vision source checkout: the unpatched runtime exhausted its cache on
the second controlled writer removal; the patched native regression completed
100 removals; and the camera/viewer run remained fresh for a two-minute sample.
The results are summarized in the source checkout's
`test-evidence/20261016-camera-stale/verification.md`. The main-repo port has
since been built, and a mock Vision launch confirmed that it loaded the overlay
library. The 100-removal native regression has not been rerun against this
main-repo copy; camera, model, and hardware acceptance remain unverified.
