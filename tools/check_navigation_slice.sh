#!/usr/bin/env bash
# Local isolated acceptance; requires the retained Humble/Voice/Nav2 fixtures.
set -eo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${MARSDOG_MIGRATION_WORKSPACE:-$(dirname "$ROOT")/migration}
source /opt/ros/humble/setup.bash
source "$WORK/work/p1-20260928/ros-voice/install/local_setup.bash"
source "$WORK/work/p1-20260928/ros-p3-behavior/install/local_setup.bash"
source "$WORK/work/navigation-recovery/install/local_setup.bash"
NAV="$WORK/work/nav2-msgs-1.1.20/extracted/opt/ros/humble"
export PYTHONPATH="$ROOT/modules/behavior:$ROOT/modules/action:$NAV/local/lib/python3.10/dist-packages:$PYTHONPATH"
export LD_LIBRARY_PATH="$NAV/lib:$LD_LIBRARY_PATH"
export AMENT_PREFIX_PATH="$NAV:$AMENT_PREFIX_PATH"
export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export ROS_DOMAIN_ID=89 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE="$ROOT/integration/migration/fixtures/fastdds-local-udp.xml"
export ROOT WORK
cd "$ROOT"
mkdir -p "$ROOT/validation/navigation-recovery"
"$ROOT/modules/action/.venv/bin/python" -B -m pytest   robotics/ros2/src/waypoint_nav/tests   integration/ros/tests   -q -p no:cacheprovider --junitxml="$ROOT/validation/navigation-recovery/navigation.xml"
"$WORK/.venv/bin/python" -B - <<'PY'
import os, subprocess, signal, uuid
from pathlib import Path
root, work = Path(os.environ['ROOT']), Path(os.environ['WORK'])
from marsdog_action_executor import ros2_compat
assert ros2_compat.get_action_source() == 'marsdog_interfaces'
from marsdog_interfaces.action import ExecuteBehavior
assert ExecuteBehavior.Goal.get_fields_and_field_types()['params_json'] == 'string'
tools = root / 'integration/migration/tools'
python = str(work / '.venv/bin/python')
endpoint = '/navigation_slice_' + uuid.uuid4().hex + '/execute_behavior'
with (work / 'work/navigation-recovery/public-server.log').open('w') as log:
    server = subprocess.Popen([python, '-B', str(tools/'ros_action_probe.py'),
        'server', '--endpoint', endpoint, '--interface-package', 'marsdog_interfaces'],
        stdout=log, stderr=subprocess.STDOUT)
    try:
        # The probe below intentionally checks the retained installed BT adapter;
        # connected tests above use the modified source tree, including its mapper.
        installed_env = dict(os.environ)
        installed_env["PYTHONPATH"] = ":".join(x for x in installed_env["PYTHONPATH"].split(":") if x != str(root / "modules/behavior"))
        subprocess.run([python, '-B', str(tools/'ros_behavior_probe.py'),
            '--install', str(work/'work/p1-20260928/ros-p3-behavior/install'),
            '--endpoint', endpoint, '--interface-package', 'marsdog_interfaces',
            '--output', str(root/'validation/navigation-recovery/public-interface.json')],
            env=installed_env, check=True, timeout=45)
    finally:
        if server.poll() is None:
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
PY
