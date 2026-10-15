"""PC visualization only; mapping and TF publishers remain on the board."""
import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    directory = os.path.dirname(os.path.abspath(__file__))
    stereo = {
        'frame_id': 'base_footprint',
        'odom_frame_id': 'odom',
        'use_sim_time': False,
        'subscribe_depth': False,
        'subscribe_rgbd': False,
        'subscribe_rgb': False,
        'subscribe_stereo': False,
        'subscribe_odom': False,
        'subscribe_odom_info': False,
        'approx_sync': True,
        'approx_sync_max_interval': 0.1,
        'sync_queue_size': 10,
        'topic_queue_size': 5,
        'qos_image': 2,
        'qos_camera_info': 1,
        'wait_for_transform': 0.5,
    }
    return LaunchDescription([
        DeclareLaunchArgument('use_rviz', default_value='true'),
        DeclareLaunchArgument('use_rtabmap_viz', default_value='false'),
        DeclareLaunchArgument('rviz_config', default_value=os.path.join(directory, 'remote_viz.rviz')),
        Node(package='rviz2', executable='rviz2', name='remote_rviz', output='screen',
             arguments=['-d', LaunchConfiguration('rviz_config')],
             condition=IfCondition(LaunchConfiguration('use_rviz'))),
        Node(package='rtabmap_viz', executable='rtabmap_viz', name='remote_rtabmap_viz',
             output='screen', parameters=[stereo],
             remappings=[
                 ('left/image_rect', '/camera/camera/infra1/image_rect_raw'),
                 ('right/image_rect', '/camera/camera/infra2/image_rect_raw'),
                 ('left/camera_info', '/camera/camera/infra1/camera_info'),
                 ('right/camera_info', '/camera/camera/infra2/camera_info'),
                 ('odom', '/odom'), ('info', '/info'), ('mapData', '/mapData'),
             ], condition=IfCondition(LaunchConfiguration('use_rtabmap_viz'))),
    ])
