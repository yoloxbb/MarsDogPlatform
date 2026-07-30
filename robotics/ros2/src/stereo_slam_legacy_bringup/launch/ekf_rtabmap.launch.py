from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    """组合双目里程计、EKF、RTAB-Map 和可选可视化节点。"""
    package_share = get_package_share_directory('stereo_slam_legacy_bringup')
    base_frame = LaunchConfiguration('base_frame')
    use_viz = LaunchConfiguration('use_viz')
    ekf_config_file = LaunchConfiguration('ekf_config')

    rtabmap_odom_params = {
        'frame_id': base_frame,
        'subscribe_rgbd': False,
        'subscribe_stereo': True,
        'subscribe_odom_info': False,
        'use_sim_time': False,
        'approx_sync': True,
        'approx_sync_max_interval': 0.1,
        'sync_queue_size': 10,
        'topic_queue_size': 10,
        'wait_for_transform': 0.5,
        'tf_delay': 0.05,
        'Rtabmap/ImagesAlreadyRectified': 'true',
        'publish_tf': False,
        'guess_frame_id': '',
        'Odom/GuessMotion': False,
        'Vis/FeatureType': '8',
        'Vis/EstimationType': '1',
        'Vis/MinInliers': '12',
        'Vis/MaxFeatures': '1000',
        'Vis/CorType': '0',
        'Odom/ResetCountdown': '5',
        'Odom/Strategy': '0',
        'OdomF2M/MaxSize': '1000',
        'GFTT/MinDistance': '10',
        'GFTT/QualityLevel': '0.00001',
        'Stereo/MaxDisparity': '128',
        'odom_frame_id': 'odom',
    }

    rtabmap_slam_params = {
        'frame_id': base_frame,
        'subscribe_rgbd': False,
        'subscribe_stereo': True,
        'subscribe_odom_info': False,
        'subscribe_odom': False,
        'odom_frame_id': 'odom',
        'use_sim_time': False,
        'approx_sync': True,
        'approx_sync_max_interval': 0.1,
        'sync_queue_size': 10,
        'topic_queue_size': 10,
        'wait_for_transform': 0.5,
        'tf_delay': 0.05,
        'Rtabmap/ImagesAlreadyRectified': 'true',
        'Rtabmap/DetectionRate': '1',
        'Reg/Force3DoF': 'true',
        'Kp/MaxFeatures': '1000',
        'Kp/NndrRatio': '0.75',
        'GFTT/MinDistance': '10',
        'GFTT/QualityLevel': '0.00001',
        'GFTT/MaxCorners': '500',
        'Stereo/MaxDisparity': '128',
        'Grid/RayTracing': 'true',
        'Grid/RangeMax': '3.5',
        'Grid/MaxObstacleHeight': '0.5',
    }

    odom_remaps = [
        ('left/image_rect', '/stereo/left/camera/image_rect'),
        ('right/image_rect', '/stereo/right/camera/image_rect'),
        ('left/camera_info', '/stereo/left/camera/camera_info'),
        ('right/camera_info', '/stereo/right/camera/camera_info'),
        ('odom', '/vo'),
    ]

    slam_remaps = [
        ('left/image_rect', '/stereo/left/camera/image_rect'),
        ('right/image_rect', '/stereo/right/camera/image_rect'),
        ('left/camera_info', '/stereo/left/camera/camera_info'),
        ('right/camera_info', '/stereo/right/camera/camera_info'),
    ]

    return LaunchDescription([
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        DeclareLaunchArgument('use_viz', default_value='true'),
        DeclareLaunchArgument(
            'ekf_config',
            default_value=os.path.join(package_share, 'config', 'ekf_stereo_wheel.yaml')
        ),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_cam_link_left',
            arguments=['0', '0.025', '0', '0', '0', '0', '1', 'camera_link', 'left_camera']
        ),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_cam_link_right',
            arguments=['0', '-0.025', '0', '0', '0', '0', '1', 'camera_link', 'right_camera']
        ),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_left_optical',
            arguments=['0', '0', '0', '-1.570796', '0', '-1.570796',
                       'left_camera', 'camera_left_frame']
        ),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_right_optical',
            arguments=['0', '0', '0', '-1.570796', '0', '-1.570796',
                       'right_camera', 'camera_right_frame']
        ),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_base_to_camera',
            arguments=['-0.05', '0.3', '0.2', '0', '0', '0',
                       'base_link', 'camera_link']
        ),

        Node(
            package='image_proc',
            executable='rectify_node',
            name='rectify_left',
            namespace='/stereo/left/camera',
            remappings=[
                ('image', '/stereo/left/camera/image_mono'),
                ('camera_info', '/stereo/left/camera/camera_info'),
                ('image_rect', '/stereo/left/camera/image_rect')
            ]
        ),

        Node(
            package='image_proc',
            executable='rectify_node',
            name='rectify_right',
            namespace='/stereo/right/camera',
            remappings=[
                ('image', '/stereo/right/camera/image_mono'),
                ('camera_info', '/stereo/right/camera/camera_info'),
                ('image_rect', '/stereo/right/camera/image_rect')
            ]
        ),

        Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_filter_node',
            output='screen',
            parameters=[ekf_config_file],
        ),

        Node(
            package='rtabmap_odom',
            executable='stereo_odometry',
            name='stereo_odometry',
            output='screen',
            parameters=[rtabmap_odom_params],
            remappings=odom_remaps
        ),

        Node(
            package='rtabmap_slam',
            executable='rtabmap',
            name='rtabmap',
            output='screen',
            parameters=[rtabmap_slam_params],
            remappings=slam_remaps,
            arguments=['-d']
        ),

        Node(
            package='rtabmap_viz',
            executable='rtabmap_viz',
            name='rtabmap_viz',
            output='screen',
            condition=IfCondition(use_viz),
            parameters=[rtabmap_slam_params],
            remappings=slam_remaps
        ),
    ])
