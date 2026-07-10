#!/usr/bin/env python3
"""启动维特 IMU 节点。可在这里改默认串口/波特率/frame_id/话题名。"""
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
            }],
        ),
    ])
