"""Shared assembly of the unchanged original follow and local planner nodes."""
from pathlib import Path
import yaml
from ament_index_python.packages import get_package_share_directory
from launch.actions import GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from .roundtrip_launch import validate_chassis


def native_stack(values, target_topic, diagnostics_topic, tracking=False, distance=.8,
                 with_follow=True, planner_output=None):
    own = Path(get_package_share_directory('robot_local_motion'))
    old = Path(get_package_share_directory('go2_uwb_local_follow'))
    enabled = values['enable_motion'].lower() == 'true'
    chassis = values['chassis_params_file']
    if enabled and not chassis:
        raise ValueError('real motion requires chassis_params_file with measured Lingmao minimum speed and braking values; see README')
    if chassis:
        chassis = str(Path(chassis).expanduser())
        minimum, decel = validate_chassis(yaml.safe_load(Path(chassis).read_text()))
    else:
        minimum, decel = .10, .70
    profile = str(own/'config/lingmao_roundtrip.yaml')
    local = GroupAction(scoped=True, actions=[IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(own/'launch/local_motion.launch.py')),
        launch_arguments={'enable_motion': values['enable_motion'], 'server_params_file': profile,
            'start_server': 'false', 'planner_cmd_vel_topic': planner_output or values['cmd_vel_topic'],
            'chassis_params_file': chassis or profile,
            'planner_params_file': str(old/'config/local_velocity_planner.yaml'),
            'odom_topic': values['odom_topic'], 'odom_child_frame': values['odom_child_frame'],
            'base_frame': 'base_footprint', 'odom_frame': 'odom',
            'cmd_vel_topic': values['cmd_vel_topic'],
            'start_uwb_bridge': 'false', 'start_uwb_adapter': 'false', 'start_uwb_multitag': 'false',
            'start_obstacle_projection': values['start_obstacle_projection']}.items())])
    nodes = [local]
    if with_follow:
        nodes.append(Node(package='go2_uwb_local_follow', executable='uwb_follow_controller_node',
            name='uwb_follow_controller_node', output='screen',
            parameters=[str(old/'config/uwb_follow_only.yaml'), profile, {
                'target_topic': target_topic, 'odom_topic': values['odom_topic'],
                'enable_motion': False, 'tracking_enabled': tracking,
                'follow_distance': float(distance),
                'cmd_vel_topic': diagnostics_topic.rsplit('/', 1)[0]+'/follow_debug_cmd',
                'nominal_cmd_topic': '/robot_local_motion/nominal_cmd',
                'diagnostics_topic': diagnostics_topic,
                'min_linear_speed': minimum, 'max_linear_decel': decel}]))
    return nodes, minimum, decel
