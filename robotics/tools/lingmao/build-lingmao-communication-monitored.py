#!/usr/bin/env python3
"""Build the official UniUbi packages with the existing 2-to-1 job memory policy."""
import importlib.util
import os
from pathlib import Path

ROOT = Path(os.environ.get('MARSDOG_ROOT', '/home/marsdog/MarsDogPlatform')).expanduser().resolve()
PROFILE = os.environ.get('LINGMAO_PROFILE', 'legacy')
if PROFILE not in ('legacy', 'modern'):
    raise ValueError('LINGMAO_PROFILE must be legacy or modern')
BASE = ROOT / ('out/rk3588-lingmao-communication-legacy' if PROFILE == 'legacy' else 'out/rk3588-lingmao-communication')
helper = ROOT / 'out/rk3588-slam-features/build-navigation-monitored.py'
spec = importlib.util.spec_from_file_location('lingmao_build_monitor', helper)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.ROOT, runner.BASE, runner.STATUS = ROOT, BASE, BASE / 'build-status.json'

def commands():
    return [('uniubi-communication', [
        str(ROOT / 'platform/humble-build-tools/.venv/bin/colcon'),
        '--log-base', str(BASE / 'logs'), 'build',
        '--base-paths', str(BASE / 'source/uniubi_robot_msgs/ros2'),
        str(BASE / 'source/uniubi_ros2/src/uniubi_motion_client'),
        str(BASE / 'source/uniubi_ros2/src/uniubi_motion_bridge'),
        '--build-base', str(BASE / 'build'), '--install-base', str(BASE / 'install'),
        '--executor', 'sequential', '--event-handlers', 'console_direct+',
        '--packages-select', 'uniubi', 'uniubi_motion_client', 'uniubi_motion_bridge',
        '--cmake-args', '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG -g0',
        '-DPython3_EXECUTABLE=/usr/bin/python3', '-DPYTHON_EXECUTABLE=/usr/bin/python3',
        '-DCycloneDDS_DIR=/opt/ros/humble/lib/aarch64-linux-gnu/cmake/CycloneDDS',
        '-DBUILD_TESTING=ON'])]

runner.commands = commands
if __name__ == '__main__':
    raise SystemExit(runner.main())
