import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """以 2560x720 YUYV 采集双目拼接图，并分别发布 1280x720 图像。"""
    package_config_dir = os.path.join(
        get_package_share_directory('stereo_v4l2_camera'), 'config')

    arguments = [
        DeclareLaunchArgument('video_device', default_value='/dev/video0'),
        DeclareLaunchArgument('buffer_count', default_value='4'),
        DeclareLaunchArgument('poll_timeout_ms', default_value='1000'),
        DeclareLaunchArgument('reconnect_delay_ms', default_value='1000'),
        DeclareLaunchArgument('swap_left_right', default_value='true'),
        DeclareLaunchArgument('left_frame_id', default_value='cam0'),
        DeclareLaunchArgument('right_frame_id', default_value='cam1'),
        DeclareLaunchArgument(
            'camera_time_offset_ms',
            default_value='0.0',
            description='加到相机时间戳上的 Kalibr 时偏，单位为毫秒。',
        ),
        DeclareLaunchArgument(
            'left_camera_info_file',
            default_value=os.path.join(
                package_config_dir, 'left_hb_2560.yaml'),
            description='左目 1280x720 CameraInfo 文件。',
        ),
        DeclareLaunchArgument(
            'right_camera_info_file',
            default_value=os.path.join(
                package_config_dir, 'right_hb_2560.yaml'),
            description='右目 1280x720 CameraInfo 文件。',
        ),
    ]

    direct_camera_node = Node(
        package='stereo_v4l2_camera',
        executable='stereo_v4l2_direct_node',
        name='stereo_v4l2_direct_node',
        output='screen',
        parameters=[{
            'video_device': LaunchConfiguration('video_device'),
            'image_width': 2560,
            'image_height': 720,
            'pixel_format': 'YUYV',
            # 使用本次 1280x720 单目高分辨率标定对应的采集模式。
            'framerate': 60,
            # 发布线程只取最新帧，以 20 Hz 向 VIO 输出并降低处理压力。
            'publish_framerate': 20,
            'buffer_count': ParameterValue(
                LaunchConfiguration('buffer_count'), value_type=int),
            'poll_timeout_ms': ParameterValue(
                LaunchConfiguration('poll_timeout_ms'), value_type=int),
            'reconnect_delay_ms': ParameterValue(
                LaunchConfiguration('reconnect_delay_ms'), value_type=int),
            'swap_left_right': ParameterValue(
                LaunchConfiguration('swap_left_right'), value_type=bool),
            'apply_camera_controls': True,
            'brightness': 0,
            'contrast': 32,
            'saturation': 38,
            'hue': 0,
            'white_balance_automatic': False,
            'gamma': 150,
            # Configure only the controls reported by this camera.
            'disabled_camera_controls': [
                'auto_exposure',
                'exposure_time_absolute',
                'white_balance_temperature',
                'gain',
                'power_line_frequency',
                'sharpness',
                'backlight_compensation',
            ],
            'left_frame_id': LaunchConfiguration('left_frame_id'),
            'right_frame_id': LaunchConfiguration('right_frame_id'),
            # 让图像时间戳与本次 Kalibr 的 IMU 时间基准保持一致。
            'camera_time_offset_ms': ParameterValue(
                LaunchConfiguration('camera_time_offset_ms'),
                value_type=float),
            'left_camera_info_file': LaunchConfiguration(
                'left_camera_info_file'),
            'right_camera_info_file': LaunchConfiguration(
                'right_camera_info_file'),
        }],
    )

    # tf_cam_link_left = Node(
    #     package='tf2_ros',
    #     executable='static_transform_publisher',
    #     name='tf_cam_link_left',
    #     arguments=[
    #         '0.01', '0.025', '0.087', '0', '0', '0', '1',
    #         'camera_link', 'left_camera'],
    # )
    # tf_cam_link_right = Node(
    #     package='tf2_ros',
    #     executable='static_transform_publisher',
    #     name='tf_cam_link_right',
    #     arguments=[
    #         '0.01', '-0.025', '0.087', '0', '0', '0', '1',
    #         'camera_link', 'right_camera'],
    # )
    # tf_left_optical = Node(
    #     package='tf2_ros',
    #     executable='static_transform_publisher',
    #     name='tf_left_optical',
    #     arguments=[
    #         '0', '0', '0', '-1.570796', '0', '-1.570796',
    #         'left_camera', 'camera_left_frame'],
    # )
    # tf_right_optical = Node(
    #     package='tf2_ros',
    #     executable='static_transform_publisher',
    #     name='tf_right_optical',
    #     arguments=[
    #         '0', '0', '0', '-1.570796', '0', '-1.570796',
    #         'right_camera', 'camera_right_frame'],
    # )

    return LaunchDescription(arguments + [
        # tf_cam_link_left,
        # tf_cam_link_right,
        # tf_left_optical,
        # tf_right_optical,
        direct_camera_node,
    ])
