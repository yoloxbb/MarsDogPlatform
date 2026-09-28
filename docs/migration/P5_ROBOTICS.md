# Native Robotics migration gate

2026-09-29. User target: Lite3, local CPU development.

All-ref robot and RTAB-Map bundles are verified and originals unchanged. External
snapshots are pinned under third_party; their existing patches are retained.
The selective import includes eight own ROS packages. Third-party code is
materialized into ignored .external, never renamed as first-party code.

The original robot HEAD has two C++ syntax errors in uwb_behavior_controller_node.cpp.
The candidate fixes only an orphan std::bind fragment and a missing vector closing
delimiter; see candidate-syntax-repair.diff. No control algorithm changed.
Eight CPU packages build (seven own packages plus the existing UWB stub build).
behavior_ext_plugins needs full Nav2 libraries and is retained but not CPU-built.

The original functional tests pass: 140 JUnit cases, zero failure/error/skip;
13 CTest entries pass, including serial reconnect (CTest-only). Counts overlap:
do not add the CTest wrappers to the JUnit cases.

Local WSL transport diagnosis: Fast DDS failed the serial transport gate.
Cyclone DDS with unrestricted packet sizes still lost planner diagnostics.
Writer traces showed 1648-byte UDP payloads sent but absent at the reader.
With MaxMessageSize=1200B and FragmentSize=1000B, a standalone 20 Hz diagnostic
probe received 52 messages in four seconds, and the unchanged full native test
suite passed. This establishes an effective local transport configuration;
the exact host network filter causing the loss is UNKNOWN.
No global ROS default, firewall setting, planner frequency or assertion changed.

The local profile uses fixed, checksum-verified Cyclone packages extracted into
out/ros-deps; it does not replace system ROS. Configuration reference:
https://cyclonedds.io/docs/cyclonedds/0.10.2/config/config_file_reference.html

No camera, IMU, UWB hardware, Lite3 motion, mapping quality, production Nav2 or
RTAB-Map runtime acceptance is claimed. Local launch scaffolding is pending the
separate integrated build and smoke gate.

Selective import completed at 243f071675540cb5298920fff3e1528c03f41a98:
30 relevant commits and 122 exact files/modes; complete 31 commits remain archived.
The imported tree received only the recorded C++ syntax fix, and its own build /
functional gate also passed (migrated.json). All original planner tests are unchanged.
Sixteen workspace-level documentation/scripts/editor files are inventoried in
history/robot-retained-workspace-assets.json and remain preserved in their archive.
The accepted local integration and remaining deployment limits are now in STATUS.md.
