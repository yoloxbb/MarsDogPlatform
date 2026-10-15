"""ROS launch integration for the robot profiles."""

import json
import math
from pathlib import Path
import tempfile

from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument, LogInfo, SetLaunchConfiguration
from launch.substitutions import LaunchConfiguration
from launch.substitution import Substitution
from launch_ros.actions import Node
import yaml

from robot_slam_bringup.robot_profiles import (
    launch_value, load_profile, merge_nav2, prepare_description, sensor_transform, uwb_transform,
)


TF_ARGUMENTS = (
    'base_frame', 'body_frame', 'odom_child_frame', 'split_base_frames',
    'body_height', 'odom_frame', 'odom_topic', 'nav2_odom_topic',
    'start_robot_state_publisher', 'description_package', 'description_file',
    'description_root_frame', 'publish_odom_tf', 'publish_sensor_tf',
)


def declare_tf_arguments():
    """Keep TF defaults identical for standalone and navigation launches."""
    defaults = (
        'base_footprint', LaunchConfiguration('base_frame'), LaunchConfiguration('body_frame'),
        'false', '', 'odom', '/leg_odom2', LaunchConfiguration('odom_topic'),
        'false', '', '', '', 'false', 'false',
    )
    descriptions = (
        '导航基座坐标系；灵猫为 base_footprint',
        'URDF 与传感器安装的物理机身坐标系；灵猫为 base_link',
        '保留外部 Odometry 的原始 child_frame_id',
        '将平面里程计与机身高度/姿态分开发布',
        '覆盖 profile 的站姿机身高度，单位 m；留空使用 YAML',
        '里程计坐标系', '外部 nav_msgs/msg/Odometry 输入话题',
        'Reliable 里程计转发话题；与输入相同时不转发',
        '从所选描述包启动 robot_state_publisher',
        '机器人描述包名', '描述包内 URDF 的相对路径',
        '原 URDF 根名称；运行时重命名为 body_frame',
        '仅在外部来源不发布 odom TF 时启用 relay',
        '从机器人 YAML 发布相机安装 TF',
    )
    return [DeclareLaunchArgument(name, default_value=default, description=description)
            for name, default, description in zip(TF_ARGUMENTS, defaults, descriptions)]


def enabled(context, name):
    return LaunchConfiguration(name).perform(context).strip().lower() in ('true', '1', 'yes', 'on')


def configured_body_height(context):
    """Use an explicit measured height; a missing value stays unavailable."""
    override = LaunchConfiguration('body_height').perform(context).strip()
    value = override if override else context.locals.robot_profile.get('body_geometry', {}).get('height')
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('body_height 必须是实测正数，单位 m')
    try:
        height = float(value)
    except (ValueError, TypeError) as error:
        raise ValueError('body_height 必须是实测正数，单位 m') from error
    if not math.isfinite(height) or height <= 0:
        raise ValueError('body_height 必须是实测正数，单位 m')
    return height


def create_robot_state_publisher(context):
    """Compose the selected model and configured sensor joints in one owner."""
    if not enabled(context, 'start_robot_state_publisher'):
        return []
    values = {name: LaunchConfiguration(name).perform(context).strip()
              for name in ('description_package', 'description_file',
                           'body_frame', 'description_root_frame')}
    if not values['description_package'] or not values['description_file']:
        raise ValueError('启用 robot_state_publisher 时必须指定 description_package 和 description_file')
    profile = context.locals.robot_profile
    mount = sensor_transform(profile) if enabled(context, 'publish_sensor_tf') else None
    description = prepare_description(
        get_package_share_directory(values['description_package']),
        values['description_file'], values['description_package'],
        values['body_frame'], values['description_root_frame'], mount=mount,
        joint_aliases=profile.get('description_joint_aliases'),
        uwb_mount=uwb_transform(profile) if mount is not None else None)
    return [Node(package='robot_state_publisher', executable='robot_state_publisher',
                 name='robot_state_publisher', output='screen',
                 parameters=[{'robot_description': description}])]


def create_odometry_relay(context):
    """Keep the direct relay by default; split only for the selected profile."""
    names = ('odom_topic', 'nav2_odom_topic', 'odom_frame', 'base_frame', 'body_frame', 'odom_child_frame')
    values = {name: LaunchConfiguration(name).perform(context).strip() for name in names}
    split = enabled(context, 'split_base_frames')
    height = configured_body_height(context) if split else None
    return [Node(package='robot_slam_bringup', executable='odometry_tf_relay',
                 name='odometry_tf_relay', output='screen', parameters=[{
                     'odom_topic': values['odom_topic'], 'odom_frame': values['odom_frame'],
                     'base_frame': values['base_frame'], 'body_frame': values['body_frame'],
                     'input_base_frame': values['odom_child_frame'], 'split_base_frames': split,
                     'body_height': height if height is not None else 0.0,
                     'output_odom_topic': (values['nav2_odom_topic']
                         if values['nav2_odom_topic'] != values['odom_topic'] else ''),
                 }])]


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


