import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from nav2_common.launch import ReplaceString


def generate_launch_description():
    """启动带地面分割优化的双目 RTAB-Map 与可选 Nav2。"""

    base_frame = LaunchConfiguration('base_frame')
    use_viz = LaunchConfiguration('use_viz')
    localization = LaunchConfiguration('localization')
    use_nav2 = LaunchConfiguration('use_nav2')
    database_path = LaunchConfiguration('database_path')
    nav2_params_file = LaunchConfiguration('nav2_params')

    # 版本说明：RTAB-Map 地面/障碍分割优化版。
    # 基于用户提供的 stereo + RTAB-Map + Nav2 启动文件新建，不覆盖原文件。
    # 主要意图：
    # 1. 在 RTAB-Map 侧先做 ground / obstacle 分割，减少反光地面误进 Nav2 obstacle layer。
    # 2. 增加 occupancy grid 聚类和离群点过滤，让 /local_grid_obstacle 更干净。
    # 3. 修正右相机 rectify_node 的 QoS override 路径，避免仍写成 left camera。
    # 4. 保留原来的 stereo odometry、SLAM/localization、Nav2 启动结构。
    rtabmap_odom_params = {
        'frame_id': base_frame,
        'subscribe_rgbd': False,
        'subscribe_stereo': True,
        'subscribe_odom_info': True,
        'use_sim_time': False,
        'approx_sync': True,
        'approx_sync_max_interval': 0.01,
        'sync_queue_size': 10,
        'topic_queue_size': 5,
        'wait_for_transform': 0.5,
        'Rtabmap/ImagesAlreadyRectified': 'true',
        'publish_tf': True,
        'Vis/FeatureType': '8',
        'Vis/EstimationType': '1',
        'Vis/MinInliers': '12',
        'Vis/MaxFeatures': '1000',
        'Vis/CorType': '0',
        'Odom/ResetCountdown': '1',
        'Odom/Strategy': '0',
        'OdomF2M/MaxSize': '1000',
        'GFTT/MinDistance': '5',
        'GFTT/QualityLevel': '0.001',
        'Stereo/MaxDisparity': '256',
        'wait_imu_to_init': False,
        'qos': 2,
        'qos_image':2,
        'qos_camera_info':2,
    }

    rtabmap_grid_filter_params = {
        'Grid/3D': 'false',
        'Grid/RayTracing': 'true',
        'Grid/RangeMin': '0.02',
        'Grid/RangeMax': '4.0',
        'Grid/CellSize': '0.05',
        'Grid/NormalsSegmentation': 'true',
        'Grid/MaxGroundAngle': '25',
        'Grid/NormalK': '12',
        'Grid/ClusterRadius': '0.15',
        'Grid/MinClusterSize': '12',
        'Grid/FlatObstacleDetected': 'true',
        'Grid/GroundIsObstacle': 'false',
        'Grid/MinObstacleHeight': '0.05',
        'Grid/MaxObstacleHeight': '1.2',
        'Grid/NoiseFilteringRadius': '0.12',
        'Grid/NoiseFilteringMinNeighbors': '4',
        'Grid/MapFrameProjection': 'false',
        'RGBD/CreateOccupancyGrid': 'false',
        'Grid/FromDepth': 'false',
    }

    rtabmap_slam_params = {
        'frame_id': base_frame,
        'subscribe_rgbd': False,
        'subscribe_stereo': True,
        'subscribe_odom_info': True,
        'subscribe_odom': True,
      #  'odom_frame_id': 'odom',
        'use_sim_time': False,
        'approx_sync': True,
        'approx_sync_max_interval': 0.01,
        'sync_queue_size': 10,
        'topic_queue_size': 5,
        'wait_for_transform': 0.5,
        'tf_delay': 0.05,
        'Rtabmap/ImagesAlreadyRectified': 'true',
        'Rtabmap/DetectionRate': '1',
        'Reg/Force3DoF': 'false',
        'Kp/MaxFeatures': '1000',
        'Kp/NndrRatio': '0.75',
        'GFTT/MinDistance': '5',
        'GFTT/QualityLevel': '0.001',
        'GFTT/MaxCorners': '800',
        'Stereo/MaxDisparity': '256',
        'qos': 2,
        'qos_image':2,
        'qos_camera_info':2,
        **rtabmap_grid_filter_params,
    }

    rtabmap_localization_params = {
        'Mem/IncrementalMemory': 'False',
        'Mem/InitWMWithAllNodes': 'True',
        'RGBD/LocalizationSmoothing': 'true',
        'RGBD/LocalizationPriorError': '0.001',
        'RGBD/MaxOdomCacheSize': '10',
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
        ('odom', '/vo'),
    ]

    pkg_stereo_camera = get_package_share_directory('stereo_slam_legacy_bringup')
    pkg_nav2_bringup = get_package_share_directory('nav2_bringup')

    nav2_launch = PathJoinSubstitution(
        [pkg_nav2_bringup, 'launch', 'navigation_launch.py'])
    configured_nav2_params_file = ReplaceString(
        source_file=nav2_params_file,
        replacements={'STEREO_CAMERA_PKG_SHARE': pkg_stereo_camera}
    )

    return LaunchDescription([

        DeclareLaunchArgument('base_frame', default_value='camera_link'),
        DeclareLaunchArgument('use_viz', default_value='true'),

        DeclareLaunchArgument(
            'localization',
            default_value='false',
            description='Launch in localization mode'
        ),
        DeclareLaunchArgument(
            'use_nav2',
            default_value='false',
            description='Launch Nav2 navigation stack'
        ),

        DeclareLaunchArgument(
            'database_path',
            default_value='~/.ros/rtabmap.db',
            description='RTAB-Map database path (REQUIRED for localization mode)'
        ),
        DeclareLaunchArgument(
            'nav2_params',
            # 该兼容入口不再伪造一个不存在的默认文件；启用 Nav2 时必须显式传入。
            default_value='',
            description='Nav2 parameters file path (required when use_nav2 is true)'
        ),

         Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_cam_link_left',
            arguments=['0', '0', '0', '0', '0', '0', '1', 'camera_link', 'left_camera']
        ),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_cam_link_right',
            arguments=['0', '-0.05', '0', '0', '0', '0', '1', 'camera_link', 'right_camera']
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
            package='image_proc',
            executable='rectify_node',
            name='rectify_left',
            namespace='/stereo/left/camera',
            parameters=[{
                # 'qos_overrides./stereo/left/camera/image_mono.subscription.reliability':
                #     'best_effort',
                # 'qos_overrides./stereo/left/camera/camera_info.subscription.reliability':
                #     'best_effort',
                # 'qos_overrides./stereo/left/camera/image_rect.publisher.reliability':
                #     'best_effort',

                'qos_overrides./stereo/left/camera/image_mono.subscription.reliability': 'reliable',
                'qos_overrides./stereo/left/camera/camera_info.subscription.reliability': 'reliable',
                'qos_overrides./stereo/left/camera/image_rect.publisher.reliability': 'best_effort',
            }],
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
            parameters=[{
                # 'qos_overrides./stereo/right/camera/image_mono.subscription.reliability':
                #     'best_effort',
                # 'qos_overrides./stereo/right/camera/camera_info.subscription.reliability':
                #     'best_effort',
                # 'qos_overrides./stereo/right/camera/image_rect.publisher.reliability':
                #     'best_effort',

                'qos_overrides./stereo/right/camera/image_mono.subscription.reliability': 'reliable',
                'qos_overrides./stereo/right/camera/camera_info.subscription.reliability': 'reliable',
                'qos_overrides./stereo/right/camera/image_rect.publisher.reliability': 'best_effort',
            }],
            remappings=[
                ('image', '/stereo/right/camera/image_mono'),
                ('camera_info', '/stereo/right/camera/camera_info'),
                ('image_rect', '/stereo/right/camera/image_rect')
            ]
        ),
        

        Node(
            package='rtabmap_odom',
            executable='stereo_odometry',
            name='stereo_odometry',
            output='screen',
            parameters=[rtabmap_odom_params],
            remappings=odom_remaps,
            # arguments=['--ros-args', '--log-level', 'warn']
        ),

        Node(
            condition=UnlessCondition(localization),
            package='rtabmap_slam',
            executable='rtabmap',
            name='rtabmap',
            output='screen',
            parameters=[rtabmap_slam_params, {'database_path': database_path}],
            remappings=slam_remaps,
            arguments=['--ros-args', '--log-level', 'warn', '--', '-d']
        ),

        Node(
            condition=IfCondition(localization),
            package='rtabmap_slam',
            executable='rtabmap',
            name='rtabmap',
            output='screen',
            parameters=[
                rtabmap_slam_params,
                rtabmap_localization_params,
                {'database_path': database_path}
            ],
            remappings=slam_remaps,
            arguments=['--ros-args', '--log-level', 'warn']
        ),

        Node(
            package='rtabmap_viz',
            executable='rtabmap_viz',
            name='rtabmap_viz',
            output='screen',
            condition=IfCondition(use_viz),
            parameters=[rtabmap_slam_params],
            remappings=slam_remaps,
            arguments=['--ros-args', '--log-level', 'warn']
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([nav2_launch]),
            condition=IfCondition(use_nav2),
            launch_arguments=[
                ('use_sim_time', 'false'),
                ('params_file', configured_nav2_params_file)
            ]
        ),
    ])
