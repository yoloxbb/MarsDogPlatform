#!/usr/bin/env python3
"""Incremental round-trip overlay using the existing two-to-one memory monitor."""
import importlib.util
import os
from pathlib import Path

ROOT = Path(os.environ.get('MARSDOG_ROOT', '/home/marsdog/MarsDogPlatform')).resolve()
BASE = ROOT/'out/rk3588-uwb-roundtrip'
spec = importlib.util.spec_from_file_location('navigation_build_monitor', ROOT/'out/rk3588-slam-features/build-navigation-monitored.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.ROOT, runner.BASE, runner.STATUS = ROOT, BASE, BASE/'build-status.json'


def commands():
    return [('uwb-roundtrip', [str(ROOT/'platform/humble-build-tools/.venv/bin/colcon'),
        '--log-base', str(BASE/'build-log'), 'build', '--build-base', str(BASE/'build'),
        '--install-base', str(BASE/'install'), '--executor', 'sequential',
        '--event-handlers', 'console_direct+', '--base-paths', str(ROOT/'robotics/ros2/src/go2_uwb_local_follow'),
        str(ROOT/'robotics/ros2/src/go2_uwb_behavior'),
        str(ROOT/'robotics/ros2/src/robot_local_motion'),
        '--packages-select', 'go2_uwb_local_follow', 'go2_uwb_behavior', 'robot_local_motion', '--cmake-args', '-DBUILD_TESTING=ON',
        '-DPython3_EXECUTABLE=/usr/bin/python3', '-DPYTHON_EXECUTABLE=/usr/bin/python3'])]


if __name__ == '__main__':
    BASE.mkdir(parents=True, exist_ok=True)
    previous = ROOT/'out/rk3588-uwb-multitag/use-uwb-multitag.sh'
    if not previous.exists():
        raise RuntimeError('existing UWB/local-motion dependency overlay is required')
    (BASE/'native-env.sh').write_text(f'source "{previous}"\n')
    (BASE/'use-uwb-roundtrip.sh').write_text(
        '#!/usr/bin/env bash\n# Opt-in overlay; never launches hardware or motion.\n'
        f'source "{previous}"\nsource "{BASE / "install/local_setup.bash"}"\n')
    runner.commands = commands
    raise SystemExit(runner.main())
