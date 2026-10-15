"""Robot model, odometry and sensor TF only; no mapping or navigation runtime."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, OpaqueFunction
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration

from robot_slam_bringup.profile_launch import (
    configure_robot_profile,
    create_odometry_relay,
    create_robot_state_publisher,
    create_sensor_transform,
    create_uwb_transform,
    declare_tf_arguments,
    show_tf_configuration,
)
from robot_slam_bringup.robot_profiles import ROBOTS


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('robot', default_value='lite3', choices=ROBOTS),
        DeclareLaunchArgument('robot_config', default_value='',
                              description='个人机器人 YAML；留空读取包内所选机器人配置'),
        OpaqueFunction(function=configure_robot_profile),
        *declare_tf_arguments(),
        DeclareLaunchArgument('print_config', default_value='false',
                              description='只打印 TF 配置，不启动任何 ROS 节点'),
        OpaqueFunction(function=show_tf_configuration),
        GroupAction(condition=UnlessCondition(LaunchConfiguration('print_config')), actions=[
            OpaqueFunction(function=create_robot_state_publisher),
            OpaqueFunction(condition=IfCondition(LaunchConfiguration('publish_sensor_tf')),
                           function=create_sensor_transform),
            OpaqueFunction(function=create_uwb_transform),
            OpaqueFunction(condition=IfCondition(LaunchConfiguration('publish_odom_tf')),
                           function=create_odometry_relay),
        ]),
    ])
