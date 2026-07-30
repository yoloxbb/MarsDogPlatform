from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """启动V4L2直采双目节点及对应静态TF."""
    arguments = [
        DeclareLaunchArgument(
            'video_device',
            default_value=(
                '/dev/v4l/by-id/'
                'usb-USB_Camera_USB_Camera_01.00.00-video-index0'
            ),
        ),
        DeclareLaunchArgument('image_width', default_value='1280'),
        DeclareLaunchArgument('image_height', default_value='480'),
        DeclareLaunchArgument('pixel_format', default_value='MJPEG'),
        DeclareLaunchArgument('framerate', default_value='60'),
        DeclareLaunchArgument('buffer_count', default_value='4'),
        DeclareLaunchArgument('poll_timeout_ms', default_value='1000'),
        DeclareLaunchArgument('reconnect_delay_ms', default_value='1000'),
        DeclareLaunchArgument('swap_left_right', default_value='true'),
        DeclareLaunchArgument('apply_camera_controls', default_value='true'),
        DeclareLaunchArgument('brightness', default_value='0'),
        DeclareLaunchArgument('contrast', default_value='0'),
        DeclareLaunchArgument('saturation', default_value='56'),
        DeclareLaunchArgument('hue', default_value='0'),
        DeclareLaunchArgument('white_balance_automatic', default_value='false'),
        DeclareLaunchArgument('white_balance_temperature', default_value='4600'),
        DeclareLaunchArgument('gamma', default_value='150'),
        DeclareLaunchArgument('gain', default_value='200'),
        DeclareLaunchArgument('power_line_frequency', default_value='1'),
        DeclareLaunchArgument('sharpness', default_value='0'),
        DeclareLaunchArgument('backlight_compensation', default_value='0'),
        DeclareLaunchArgument('auto_exposure', default_value='1'),
        DeclareLaunchArgument('exposure_time_absolute', default_value='150'),
        DeclareLaunchArgument('left_frame_id', default_value='camera_left_frame'),
        DeclareLaunchArgument('right_frame_id', default_value='camera_right_frame'),
    ]

    direct_camera_node = Node(
        package='stereo_v4l2_camera',
        executable='stereo_v4l2_direct_node',
        name='stereo_v4l2_direct_node',
        output='screen',
        parameters=[{
            'video_device': LaunchConfiguration('video_device'),
            'image_width': ParameterValue(
                LaunchConfiguration('image_width'), value_type=int),
            'image_height': ParameterValue(
                LaunchConfiguration('image_height'), value_type=int),
            'pixel_format': LaunchConfiguration('pixel_format'),
            'framerate': ParameterValue(
                LaunchConfiguration('framerate'), value_type=int),
            'buffer_count': ParameterValue(
                LaunchConfiguration('buffer_count'), value_type=int),
            'poll_timeout_ms': ParameterValue(
                LaunchConfiguration('poll_timeout_ms'), value_type=int),
            'reconnect_delay_ms': ParameterValue(
                LaunchConfiguration('reconnect_delay_ms'), value_type=int),
            'swap_left_right': ParameterValue(
                LaunchConfiguration('swap_left_right'), value_type=bool),
            'apply_camera_controls': ParameterValue(
                LaunchConfiguration('apply_camera_controls'), value_type=bool),
            'brightness': ParameterValue(
                LaunchConfiguration('brightness'), value_type=int),
            'contrast': ParameterValue(
                LaunchConfiguration('contrast'), value_type=int),
            'saturation': ParameterValue(
                LaunchConfiguration('saturation'), value_type=int),
            'hue': ParameterValue(
                LaunchConfiguration('hue'), value_type=int),
            'white_balance_automatic': ParameterValue(
                LaunchConfiguration('white_balance_automatic'), value_type=bool),
            'white_balance_temperature': ParameterValue(
                LaunchConfiguration('white_balance_temperature'), value_type=int),
            'gamma': ParameterValue(
                LaunchConfiguration('gamma'), value_type=int),
            'gain': ParameterValue(
                LaunchConfiguration('gain'), value_type=int),
            'power_line_frequency': ParameterValue(
                LaunchConfiguration('power_line_frequency'), value_type=int),
            'sharpness': ParameterValue(
                LaunchConfiguration('sharpness'), value_type=int),
            'backlight_compensation': ParameterValue(
                LaunchConfiguration('backlight_compensation'), value_type=int),
            'auto_exposure': ParameterValue(
                LaunchConfiguration('auto_exposure'), value_type=int),
            'exposure_time_absolute': ParameterValue(
                LaunchConfiguration('exposure_time_absolute'), value_type=int),
            'left_frame_id': LaunchConfiguration('left_frame_id'),
            'right_frame_id': LaunchConfiguration('right_frame_id'),
        }],
    )

    tf_cam_link_left = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='tf_cam_link_left',
        arguments=[
            '0.01', '0.025', '0.087', '0', '0', '0', '1',
            'camera_link', 'left_camera'],
    )
    tf_cam_link_right = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='tf_cam_link_right',
        arguments=[
            '0.01', '-0.025', '0.087', '0', '0', '0', '1',
            'camera_link', 'right_camera'],
    )
    tf_left_optical = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='tf_left_optical',
        arguments=[
            '0', '0', '0', '-1.570796', '0', '-1.570796',
            'left_camera', 'camera_left_frame'],
    )
    tf_right_optical = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='tf_right_optical',
        arguments=[
            '0', '0', '0', '-1.570796', '0', '-1.570796',
            'right_camera', 'camera_right_frame'],
    )

    return LaunchDescription(arguments + [
        tf_cam_link_left,
        tf_cam_link_right,
        tf_left_optical,
        tf_right_optical,
        direct_camera_node,
    ])