def show_tf_configuration(context):
    """Print resolved TF values without loading Nav2 or starting ROS nodes."""
    profile = context.locals.robot_profile
    report = {name: LaunchConfiguration(name).perform(context)
              for name in ('robot', 'robot_config', *TF_ARGUMENTS)}
    if enabled(context, 'publish_sensor_tf'):
        mount = sensor_transform(profile)
        if mount['parent_frame'] != report['body_frame']:
            raise ValueError('sensor_mount.parent_frame 与 body_frame 不一致')
    report.update(profile_file=context.locals.robot_profile_path,
                  body_height=configured_body_height(context),
                  sensor_mount=profile.get('sensor_mount'),
                  uwb_mount=uwb_transform(profile))
    return [LogInfo(msg='ROBOT_TF_CONFIG=' + json.dumps(report, ensure_ascii=False))]


def show_configuration(context, configured_params):
    """Render resolved values without starting ROS nodes when print_config=true."""
    filename = configured_params.perform(context)
    with Path(filename).open(encoding='utf-8') as stream:
        params = yaml.safe_load(stream)
    names = ('robot', 'base_frame', 'odom_frame', 'map_frame', 'sensor_frame',
             'odom_topic', 'nav2_odom_topic', 'cmd_vel_topic', 'database_path', 'publish_odom_tf',
             'publish_sensor_tf', 'description_package', 'description_file',
             'description_root_frame', 'use_nav2', 'use_stereo_odometry',
             'body_frame', 'odom_child_frame', 'split_base_frames', 'frames_only',
             'start_robot_state_publisher', 'start_tf')
    report = {name: LaunchConfiguration(name).perform(context) for name in names}
    if report['publish_sensor_tf'].lower() in ('true', '1', 'yes', 'on'):
        mount = sensor_transform(context.locals.robot_profile)
        if mount['parent_frame'] != report['body_frame']:
            raise ValueError('sensor_mount.parent_frame 与 body_frame 不一致')
    uwb_mount = uwb_transform(context.locals.robot_profile)
    report.update(
        profile_file=context.locals.robot_profile_path,
        nav2_params_file=filename,
        footprint=params['local_costmap']['local_costmap']['ros__parameters']['footprint'],
        mppi={key: params['controller_server']['ros__parameters']['FollowPath'][key]
              for key in ('plugin', 'motion_model', 'vx_max', 'vx_min', 'wz_max')},
        sensor_mount=context.locals.robot_profile.get('sensor_mount'),
        body_height=configured_body_height(context),
        uwb_mount=uwb_mount,
        uwb_tf_owner=('external' if not enabled(context, 'start_tf') else (
            'robot_state_publisher' if enabled(context, 'start_robot_state_publisher')
            and enabled(context, 'publish_sensor_tf') else 'robot_uwb_mount'
        )) if uwb_mount is not None else 'external_or_pending',
        camera_tf_owner=('external' if not enabled(context, 'start_tf') else (
            'robot_state_publisher' if enabled(context, 'start_robot_state_publisher')
            else 'robot_camera_mount')) if enabled(context, 'publish_sensor_tf') else 'external_or_pending',
    )
    return [LogInfo(msg='ROBOT_CONFIG=' + json.dumps(report, ensure_ascii=False))]


def create_sensor_transform(context):
    """Publish a supplied base-to-camera mount only on explicit request."""
    mount = sensor_transform(context.locals.robot_profile)
    body_frame = LaunchConfiguration('body_frame').perform(context)
    if mount['parent_frame'] != body_frame:
        raise ValueError('sensor_mount.parent_frame 与 body_frame 不一致，请更新机器人配置')
    if enabled(context, 'start_robot_state_publisher'):
        return []  # The measured mount is already part of the composed URDF.
    return [_static_mount_node(mount, 'robot_camera_mount')]


def _static_mount_node(mount, name):
    """Use the same named-argument convention for optional sensor publishers."""
    args = []
    for key, value in zip(('x', 'y', 'z'), mount['xyz']):
        args.extend([f'--{key}', str(value)])
    for key, value in zip(('roll', 'pitch', 'yaw'), mount['rpy']):
        args.extend([f'--{key}', str(value)])
    args.extend(['--frame-id', mount['parent_frame'], '--child-frame-id', mount['child_frame']])
    return Node(package='tf2_ros', executable='static_transform_publisher',
                name=name, arguments=args, output='screen')


def create_uwb_transform(context):
    """Use one owner: composed URDF normally, a static publisher without it."""
    mount = uwb_transform(context.locals.robot_profile)
    if mount is None:
        return []
    if enabled(context, 'start_robot_state_publisher') and enabled(context, 'publish_sensor_tf'):
        return []  # The UWB joint is already part of the composed URDF.
    return [_static_mount_node(mount, 'robot_uwb_mount')]
