# RTAB-Map preservation boundary

The complete local RTAB-Map repository is pinned as one external unit. Its 4 commits,
refs, core sources, ROS wrappers and local additions are preserved in a verified bundle.
No upstream checkout replaces that fork, and no third-party algorithm is presented as MarsDog-owned.

UPSTREAM_VERSIONS.md records short upstream revisions only. The initial snapshot may
already contain edits; a full upstream comparison remains UNKNOWN. In particular, the
rtabmap_openvins_mono wrapper is retained in this external unit until its provenance is settled.

Files changed since the local initial commit (this is NOT the full upstream patch set):

- src/rtabmap/corelib/include/rtabmap/core/Odometry.h
- src/rtabmap/corelib/include/rtabmap/core/Parameters.h
- src/rtabmap/corelib/include/rtabmap/core/impl/LocalMapMaker.hpp
- src/rtabmap/corelib/include/rtabmap/core/odometry/OdometryOpenVINS.h
- src/rtabmap/corelib/src/odometry/OdometryOpenVINS.cpp
- src/rtabmap_ros/rtabmap_odom/include/rtabmap_odom/OdometryROS.h
- src/rtabmap_ros/rtabmap_odom/src/OdometryROS.cpp
- src/rtabmap_ros/rtabmap_slam/CMakeLists.txt

Materialize with tools/materialize_vendors.py; build separately when actual mapping
is selected. The local Lite3 smoke uses explicit Nav2 simulation and does not claim
RTAB-Map mapping, loop closure, localization, or obstacle avoidance on sensor data.
