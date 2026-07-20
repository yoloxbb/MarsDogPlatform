import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """使用最新鱼眼标定和Kalibr时偏启动TST YUYV双目相机。"""
    config_dir = os.path.join(
        get_package_share_directory('stereo_v4l2_camera'), 'config')
    arguments = [
        DeclareLaunchArgument(
            'video_device',
            default_value=(
                '/dev/v4l/by-id/'
                'usb-TST_USB3.0_Camera_TST_USB3.0_Camera_01.00.000-'
                'video-index0'
            ),
        ),
        DeclareLaunchArgument('buffer_count', default_value='4'),
        # This camera pauses for about 1.04 s after its first STREAMON frame.
        DeclareLaunchArgument('poll_timeout_ms', default_value='3000'),
        DeclareLaunchArgument('reconnect_delay_ms', default_value='1000'),
        # TST 相机的拼接图顺序已经是左目在前、右目在后，无需再次交换。
        DeclareLaunchArgument('swap_left_right', default_value='false'),
        DeclareLaunchArgument('left_image_topic', default_value='/cam0/image_raw'),
        DeclareLaunchArgument('right_image_topic', default_value='/cam1/image_raw'),
        DeclareLaunchArgument('left_info_topic', default_value='/cam0/camera_info'),
        DeclareLaunchArgument('right_info_topic', default_value='/cam1/camera_info'),
        DeclareLaunchArgument('left_frame_id', default_value='cam0'),
        DeclareLaunchArgument('right_frame_id', default_value='cam1'),
        DeclareLaunchArgument(
            'left_camera_info_file',
            default_value=os.path.join(config_dir, 'left_equi.yaml')),
        DeclareLaunchArgument(
            'right_camera_info_file',
            default_value=os.path.join(config_dir, 'right_equi.yaml')),
        # 双目共用硬件时间戳，取两目Kalibr时偏的均值。
        DeclareLaunchArgument(
            'camera_time_offset_ms', default_value='30.730406888559322'),
    ]

    direct_camera_node = Node(
        package='stereo_v4l2_camera',
        executable='stereo_v4l2_direct_node',
        name='stereo_v4l2_direct_node',
        output='screen',
        parameters=[{
            'video_device': LaunchConfiguration('video_device'),
            'image_width': 1280,
            'image_height': 480,
            'pixel_format': 'YUYV',
            'framerate': 20,
            # Publish every native camera frame without a second rate limiter.
            'publish_framerate': 0,
            'qos_depth': 4,
            'reliable_qos': True,
            'buffer_count': ParameterValue(
                LaunchConfiguration('buffer_count'), value_type=int),
            'poll_timeout_ms': ParameterValue(
                LaunchConfiguration('poll_timeout_ms'), value_type=int),
            'reconnect_delay_ms': ParameterValue(
                LaunchConfiguration('reconnect_delay_ms'), value_type=int),
            'swap_left_right': ParameterValue(
                LaunchConfiguration('swap_left_right'), value_type=bool),
            'apply_camera_controls': True,
            'brightness': 128,
            'contrast': 64,
            'saturation': 76,
            'hue': 0,
            'white_balance_automatic': True,
            'gamma': 128,
            'gain': 128,
            'power_line_frequency': 1,
            'sharpness': 128,
            'backlight_compensation': 64,
            'auto_exposure': 3,
            # These controls are inactive while the corresponding auto mode is on.
            'disabled_camera_controls': [
                'exposure_time_absolute',
                'white_balance_temperature',
            ],
            'left_frame_id': LaunchConfiguration('left_frame_id'),
            'right_frame_id': LaunchConfiguration('right_frame_id'),
            'left_camera_info_file': LaunchConfiguration(
                'left_camera_info_file'),
            'right_camera_info_file': LaunchConfiguration(
                'right_camera_info_file'),
            'camera_time_offset_ms': ParameterValue(
                LaunchConfiguration('camera_time_offset_ms'),
                value_type=float),
        }],
        remappings=[
            ('/stereo/left/camera/image_mono',
             LaunchConfiguration('left_image_topic')),
            ('/stereo/right/camera/image_mono',
             LaunchConfiguration('right_image_topic')),
            ('/stereo/left/camera/camera_info',
             LaunchConfiguration('left_info_topic')),
            ('/stereo/right/camera/camera_info',
             LaunchConfiguration('right_info_topic')),
        ],
    )

    # 相机launch只发布图像和CameraInfo；imu_link外参由建图launch统一发布。
    return LaunchDescription(arguments + [direct_camera_node])
