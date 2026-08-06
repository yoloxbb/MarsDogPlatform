"""使用 D435i 原始话题和 TF 启动手持视觉惯性建图。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def package_launch(package_name, launch_name):
    """返回指定 ROS 包中的 Python 启动文件。"""
    launch_path = os.path.join(
        get_package_share_directory(package_name),
        'launch',
        launch_name,
    )
    return PythonLaunchDescriptionSource(launch_path)


def generate_launch_description():
    """组合 D435i 原始数据、OpenVINS 和 RTAB-Map 手持建图管线。"""
    package_share = get_package_share_directory('stereo_slam_legacy_bringup')
    config_dir = os.path.join(package_share, 'config')

    params_file = LaunchConfiguration('params_file')
    database_path = LaunchConfiguration('database_path')
    delete_db_on_start = LaunchConfiguration('delete_db_on_start')
    launch_viz = LaunchConfiguration('launch_viz')
    use_sim_time = LaunchConfiguration('use_sim_time')
    camera_frame_id = LaunchConfiguration('camera_frame_id')
    left_image_topic = LaunchConfiguration('left_image_topic')
    right_image_topic = LaunchConfiguration('right_image_topic')
    left_info_topic = LaunchConfiguration('left_info_topic')
    right_info_topic = LaunchConfiguration('right_info_topic')
    imu_topic = LaunchConfiguration('imu_topic')
    leg_velocity_enabled = LaunchConfiguration('leg_velocity_enabled')
    leg_odom_topic = LaunchConfiguration('leg_odom_topic')
    startup_delay = LaunchConfiguration('startup_delay')
    log_level = LaunchConfiguration('log_level')

    declared_arguments = [
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                config_dir, 'd435i_rtabmap_openvins.yaml'),
            description='D435i 的 OpenVINS 与 RTAB-Map 参数文件。',
        ),
        DeclareLaunchArgument(
            'database_path',
            default_value=os.path.expanduser(
                '~/.ros/rtabmap_d435i_handheld.db'),
            description='手持建图使用的 RTAB-Map 数据库。',
        ),
        DeclareLaunchArgument(
            'delete_db_on_start',
            default_value='true',
            description='启动时是否删除旧数据库并重新建图。',
        ),
        DeclareLaunchArgument(
            'launch_viz',
            default_value='true',
            description='是否启动 rtabmap_viz。',
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='是否使用 /clock 仿真时钟。',
        ),
        DeclareLaunchArgument(
            'camera_frame_id',
            default_value='camera_link',
            description='手持建图的基准坐标系。',
        ),
        DeclareLaunchArgument(
            'left_image_topic',
            default_value='/camera/camera/infra1/image_rect_raw',
            description='D435i 左红外校正图像话题。',
        ),
        DeclareLaunchArgument(
            'right_image_topic',
            default_value='/camera/camera/infra2/image_rect_raw',
            description='D435i 右红外校正图像话题。',
        ),
        DeclareLaunchArgument(
            'left_info_topic',
            default_value='/camera/camera/infra1/camera_info',
            description='D435i 左红外 CameraInfo 话题。',
        ),
        DeclareLaunchArgument(
            'right_info_topic',
            default_value='/camera/camera/infra2/camera_info',
            description='D435i 右红外 CameraInfo 话题。',
        ),
        DeclareLaunchArgument(
            'imu_topic',
            default_value='/camera/camera/imu',
            description='D435i 驱动发布的合并 IMU 话题。',
        ),
        DeclareLaunchArgument(
            'leg_velocity_enabled',
            default_value='false',
            description='视觉退化时是否启用 OpenVINS 内部足式速度辅助。',
        ),
        DeclareLaunchArgument(
            'leg_odom_topic',
            default_value='/odom_leg',
            description='足式运动学里程计话题。',
        ),
        DeclareLaunchArgument(
            'startup_delay',
            default_value='1.0',
            description='等待外部 D435i 和 TF 稳定的时间，单位秒。',
        ),
        DeclareLaunchArgument(
            'log_level',
            default_value='info',
            description='OpenVINS 和 RTAB-Map 的日志等级。',
        ),
    ]

    # 直接使用 RealSense 驱动的 CameraInfo、IMU frame_id 和静态 TF。
    # 手持设备保留完整的 x/y/z/roll/pitch/yaw 六自由度运动。
    mapping_launch = IncludeLaunchDescription(
        package_launch(
            'stereo_slam_legacy_bringup',
            'rtabmap_openvins_stereo_mapping.launch.py',
        ),
        launch_arguments={
            'params_file': params_file,
            'frame_id': camera_frame_id,
            'odom_frame_id': 'odom',
            'map_frame_id': 'map',
            'publish_odom_tf': 'true',
            'publish_map_tf': 'true',
            'planar_mode': 'false',
            'localization': 'false',
            'use_sim_time': use_sim_time,
            'odom_left_image_topic': left_image_topic,
            'odom_right_image_topic': right_image_topic,
            'odom_left_info_topic': left_info_topic,
            'odom_right_info_topic': right_info_topic,
            'odom_images_already_rectified': 'true',
            'left_image_topic': left_image_topic,
            'right_image_topic': right_image_topic,
            'left_info_topic': left_info_topic,
            'right_info_topic': right_info_topic,
            'imu_topic': imu_topic,
            'leg_velocity_enabled': leg_velocity_enabled,
            'leg_odom_topic': leg_odom_topic,
            # D435i 原始 IMU 不含 orientation，不能送入 RTAB-Map 异步接口。
            'orientation_imu_topic': '/rtabmap/unused_orientation_imu',
            'odom_topic': '/odom',
            'odom_info_topic': '/odom_info',
            'database_path': database_path,
            'delete_db_on_start': delete_db_on_start,
            'launch_viz': launch_viz,
            'log_level': log_level,
        }.items(),
    )

    delayed_mapping = TimerAction(
        period=startup_delay,
        actions=[mapping_launch],
    )

    return LaunchDescription(declared_arguments + [delayed_mapping])
