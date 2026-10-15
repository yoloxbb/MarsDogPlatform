#!/usr/bin/env bash
set -eo pipefail
MARSDOG_ROOT="${MARSDOG_ROOT:-/home/marsdog/MarsDogPlatform}"
ROUNDTRIP_OUT="$MARSDOG_ROOT/out/rk3588-uwb-roundtrip"
source "$ROUNDTRIP_OUT/use-uwb-roundtrip.sh"
set -u
export ROS_LOCALHOST_ONLY=1
# rmw_cyclonedds selects loopback here; selecting lo again in XML causes a duplicate-interface error.
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><Peers><Peer address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
TEST_ROOT="$MARSDOG_ROOT/robotics/ros2/src/robot_local_motion/test"
python3 -m pytest "$TEST_ROOT/test_core.py" "$TEST_ROOT/test_guard.py" "$TEST_ROOT/test_roundtrip_core.py" "$TEST_ROOT/test_uwb_follow_backend.py" \
    "$TEST_ROOT/test_uwb_protocol.py" "$TEST_ROOT/test_uwb_tracking.py" "$TEST_ROOT/test_uwb_stability.py" "$TEST_ROOT/test_target_geometry.py" \
    -q --junitxml="$ROUNDTRIP_OUT/pure-tests.xml"
ROS_DOMAIN_ID=225 python3 -m pytest "$TEST_ROOT/test_uwb_transport.py" -q --junitxml="$ROUNDTRIP_OUT/uwb-transport.xml"
ROS_DOMAIN_ID=220 python3 -m pytest "$TEST_ROOT/test_task_transport.py" -q --junitxml="$ROUNDTRIP_OUT/task-transport.xml"
ROS_DOMAIN_ID=226 python3 -m pytest "$TEST_ROOT/test_native_roundtrip_transport.py" -q --junitxml="$ROUNDTRIP_OUT/native-roundtrip-transport.xml"
ROS_DOMAIN_ID=224 python3 -m pytest "$TEST_ROOT/test_follow_input_transport.py" -q --junitxml="$ROUNDTRIP_OUT/follow-input-transport.xml"
