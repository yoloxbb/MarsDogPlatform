# P2: Emotion/Needs migration

Status: software migration verified on 2026-09-28. Not a full robot release.

The original source is MarsDogEmotion at cd1e0476df7ab20873d048a8508e67301e7231c1.
The mechanical import is a4ded4ad6c36d76a1dab6648aa1cbeb6c756b3a4.
At import, all 102 tracked paths matched the source bytes and file modes.
Original refs, 19 reachable commits, bundle SHA256 and restore verification are in
history/emotion-import.json. History transformation occurred only in a disposable clone.

P1 demonstrated 346 Emotion tests passing and its ROS package building with the
Ubuntu 22.04/Humble setuptools 59.6 toolchain. Modern wheel packaging lost console
scripts, and default pure-Python config lookup failed after installation. These
are the narrowly scoped packaging fixes in this slice, not changes to demand logic.

At this checkpoint, Action lacked nav2_msgs and Behavior/Action packaging needed
separate fixes. Subsequent P3 records document those software fixes and the full
Action build. External chassis interfaces, models, production profiles, waypoint
service and hardware acceptance remain outside this slice; see STATUS.md.

The gate was refined from an all-modules barrier to a per-module barrier: independently
verified Emotion can migrate while unrelated Action deployment prerequisites remain
explicitly blocked. No production deployment or behavior change is authorized by a
passing software test alone.

## Validated changes and results

Only pyproject build metadata/scripts/dev lock and config_loader's ordinary-wheel
prefix fallback changed. Source and ROS share precedence remain unchanged. Config
bytes, package/endpoint identities and demand calculations are preserved.

- Existing 346 JUnit cases plus 4 new lookup cases: 350 passing, no skips.
- Old Action/BT to migrated Needs: 17 contract/baseline checks passing.
- Clean wheel outside source cwd: six original scripts, all original config hashes,
  core construction without ROS or optional PyYAML.
- Real Humble colcon build: passing; all six original ROS executable names present.
- Baseline and migrated installed InternalNeedNode: real remapped ROS pub/sub both
  settle energyValue=88 to Energy need=12 and ignore duplicate event IDs.
- All seven original repositories still match captured hashes, modes, index and HEAD.

Evidence is retained under docs/migration/validation/p2-emotion; larger P1 logs and
the immutable baseline live in the sibling migration verification workspace.
The first ROS probe used incomplete synthetic fields and failed on both versions;
the fixture was corrected to the actual BT contract. No production logic changed.

Python wheels use an isolated setuptools 79.0.1 backend. ROS colcon uses the
separately locked platform/humble-build-tools environment with setuptools 59.6.0,
matching this Ubuntu 22.04/Humble installation. Neither replaces system ROS Python.

The source repositories remain available for rollback. No robot has been switched
to this checkout; no original files, launch profiles or Git histories were removed.
