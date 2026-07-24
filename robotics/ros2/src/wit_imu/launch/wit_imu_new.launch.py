#!/usr/bin/env python3
"""使用已配置为 200 Hz 的新 WIT IMU 启动 ROS 2 驱动。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """创建新 IMU 的可配置启动描述。"""
    port = LaunchConfiguration('port')
    baud = LaunchConfiguration('baud')
    expected_rate_hz = LaunchConfiguration('expected_rate_hz')

    return LaunchDescription([
        # 新设备已写入 115200 baud、200 Hz，参数仍可从命令行覆盖。
        DeclareLaunchArgument(
            'port',
            default_value='/dev/ttyUSB0',
            description='新 IMU 对应的串口设备',
        ),
        DeclareLaunchArgument(
            'baud',
            default_value='115200',
            description='新 IMU 当前配置的串口波特率',
        ),
        DeclareLaunchArgument(
            'expected_rate_hz',
            default_value='200.0',
            description='新 IMU 当前配置的数据输出频率',
        ),
        Node(
            package='wit_imu',
            executable='wit_imu_node',
            name='wit_imu_node',
            output='screen',
            parameters=[{
                'port': port,
                # 显式指定参数类型，避免 LaunchConfiguration 被当成字符串传入节点。
                'baud': ParameterValue(baud, value_type=int),
                'frame_id': 'imu_link',
                'topic': 'imu/data_raw',
                'expected_rate_hz': ParameterValue(
                    expected_rate_hz, value_type=float),
                'qos_depth': 5,
                'poll_timeout_ms': 500,
                'serial_data_timeout_ms': 2000,
                'reconnect_delay_ms': 1000,
                'timestamp_resync_threshold_ms': 20.0,
                # 0 表示协方差未知，避免向 VIO 提供未经标定的置信度。
                'angular_velocity_covariance': 0.0,
                'linear_acceleration_covariance': 0.0,
            }],
        ),
    ])
