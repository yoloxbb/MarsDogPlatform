"""Dual-tag round trip using the original UWB follow node and planner."""
import json
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration as LC
from launch_ros.actions import Node
from robot_local_motion_runtime.roundtrip_launch import validate_roles
from robot_local_motion_runtime.native_follow_launch import native_stack


def setup(context):
    value = lambda key: LC(key).perform(context)
    own = Path(get_package_share_directory('robot_local_motion'))
    owner, frisbee = validate_roles(value('owner_id'), value('frisbee_id'))
    enabled = value('enable_motion').lower() == 'true'
    profile = str(own/'config/lingmao_roundtrip.yaml')
    values = {key: value(key) for key in ('enable_motion', 'chassis_params_file', 'cmd_vel_topic',
        'odom_topic', 'odom_child_frame', 'start_obstacle_projection')}
    stack, _, _ = native_stack(values, '/uwb_roundtrip/selected_target', '/uwb_roundtrip/follow_diagnostics')
    serial = Node(package='robot_local_motion', executable='uwb_multitag_input', name='uwb_multitag_input',
        parameters=[str(own/'config/uwb_multitag.yaml'), {'enable_serial': value('enable_serial').lower() == 'true',
            'tag_overrides_json': json.dumps({frisbee: {'allow_jump_reacquire': True}})}])
    demo = Node(package='robot_local_motion', executable='uwb_roundtrip_demo', name='uwb_roundtrip_demo',
        output='screen', parameters=[profile, {'owner_id': owner, 'frisbee_id': frisbee,
            'enable_motion': enabled, 'autostart': value('autostart').lower() == 'true',
            'odom_topic': value('odom_topic'), 'odom_child_frame': value('odom_child_frame')}])
    return [*stack, serial, demo]


def generate_launch_description():
    defaults = {'owner_id': '', 'frisbee_id': '', 'enable_motion': 'false', 'enable_serial': 'false',
        'autostart': 'false', 'chassis_params_file': '', 'odom_topic': '/odom',
        'odom_child_frame': 'base_link', 'cmd_vel_topic': '/robot_local_motion/cmd_vel',
        'start_obstacle_projection': 'true'}
    return LaunchDescription([*[DeclareLaunchArgument(k, default_value=v) for k,v in defaults.items()],
                              OpaqueFunction(function=setup)])
