import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def int_parameter(name):
    """把启动参数显式转换为整数类型的 ROS 参数."""
    return ParameterValue(LaunchConfiguration(name), value_type=int)


def bool_parameter(name):
    """把启动参数显式转换为布尔类型的 ROS 参数."""
    return ParameterValue(LaunchConfiguration(name), value_type=bool)


def float_parameter(name):
    """把启动参数显式转换为浮点类型的 ROS 参数."""
    return ParameterValue(LaunchConfiguration(name), value_type=float)


def generate_launch_description():
    """以 YUYV 15 FPS 和相机固件自动曝光启动 OpenVINS USB 双目相机."""
    config_dir = os.path.join(
        get_package_share_directory('stereo_v4l2_camera'), 'config')
    arguments = [
        # 使用 by-id 路径，避免设备重插后 /dev/videoX 编号发生变化。
        DeclareLaunchArgument(
            'video_device',
            default_value=(
                '/dev/v4l/by-id/'
                'usb-USB_Camera_USB_Camera_01.00.00-video-index0'
            ),
        ),
        DeclareLaunchArgument('pixel_format', default_value='YUYV'),
        DeclareLaunchArgument('image_width', default_value='1280'),
        DeclareLaunchArgument('image_height', default_value='480'),
        DeclareLaunchArgument('framerate', default_value='15'),
        # 0 表示发布全部原生帧，不在 ROS 节点内进行二次限频。
        DeclareLaunchArgument('publish_framerate', default_value='0'),
        DeclareLaunchArgument('qos_depth', default_value='4'),
        DeclareLaunchArgument('reliable_qos', default_value='false'),
        DeclareLaunchArgument('buffer_count', default_value='4'),
        DeclareLaunchArgument('poll_timeout_ms', default_value='1000'),
        DeclareLaunchArgument('reconnect_delay_ms', default_value='1000'),
        # 新相机的双目拼接顺序按当前驱动默认设置进行交换。
        DeclareLaunchArgument('swap_left_right', default_value='true'),
        DeclareLaunchArgument('apply_camera_controls', default_value='true'),
        # 与 usb_v4l2.launch.py 的实测控制值保持一致。
        DeclareLaunchArgument('brightness', default_value='0'),
        DeclareLaunchArgument('contrast', default_value='0'),
        DeclareLaunchArgument('saturation', default_value='38'),
        DeclareLaunchArgument('hue', default_value='0'),
        DeclareLaunchArgument(
            'white_balance_automatic', default_value='false'),
        DeclareLaunchArgument('gamma', default_value='150'),
        DeclareLaunchArgument('gain', default_value='50'),
        # 1 表示 50 Hz 工频滤波，适合国内电网环境。
        DeclareLaunchArgument('power_line_frequency', default_value='1'),
        DeclareLaunchArgument('sharpness', default_value='0'),
        # 背光补偿 48 是 usb_v4l2 画面正常且稳定的关键固件默认值。
        DeclareLaunchArgument('backlight_compensation', default_value='50'),
        # 3 为 Aperture Priority，由相机固件负责自动曝光。
        DeclareLaunchArgument('auto_exposure', default_value='3'),
        DeclareLaunchArgument('exposure_time_absolute', default_value='156'),
        # 关闭 ROS 节点的软件闭环，避免与固件自动曝光互相抢占控制权。
        DeclareLaunchArgument('software_auto_exposure', default_value='false'),
        # 以下参数仅在手动覆盖 software_auto_exposure:=true 时生效。
        DeclareLaunchArgument(
            'software_auto_exposure_target', default_value='105'),
        DeclareLaunchArgument(
            'software_auto_exposure_min', default_value='10'),
        DeclareLaunchArgument(
            'software_auto_exposure_max', default_value='0'),
        DeclareLaunchArgument(
            'software_auto_exposure_deadband', default_value='15'),
        DeclareLaunchArgument(
            'software_auto_exposure_update_interval', default_value='30'),
        DeclareLaunchArgument(
            'software_auto_exposure_response', default_value='0.1'),
        DeclareLaunchArgument('left_image_topic', default_value='/cam0/image_raw'),
        DeclareLaunchArgument('right_image_topic', default_value='/cam1/image_raw'),
        DeclareLaunchArgument('left_info_topic', default_value='/cam0/camera_info'),
        DeclareLaunchArgument('right_info_topic', default_value='/cam1/camera_info'),
        DeclareLaunchArgument('left_frame_id', default_value='cam0'),
        DeclareLaunchArgument('right_frame_id', default_value='cam1'),
        DeclareLaunchArgument(
            'left_camera_info_file',
            default_value=os.path.join(config_dir, 'left_hb.yaml')),
        DeclareLaunchArgument(
            'right_camera_info_file',
            default_value=os.path.join(config_dir, 'right_hb.yaml')),
        # 暂时沿用模板中的 Kalibr 时偏，可在新相机完成联合标定后覆盖。
        DeclareLaunchArgument(
            'camera_time_offset_ms', default_value='0.0'),
    ]

    direct_camera_node = Node(
        package='stereo_v4l2_camera',
        executable='stereo_v4l2_direct_node',
        name='stereo_v4l2_direct_node',
        output='screen',
        parameters=[{
            # 1280x400 拼接帧拆分后，每目输出一张 640x400 mono8 图像。
            'video_device': LaunchConfiguration('video_device'),
            'image_width': int_parameter('image_width'),
            'image_height': int_parameter('image_height'),
            'pixel_format': LaunchConfiguration('pixel_format'),
            'framerate': int_parameter('framerate'),
            'publish_framerate': int_parameter('publish_framerate'),
            # OpenVINS 双目同步订阅使用可靠 QoS，左右目必须保持一致。
            'qos_depth': int_parameter('qos_depth'),
            'reliable_qos': bool_parameter('reliable_qos'),
            'buffer_count': int_parameter('buffer_count'),
            'poll_timeout_ms': int_parameter('poll_timeout_ms'),
            'reconnect_delay_ms': int_parameter('reconnect_delay_ms'),
            'swap_left_right': bool_parameter('swap_left_right'),
            'apply_camera_controls': bool_parameter('apply_camera_controls'),
            'brightness': int_parameter('brightness'),
            'contrast': int_parameter('contrast'),
            'saturation': int_parameter('saturation'),
            'hue': int_parameter('hue'),
            'white_balance_automatic': bool_parameter(
                'white_balance_automatic'),
            'gamma': int_parameter('gamma'),
            'gain': int_parameter('gain'),
            'power_line_frequency': int_parameter('power_line_frequency'),
            'sharpness': int_parameter('sharpness'),
            'backlight_compensation': int_parameter(
                'backlight_compensation'),
            'auto_exposure': int_parameter('auto_exposure'),
            'exposure_time_absolute': int_parameter(
                'exposure_time_absolute'),
            'software_auto_exposure': bool_parameter(
                'software_auto_exposure'),
            'software_auto_exposure_target': int_parameter(
                'software_auto_exposure_target'),
            'software_auto_exposure_min': int_parameter(
                'software_auto_exposure_min'),
            'software_auto_exposure_max': int_parameter(
                'software_auto_exposure_max'),
            'software_auto_exposure_deadband': int_parameter(
                'software_auto_exposure_deadband'),
            'software_auto_exposure_update_interval': int_parameter(
                'software_auto_exposure_update_interval'),
            'software_auto_exposure_response': float_parameter(
                'software_auto_exposure_response'),
            # 自动白平衡下不写温度；其余控件为新相机不支持项。
            'disabled_camera_controls': [
                'exposure_dynamic_framerate',
                'white_balance_temperature',
                'focus_automatic_continuous',
                'focus_absolute',
            ],
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

    # 相机启动文件只发布图像和 CameraInfo，外参由 OpenVINS/建图启动文件统一发布。
    return LaunchDescription(arguments + [direct_camera_node])
