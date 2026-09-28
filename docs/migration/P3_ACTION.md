# P3b: Action migration

Status: prepared; import and validation in progress.

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
