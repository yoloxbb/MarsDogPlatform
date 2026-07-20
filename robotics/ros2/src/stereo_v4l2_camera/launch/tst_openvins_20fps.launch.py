import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def int_parameter(name):
    """把启动参数显式转换为整数类型的ROS参数."""
    return ParameterValue(LaunchConfiguration(name), value_type=int)


def bool_parameter(name):
    """把启动参数显式转换为布尔类型的ROS参数."""
    return ParameterValue(LaunchConfiguration(name), value_type=bool)


def float_parameter(name):
    """把启动参数显式转换为浮点类型的ROS参数。"""
    return ParameterValue(LaunchConfiguration(name), value_type=float)


def generate_launch_description():
    """使用鱼眼标定和Kalibr时偏启动面向OpenVINS的TST双目相机。"""
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
        # Prefer YUYV on a real USB 3 link; MJPEG is the 20 FPS fallback on USB 2.
        DeclareLaunchArgument('pixel_format', default_value='YUYV'),
        DeclareLaunchArgument('image_width', default_value='1280'),
        DeclareLaunchArgument('image_height', default_value='480'),
        DeclareLaunchArgument('framerate', default_value='20'),
        # 0表示发布每一帧原始相机图像，不再进行二次限频。
        DeclareLaunchArgument('publish_framerate', default_value='0'),
        DeclareLaunchArgument('qos_depth', default_value='4'),
        DeclareLaunchArgument('reliable_qos', default_value='true'),
        DeclareLaunchArgument('buffer_count', default_value='4'),
        # This camera pauses for about 1.04 s after its first STREAMON frame.
        DeclareLaunchArgument('poll_timeout_ms', default_value='3000'),
        DeclareLaunchArgument('reconnect_delay_ms', default_value='1000'),
        # Kalibr录包使用的是第一半幅=左目、第二半幅=右目，运行时必须保持相同顺序。
        DeclareLaunchArgument('swap_left_right', default_value='false'),
        DeclareLaunchArgument('apply_camera_controls', default_value='true'),
        DeclareLaunchArgument('brightness', default_value='50'),
        DeclareLaunchArgument('contrast', default_value='50'),
        DeclareLaunchArgument('saturation', default_value='128'),
        DeclareLaunchArgument('hue', default_value='0'),
        DeclareLaunchArgument(
            'white_balance_automatic', default_value='false'),
        # V4L2 exposure units are 100 us: 100 means 10 ms.
        DeclareLaunchArgument('exposure_time_absolute', default_value='580'),
        DeclareLaunchArgument('gamma', default_value='120'),
        DeclareLaunchArgument('gain', default_value='128'),
        DeclareLaunchArgument('white_balance_temperature', default_value='4650'),
        DeclareLaunchArgument('power_line_frequency', default_value='1'),
        DeclareLaunchArgument('sharpness', default_value='64'),
        DeclareLaunchArgument('backlight_compensation', default_value='64'),
        # UVC常用值：1=手动曝光，3=自动曝光；具体范围以v4l2-ctl输出为准。
        DeclareLaunchArgument('auto_exposure', default_value='1'),
        DeclareLaunchArgument('exposure_dynamic_framerate', default_value='0'),
        # Retain the focus position reported by this camera before autofocus is locked.
        DeclareLaunchArgument(
            'focus_automatic_continuous', default_value='0'),
        DeclareLaunchArgument('focus_absolute', default_value='359'),
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
        # 双目共用硬件时间戳，取两目Kalibr时偏的均值：t_imu=t_cam+0.0307304 s。
        DeclareLaunchArgument(
            'camera_time_offset_ms', default_value='30.730406888559322'),
    ]

    direct_camera_node = Node(
        package='stereo_v4l2_camera',
        executable='stereo_v4l2_direct_node',
        name='stereo_v4l2_direct_node',
        output='screen',
        parameters=[{
            # Each published eye is 640x480 mono8. Both eyes share one timestamp.
            'video_device': LaunchConfiguration('video_device'),
            'image_width': int_parameter('image_width'),
            'image_height': int_parameter('image_height'),
            'pixel_format': LaunchConfiguration('pixel_format'),
            'framerate': int_parameter('framerate'),
            'publish_framerate': int_parameter('publish_framerate'),
            # OpenVINS' ROS 2 stereo message_filters subscribers use reliable QoS.
            'qos_depth': int_parameter('qos_depth'),
            'reliable_qos': bool_parameter('reliable_qos'),
            'buffer_count': int_parameter('buffer_count'),
            'poll_timeout_ms': int_parameter('poll_timeout_ms'),
            'reconnect_delay_ms': int_parameter('reconnect_delay_ms'),
            'swap_left_right': bool_parameter('swap_left_right'),
            'apply_camera_controls': bool_parameter('apply_camera_controls'),
            # Fixed image processing prevents frame-to-frame feature appearance changes.
            'brightness': int_parameter('brightness'),
            'contrast': int_parameter('contrast'),
            'saturation': int_parameter('saturation'),
            'hue': int_parameter('hue'),
            'white_balance_automatic': bool_parameter(
                'white_balance_automatic'),
            'white_balance_temperature': int_parameter(
                'white_balance_temperature'),
            'gamma': int_parameter('gamma'),
            'gain': int_parameter('gain'),
            'power_line_frequency': int_parameter('power_line_frequency'),
            # Reduce sharpening halos and disable dynamic backlight compensation.
            'sharpness': int_parameter('sharpness'),
            'backlight_compensation': int_parameter(
                'backlight_compensation'),
            # Manual, short exposure reduces motion blur and keeps the cadence fixed.
            'auto_exposure': int_parameter('auto_exposure'),
            'exposure_dynamic_framerate': int_parameter(
                'exposure_dynamic_framerate'),
            'exposure_time_absolute': int_parameter(
                'exposure_time_absolute'),
            # VIO requires fixed intrinsics, so continuous autofocus must stay off.
            'focus_automatic_continuous': int_parameter(
                'focus_automatic_continuous'),
            'focus_absolute': int_parameter('focus_absolute'),
            'left_frame_id': LaunchConfiguration('left_frame_id'),
            'right_frame_id': LaunchConfiguration('right_frame_id'),
            'left_camera_info_file': LaunchConfiguration(
                'left_camera_info_file'),
            'right_camera_info_file': LaunchConfiguration(
                'right_camera_info_file'),
            'camera_time_offset_ms': float_parameter(
                'camera_time_offset_ms'),
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

    # 相机节点只发布带frame_id的数据；标定后的imu_link到cam0/cam1由建图launch统一发布。
    return LaunchDescription(arguments + [direct_camera_node])
