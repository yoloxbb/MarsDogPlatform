"""显式启用四维足式速度辅助的 D435i OpenVINS 建图入口。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    """复用原启动管线，只打开足式速度辅助并绑定足式里程计话题。"""
    package_share = get_package_share_directory(
        'stereo_slam_legacy_bringup')
    launch_path = os.path.join(
        package_share, 'launch', 'd435i_openvins_rtabmap.launch.py')

    mapping_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(launch_path),
        launch_arguments={
            # 杆臂和足式速度都以机器人 base_link 为刚体参考点。
            'camera_frame_id': 'base_link',
            'leg_velocity_enabled': 'true',
            'leg_odom_topic': '/odom_leg',
        }.items(),
    )
    return LaunchDescription([mapping_launch])
