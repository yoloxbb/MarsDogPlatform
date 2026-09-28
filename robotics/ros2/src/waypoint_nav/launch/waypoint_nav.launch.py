import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'waypoints_file',
            default_value=os.path.expanduser('~/.ros/waypoints.yaml'),
            description='地点文件路径（occupancy-editor 地点层导出）',
        ),
        DeclareLaunchArgument(
            'random_clearance_m',
            default_value='0.35',
            description='随机目标优先满足的已知空闲安全距离（米）',
        ),
        Node(
            package='waypoint_nav',
            executable='waypoint_nav_dispatcher',
            output='screen',
            parameters=[{
                'waypoints_file': LaunchConfiguration('waypoints_file'),
                'random_clearance_m': ParameterValue(
                    LaunchConfiguration('random_clearance_m'), value_type=float),
            }],
        ),
    ])
