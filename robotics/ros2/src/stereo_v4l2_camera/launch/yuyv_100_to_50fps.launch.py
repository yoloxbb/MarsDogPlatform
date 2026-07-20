from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Capture the 1280x480 YUYV stereo camera at 100 Hz and publish at 50 Hz."""
    arguments = [
        DeclareLaunchArgument('video_device', default_value='/dev/video2'),
        DeclareLaunchArgument('buffer_count', default_value='4'),
        DeclareLaunchArgument('poll_timeout_ms', default_value='1000'),
        DeclareLaunchArgument('reconnect_delay_ms', default_value='1000'),
        DeclareLaunchArgument('swap_left_right', default_value='true'),
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
            'image_width': 1280,
            'image_height': 480,
            'pixel_format': 'YUYV',
            # The device advertises only the discrete 100 fps YUYV mode.
            'framerate': 100,
            # Publishing is paced by a steady-clock timer inside the capture node.
            'publish_framerate': 50,
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
