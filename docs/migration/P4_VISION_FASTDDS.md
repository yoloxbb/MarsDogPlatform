# P4 Vision Fast DDS cache fix port

## Source and provenance

The patch, pinned builder, and library-selection helper were copied from the
retained working checkout
`/home/marsdog/marsdog_ws/src/MarsDogVisionInteraction`, based on source `HEAD`
`9c4f134`. That checkout was dirty when inspected; the copied files were
uncommitted there. The original checkout was not modified by this port.

At copy time, the copied files matched these source SHA-256 digests:

| Main-repo file | SHA-256 |
| --- | --- |
| `modules/vision/patches/fastdds/0001-release-partial-change-on-writer-removal.patch` | `90eb294e657118ea9e91b39bfb61e3561a9fe24a8960abd4a69e24faea1349d5` |
| `modules/vision/scripts/build_fastdds.sh` | `b80a17c0f25816850bc5a7d4eb105666bb593b68e50c43ac2671f808047ddd03` |
| `modules/vision/marsdog_vision_interaction/fastdds_overlay.py` | `66890d36c91ba00971ee9b6bcc3a99fd5bf9179349932b99ec7d602d2f16261b` |

The builder's final status message was then adapted to avoid referring to a
native test script that is not part of this port. The existing main-repo Fast
DDS shell script and launch files were adapted to load the copied files.
Runtime use no longer depends on the retained source checkout. The pinned Fast
DDS and Asio archives are still verified by the builder before use.

## Scope

The fix is limited to the Fast DDS 2.6.12 reader's incomplete-fragment cache
cleanup and the standalone Vision Fast DDS startup path. ROS package/type/topic
names, image QoS, Python dependency locks, and platform `marsdog.py up` default
Cyclone DDS configuration are unchanged.

Historical validation is documented in
[`modules/vision/docs/FAST_DDS_PATCHED_RUNTIME.md`](../../modules/vision/docs/FAST_DDS_PATCHED_RUNTIME.md).
The prior source-checkout report remains in its original location and is not
presented as validation of this main-repo port.
