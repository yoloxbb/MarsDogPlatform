# P2: Emotion/Needs migration

Status: import completed; packaging correction and validation in progress.

The original source is MarsDogEmotion at cd1e0476df7ab20873d048a8508e67301e7231c1.
The mechanical import is a4ded4ad6c36d76a1dab6648aa1cbeb6c756b3a4.
At import, all 102 tracked paths matched the source bytes and file modes.
Original refs, 19 reachable commits, bundle SHA256 and restore verification are in
history/emotion-import.json. History transformation occurred only in a disposable clone.

P1 demonstrated 346 Emotion tests passing and its ROS package building with the
Ubuntu 22.04/Humble setuptools 59.6 toolchain. Modern wheel packaging lost console
scripts, and default pure-Python config lookup failed after installation. These
are the narrowly scoped packaging fixes in this slice, not changes to demand logic.

Global gates still open: full Action ROS build lacks nav2_msgs and external chassis
interfaces; Behavior/Action Python packaging needs separate fixes; models, production
profiles, waypoint service and hardware acceptance remain outside this slice.

The gate was refined from an all-modules barrier to a per-module barrier: independently
verified Emotion can migrate while unrelated Action deployment prerequisites remain
explicitly blocked. No production deployment or behavior change is authorized by a
passing software test alone.
