"""启动可完整配置的原生 V4L2 拼接双目相机驱动."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _as_bool(value):
    """把 launch 字符串转换为布尔值."""
    return str(value).lower() in ('true', '1', 'yes', 'on')


def _split_names(value):
    """把逗号分隔的控件名称转换为 ROS 字符串数组."""
    names = [name.strip() for name in value.split(',') if name.strip()]
    # ROS 2 参数文件无法推断空数组类型，用无匹配占位符表达“不禁用控件”。
    return names or ['none']


def _launch_setup(context, *args, **kwargs):
    """解析全部启动参数并创建唯一的相机节点."""
    def value(name):
        """读取当前 launch 上下文中的单个参数值."""
        return LaunchConfiguration(name).perform(context)

    parameters = {
        'video_device': value('video_device'),
        'image_width': int(value('image_width')),
        'image_height': int(value('image_height')),
        'pixel_format': value('pixel_format'),
        'framerate': int(value('framerate')),
        'publish_framerate': int(value('publish_framerate')),
        'qos_depth': int(value('qos_depth')),
        'reliable_qos': _as_bool(value('reliable_qos')),
        'buffer_count': int(value('buffer_count')),
        'poll_timeout_ms': int(value('poll_timeout_ms')),
        'reconnect_delay_ms': int(value('reconnect_delay_ms')),
        'swap_left_right': _as_bool(value('swap_left_right')),
        'apply_camera_controls': _as_bool(value('apply_camera_controls')),
        'brightness': int(value('brightness')),
        'contrast': int(value('contrast')),
        'saturation': int(value('saturation')),
        'hue': int(value('hue')),
        'white_balance_automatic': _as_bool(value('white_balance_automatic')),
        'white_balance_temperature': int(value('white_balance_temperature')),
        'gamma': int(value('gamma')),
        'gain': int(value('gain')),
        'power_line_frequency': int(value('power_line_frequency')),
        'sharpness': int(value('sharpness')),
        'backlight_compensation': int(value('backlight_compensation')),
        'auto_exposure': int(value('auto_exposure')),
        'exposure_time_absolute': int(value('exposure_time_absolute')),
        'software_auto_exposure': _as_bool(value('software_auto_exposure')),
        'software_auto_exposure_target': int(value('software_auto_exposure_target')),
        'software_auto_exposure_min': int(value('software_auto_exposure_min')),
        'software_auto_exposure_max': int(value('software_auto_exposure_max')),
        'software_auto_exposure_deadband': int(value('software_auto_exposure_deadband')),
        'software_auto_exposure_update_interval': int(
            value('software_auto_exposure_update_interval')),
        'software_auto_exposure_response': float(value('software_auto_exposure_response')),
        'exposure_dynamic_framerate': int(value('exposure_dynamic_framerate')),
        'focus_automatic_continuous': int(value('focus_automatic_continuous')),
        'focus_absolute': int(value('focus_absolute')),
        'disabled_camera_controls': _split_names(value('disabled_camera_controls')),
        'left_frame_id': value('left_frame_id'),
        'right_frame_id': value('right_frame_id'),
        'left_camera_info_file': value('left_camera_info_file'),
        'right_camera_info_file': value('right_camera_info_file'),
        'camera_time_offset_ms': float(value('camera_time_offset_ms')),
        'use_sim_time': _as_bool(value('use_sim_time')),
    }

    # 驱动内部使用固定源话题，通过 remap 保留完整的话题配置能力。
    remappings = [
        ('/cam0/image_raw', value('left_image_topic')),
        ('/cam1/image_raw', value('right_image_topic')),
        ('/cam0/camera_info', value('left_info_topic')),
        ('/cam1/camera_info', value('right_info_topic')),
    ]
    return [Node(
        package='stereo_v4l2_camera',
        executable='stereo_v4l2_direct_node',
        name='stereo_v4l2_direct_node',
        output='screen',
        parameters=[parameters],
        remappings=remappings,
    )]


def generate_launch_description():
    """声明通用参数；默认值针对 HB 双目低算力稳定运行."""
    arguments = [
        DeclareLaunchArgument(
            'video_device',
            default_value=(
                '/dev/v4l/by-id/'
                'usb-USB_Camera_USB_Camera_01.00.00-video-index0'),
            description='V4L2 设备路径，推荐使用稳定的 /dev/v4l/by-id 路径。'),
        DeclareLaunchArgument('image_width', default_value='1280'),
        DeclareLaunchArgument('image_height', default_value='480'),
        DeclareLaunchArgument(
            'pixel_format', default_value='YUYV',
            description='支持 YUYV 或 MJPEG；YUYV 的 CPU 开销更低。'),
        DeclareLaunchArgument('framerate', default_value='15'),
        DeclareLaunchArgument(
            'publish_framerate', default_value='0',
            description='0 发布全部帧；大于 0 时按指定频率发布最新帧。'),
        DeclareLaunchArgument('qos_depth', default_value='4'),
        DeclareLaunchArgument('reliable_qos', default_value='false'),
        DeclareLaunchArgument('buffer_count', default_value='4'),
        DeclareLaunchArgument('poll_timeout_ms', default_value='1000'),
        DeclareLaunchArgument('reconnect_delay_ms', default_value='1000'),
        DeclareLaunchArgument('swap_left_right', default_value='true'),
        DeclareLaunchArgument('apply_camera_controls', default_value='true'),
        DeclareLaunchArgument('brightness', default_value='0'),
        DeclareLaunchArgument('contrast', default_value='0'),
        DeclareLaunchArgument('saturation', default_value='38'),
        DeclareLaunchArgument('hue', default_value='0'),
        DeclareLaunchArgument('white_balance_automatic', default_value='false'),
        DeclareLaunchArgument('white_balance_temperature', default_value='4600'),
        DeclareLaunchArgument('gamma', default_value='150'),
        DeclareLaunchArgument('gain', default_value='50'),
        DeclareLaunchArgument('power_line_frequency', default_value='1'),
        DeclareLaunchArgument('sharpness', default_value='0'),
        DeclareLaunchArgument('backlight_compensation', default_value='50'),
        DeclareLaunchArgument(
            'auto_exposure', default_value='3',
            description='常见 UVC 值：1 为手动曝光，3 为光圈优先自动曝光。'),
        DeclareLaunchArgument('exposure_time_absolute', default_value='156'),
        DeclareLaunchArgument('software_auto_exposure', default_value='false'),
        DeclareLaunchArgument('software_auto_exposure_target', default_value='105'),
        DeclareLaunchArgument('software_auto_exposure_min', default_value='10'),
        DeclareLaunchArgument('software_auto_exposure_max', default_value='0'),
        DeclareLaunchArgument('software_auto_exposure_deadband', default_value='15'),
        DeclareLaunchArgument(
            'software_auto_exposure_update_interval', default_value='30'),
        DeclareLaunchArgument('software_auto_exposure_response', default_value='0.1'),
        DeclareLaunchArgument('exposure_dynamic_framerate', default_value='-1'),
        DeclareLaunchArgument('focus_automatic_continuous', default_value='-1'),
        DeclareLaunchArgument('focus_absolute', default_value='-1'),
        DeclareLaunchArgument(
            'disabled_camera_controls',
            default_value=(
                'exposure_dynamic_framerate,white_balance_temperature,'
                'focus_automatic_continuous,focus_absolute'),
            description='当前相机不支持或不应写入的 V4L2 控件，使用逗号分隔。'),
        DeclareLaunchArgument('left_image_topic', default_value='/cam0/image_raw'),
        DeclareLaunchArgument('right_image_topic', default_value='/cam1/image_raw'),
        DeclareLaunchArgument('left_info_topic', default_value='/cam0/camera_info'),
        DeclareLaunchArgument('right_info_topic', default_value='/cam1/camera_info'),
        DeclareLaunchArgument('left_frame_id', default_value='cam0'),
        DeclareLaunchArgument('right_frame_id', default_value='cam1'),
        DeclareLaunchArgument(
            'left_camera_info_file', default_value='',
            description='可选的外部左目 CameraInfo YAML；空值表示未标定。'),
        DeclareLaunchArgument(
            'right_camera_info_file', default_value='',
            description='可选的外部右目 CameraInfo YAML；空值表示未标定。'),
        DeclareLaunchArgument(
            'camera_time_offset_ms', default_value='0.0',
            description='加到相机时间戳上的 Kalibr 时偏，单位为毫秒。'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
    ]
    return LaunchDescription(arguments + [OpaqueFunction(function=_launch_setup)])
