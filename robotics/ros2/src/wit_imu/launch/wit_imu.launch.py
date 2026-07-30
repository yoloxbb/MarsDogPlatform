#!/usr/bin/env python3
"""启动可配置的低延迟 WIT IMU C++ 节点。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """创建支持串口、频率和低通参数覆盖的 WIT IMU 启动描述。"""
    port = LaunchConfiguration('port')
    baud = LaunchConfiguration('baud')
    expected_rate_hz = LaunchConfiguration('expected_rate_hz')
    raw_topic = LaunchConfiguration('raw_topic')
    filtered_topic = LaunchConfiguration('filtered_topic')
    enable_low_pass = LaunchConfiguration('enable_low_pass')
    low_pass_cutoff_hz = LaunchConfiguration('low_pass_cutoff_hz')

    return LaunchDescription([
        # 设备默认配置为 115200 baud、200 Hz，仍允许启动时覆盖。
        DeclareLaunchArgument(
            'port',
            default_value='/dev/ttyUSB0',
            description='WIT IMU 对应的串口设备',
        ),
        DeclareLaunchArgument(
            'baud',
            default_value='115200',
            description='WIT IMU 串口波特率',
        ),
        DeclareLaunchArgument(
            'expected_rate_hz',
            default_value='200.0',
            description='WIT IMU 预期数据输出频率',
        ),
        DeclareLaunchArgument(
            'enable_low_pass',
            default_value='true',
            description='是否额外发布二阶 Butterworth 低通数据',
        ),
        DeclareLaunchArgument(
            'low_pass_cutoff_hz',
            default_value='20.0',
            description='低通截止频率；IMU 输出仍保持 200 Hz',
        ),
        DeclareLaunchArgument(
            'raw_topic',
            default_value='/imu/data_raw',
            description='未经软件滤波的原始 IMU 话题',
        ),
        DeclareLaunchArgument(
            'filtered_topic',
            default_value='/imu/data_filtered',
            description='二阶 Butterworth 低通后的 IMU 话题',
        ),
        Node(
            package='wit_imu',
            executable='wit_imu_node',
            name='wit_imu_node',
            output='screen',
            parameters=[{
                'port': port,
                # 显式指定参数类型，避免 LaunchConfiguration 被当成字符串。
                'baud': ParameterValue(baud, value_type=int),
                'frame_id': 'imu_link',
                'topic': raw_topic,
                'filtered_topic': filtered_topic,
                'enable_low_pass': ParameterValue(
                    enable_low_pass, value_type=bool),
                'low_pass_cutoff_hz': ParameterValue(
                    low_pass_cutoff_hz, value_type=float),
                'expected_rate_hz': ParameterValue(
                    expected_rate_hz, value_type=float),
                'qos_depth': 5,
                'poll_timeout_ms': 500,
                'serial_data_timeout_ms': 2000,
                'reconnect_delay_ms': 1000,
                # CPU 短时抢占后最多允许时间轴落后 20 ms，超过即重新锚定。
                'timestamp_resync_threshold_ms': 20.0,
                # 0 表示协方差未知，避免向 VIO 提供未经标定的置信度。
                'angular_velocity_covariance': 0.0,
                'linear_acceleration_covariance': 0.0,
            }],
        ),
    ])
