import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """启动双目 SLAM、EKF、可视化和可选 Nav2 历史流程。"""

    base_frame = LaunchConfiguration('base_frame')
    use_viz = LaunchConfiguration('use_viz')
    ekf_config_file = LaunchConfiguration('ekf_config')
    localization = LaunchConfiguration('localization')
    use_nav2 = LaunchConfiguration('use_nav2')
    rviz = LaunchConfiguration('rviz')
    rviz_cfg = LaunchConfiguration('rviz_cfg')
    database_path = LaunchConfiguration('database_path')
    nav2_params_file = LaunchConfiguration('nav2_params')

    rtabmap_odom_params = {
            'frame_id': base_frame,
	    # stereo mode
	    'subscribe_rgbd': False,
	    'subscribe_stereo': True,
	    'subscribe_odom_info': True,
	    'use_sim_time': False,
	    'approx_sync': True,
	    'approx_sync_max_interval': 0.005,
	    'sync_queue_size': 5,
	    'wait_for_transform': 0.2,
	    'tf_delay': 0.2,
	    'Rtabmap/ImagesAlreadyRectified': 'true',
	    'Odom/Strategy': '0', 
            'Odom/GuessMotion':'true',
	    'Vis/EstimationType': '1', 
	    'Vis/MinInliers': '12',
	    'Vis/MaxFeatures': '1200',
	    'OdomF2M/MaxSize': '1000',
	    'GFTT/MinDistance': '5',
	    'GFTT/QualityLevel': '0.00001',
	    'Stereo/MaxDisparity':'128',
	    'odom/ResetCountdown': '5',
    }

    rtabmap_slam_params = {
            'frame_id': base_frame,
	    'subscribe_rgbd': False,
	    'subscribe_stereo': True,
	    'subscribe_odom_info': True,
	    'use_sim_time': False,
	    'approx_sync': True,
	    'approx_sync_max_interval': 0.005,
	    'queue_size': 5,
	    'wait_for_transform': 0.2,
	    'tf_delay': 0.2,
	    'Rtabmap/ImagesAlreadyRectified': 'true',
	    'Rtabmap/DetectionRate': '1',
	    'Reg/Force3DoF': 'true',
	    'Kp/MaxFeatures': '1000',
	    'GFTT/MinDistance': '5',
	    'GFTT/QualityLevel': '0.00001',
	    'Stereo/MaxDisparity':'128',
	    'Grid/RangeMax':'4',
            'Grid/GroundIsObstacle':'false',
	    'Grid/CellSize':'0.05',
	    'Grid/RayTracing': 'true',
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

    pkg_nav2_bringup = get_package_share_directory('nav2_bringup')

    nav2_launch = PathJoinSubstitution(
        [pkg_nav2_bringup, 'launch', 'navigation_launch.py'])

    return LaunchDescription([

        DeclareLaunchArgument('base_frame', default_value='base_footprint'),
        DeclareLaunchArgument('use_viz', default_value='false'),

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
            'rviz',
            default_value='true',
            description='Launch RVIZ'
        ),
        DeclareLaunchArgument(
            'rviz_cfg',
            default_value=os.path.join(
                get_package_share_directory('stereo_slam_legacy_bringup'), 'config', 'rviz.rviz'),
            description='RViz configuration file path'
        ),
        DeclareLaunchArgument(
            'database_path',
            default_value='~/.ros/rtabmap.db',
            description='RTAB-Map database path (REQUIRED for localization mode)'
        ),
        DeclareLaunchArgument(
            'nav2_params',
            default_value=os.path.join(
                get_package_share_directory('stereo_slam_legacy_bringup'), 'config', 'nav.yaml'),
            description='Nav2 parameters file path (REQUIRED: create custom for your robot)'
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
            package='rtabmap_odom',
            executable='stereo_odometry',
            name='stereo_odometry',
            output='screen',
            parameters=[rtabmap_odom_params],
            remappings=odom_remaps
        ),

        Node(
            condition=UnlessCondition(localization),
            package='rtabmap_slam',
            executable='rtabmap',
            name='rtabmap',
            output='screen',
            parameters=[rtabmap_slam_params, {'database_path': database_path}],
            remappings=slam_remaps,
            arguments=['-d']
        ),

        Node(
            condition=IfCondition(localization),
            package='rtabmap_slam',
            executable='rtabmap',
            name='rtabmap',
            output='screen',
            parameters=[rtabmap_slam_params, rtabmap_localization_params, {'database_path': database_path}],
            remappings=slam_remaps,
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

        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            condition=IfCondition(rviz),
            arguments=[['-d'], [rviz_cfg]]
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([nav2_launch]),
            condition=IfCondition(use_nav2),
            launch_arguments=[
                ('use_sim_time', 'false'),
                ('params_file', nav2_params_file)
            ]
        ),


        Node(
            package='rtabmap_util',
            executable='obstacles_detection',
            name='obstacles_detection',
            output='screen',
            parameters=[rtabmap_slam_params],
            remappings=[
                ('cloud', '/stereo/points'),
                ('obstacles', '/stereo/obstacles'),
                ('ground', '/stereo/ground')
            ]
        ),
    ])
