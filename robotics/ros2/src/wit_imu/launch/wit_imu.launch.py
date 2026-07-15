#!/usr/bin/env python3
"""启动低延迟维特IMU C++节点。"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='wit_imu',
            executable='wit_imu_node',
            name='wit_imu_node',
            output='screen',
            parameters=[{
                'port': '/dev/ttyUSB0',
                'baud': 115200,
                'frame_id': 'imu_link',
                'topic': 'imu/data_raw',
                'expected_rate_hz': 200.0,
                'qos_depth': 5,
                'poll_timeout_ms': 500,
                'serial_data_timeout_ms': 2000,
                'reconnect_delay_ms': 1000,
                # CPU短时抢占后最多允许IMU时间轴落后20ms，超过即重新锚定。
                'timestamp_resync_threshold_ms': 20.0,
                # 0表示协方差未知，避免向VIO提供未经标定的置信度。
                'angular_velocity_covariance': 0.0,
                'linear_acceleration_covariance': 0.0,
            }],
        ),
    ])
