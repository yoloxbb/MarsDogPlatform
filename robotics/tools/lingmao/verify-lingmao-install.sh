#!/usr/bin/env bash
# Offline installation and mock ROS transport checks; never use the robot domain.
set -eo pipefail
root=${MARSDOG_ROOT:-/home/marsdog/MarsDogPlatform}
profile=${LINGMAO_PROFILE:-legacy}
case $profile in
  legacy) base=$root/out/rk3588-lingmao-communication-legacy ;;
  modern) base=$root/out/rk3588-lingmao-communication ;;
  *) echo 'LINGMAO_PROFILE must be legacy or modern' >&2; exit 2 ;;
esac
source "$base/native-env.sh"
source "$base/install/local_setup.bash"
export ROS_DOMAIN_ID=238 ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export CYCLONEDDS_URI='<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General></Domain></CycloneDDS>'
mkdir -p "$base/verification"
ros2 pkg prefix uniubi
ros2 pkg prefix uniubi_motion_client
ros2 pkg prefix uniubi_motion_bridge
ros2 launch uniubi_motion_bridge motion_bridge.launch.py --show-args \
  > "$base/verification/launch-arguments.log"
for package in uniubi_motion_client uniubi_motion_bridge; do
  ctest --test-dir "$base/build/$package" --output-on-failure \
    | tee "$base/verification/$package-ctest.log"
done
python3 -B - "$base" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
base=Path(sys.argv[1])
files=[base/'install/uniubi_motion_bridge/lib/uniubi_motion_bridge/uniubi_motion_bridge_node',
       base/'install/uniubi_motion_client/lib/uniubi_motion_client/sensor_observed_subscriber']
for path in files:
    result=subprocess.run(['ldd', str(path)], capture_output=True, text=True, timeout=20)
    missing=[s.strip() for s in result.stdout.splitlines() if 'not found' in s]
    assert result.returncode == 0 and not missing, (str(path), missing)
    print('DYNAMIC_DEPENDENCIES_PASS', path.name)
status=json.loads((base/'build-status.json').read_text())
print(json.dumps({k: status[k] for k in ['status','compile_jobs','elapsed_seconds','minimum_available_bytes',
      'maximum_swap_used_bytes','oom_kill_at_start','oom_kill_at_finish']},indent=2))
PY
