"""ROS launch integration for the robot profiles."""

import json
from pathlib import Path
import tempfile

from ament_index_python.packages import get_package_share_directory
from launch.actions import LogInfo, SetLaunchConfiguration
from launch.substitutions import LaunchConfiguration
from launch.substitution import Substitution
from launch_ros.actions import Node
import yaml

from robot_slam_bringup.robot_profiles import (
    launch_value, load_profile, merge_nav2, sensor_transform,
)


def configure_robot_profile(context):
    """Set defaults before declarations; explicit launch arguments take priority."""
    share = get_package_share_directory('robot_slam_bringup')
    robot = LaunchConfiguration('robot').perform(context)
    filename = LaunchConfiguration('robot_config').perform(context)
    profile, path = load_profile(share, robot, filename)
    context.extend_locals({'robot_profile': profile, 'robot_profile_path': str(path)})
    return [SetLaunchConfiguration(name, launch_value(value))
            for name, value in profile['launch'].items()
            if name not in context.launch_configurations]


class ProfiledNav2Params(Substitution):
    """Produce a temporary Nav2 YAML without modifying installed resources."""

    def __init__(self, common):
        super().__init__()
        self.common = common

    def describe(self):
        return '公共 Nav2 参数与所选机器人参数合并'

    def perform(self, context):
        common_file = self.common.perform(context)
        profile = context.locals.robot_profile
        cache_key = (common_file, context.locals.robot_profile_path)
        cached = getattr(context.locals, 'robot_nav2_params', None)
        if cached and cached[0] == cache_key:
            return cached[1]
        with Path(common_file).open(encoding='utf-8') as stream:
            params = merge_nav2(yaml.safe_load(stream), profile['nav2_overrides'])
        with tempfile.NamedTemporaryFile(mode='w', prefix='marsdog_nav2_',
                                         suffix='.yaml', delete=False,
                                         encoding='utf-8') as stream:
            yaml.safe_dump(params, stream, allow_unicode=True, sort_keys=False)
            filename = stream.name
        context.extend_locals({'robot_nav2_params': (cache_key, filename)})
        return filename


def show_configuration(context, configured_params):
    """Render resolved values without starting ROS nodes when print_config=true."""
    filename = configured_params.perform(context)
    with Path(filename).open(encoding='utf-8') as stream:
        params = yaml.safe_load(stream)
    names = ('robot', 'base_frame', 'odom_frame', 'map_frame', 'sensor_frame',
             'odom_topic', 'cmd_vel_topic', 'database_path', 'publish_odom_tf',
             'publish_sensor_tf', 'description_package', 'description_file',
             'description_root_frame', 'use_nav2', 'use_stereo_odometry')
    report = {name: LaunchConfiguration(name).perform(context) for name in names}
    if report['publish_sensor_tf'].lower() in ('true', '1', 'yes', 'on'):
        mount = sensor_transform(context.locals.robot_profile)
        if mount['parent_frame'] != report['base_frame']:
            raise ValueError('sensor_mount.parent_frame 与 base_frame 不一致')
    report.update(
        profile_file=context.locals.robot_profile_path,
        nav2_params_file=filename,
        footprint=params['local_costmap']['local_costmap']['ros__parameters']['footprint'],
        mppi={key: params['controller_server']['ros__parameters']['FollowPath'][key]
              for key in ('plugin', 'motion_model', 'vx_max', 'vx_min', 'wz_max')},
        sensor_mount=context.locals.robot_profile.get('sensor_mount'),
    )
    return [LogInfo(msg='ROBOT_CONFIG=' + json.dumps(report, ensure_ascii=False))]


def create_sensor_transform(context):
    """Publish a supplied base-to-camera mount only on explicit request."""
    mount = sensor_transform(context.locals.robot_profile)
    base_frame = LaunchConfiguration('base_frame').perform(context)
    if mount['parent_frame'] != base_frame:
        raise ValueError('sensor_mount.parent_frame 与 base_frame 不一致，请更新机器人配置')
    args = []
    for key, value in zip(('x', 'y', 'z'), mount['xyz']):
        args.extend([f'--{key}', str(value)])
    for key, value in zip(('roll', 'pitch', 'yaw'), mount['rpy']):
        args.extend([f'--{key}', str(value)])
    args.extend(['--frame-id', mount['parent_frame'], '--child-frame-id', mount['child_frame']])
    return [Node(package='tf2_ros', executable='static_transform_publisher',
                 name='robot_camera_mount', arguments=args, output='screen')]
