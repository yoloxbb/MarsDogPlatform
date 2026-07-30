# stereo_rtabmap.launch.py
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, Command
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

def generate_launch_description():
    """启动双路 V4L2 相机并接入 RTAB-Map 的历史流程。"""
    # 设置参数
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    left_camera_device = LaunchConfiguration('left_camera_device', default='/dev/video0')
    right_camera_device = LaunchConfiguration('right_camera_device', default='/dev/video2')
    resolution = LaunchConfiguration('resolution', default='640x480')
    framerate = LaunchConfiguration('framerate', default='30')
    
    # RTAB-Map 参数
    rtabmap_args = LaunchConfiguration('rtabmap_args', default='')
    delete_db_on_start = LaunchConfiguration('delete_db_on_start', default='false')
    
    # 标定文件路径
    calibration_dir = get_package_share_directory('stereo_sync')
    calibration_file = os.path.join(calibration_dir, 'config', 'stereo_calibration.yaml')
    
    return LaunchDescription([
        # 设置环境变量
        SetEnvironmentVariable('RCUTILS_CONSOLE_OUTPUT_FORMAT', '[{severity}]: {message}'),
        
        # 声明参数
        DeclareLaunchArgument(
            'use_sim_time',
            default_value=use_sim_time,
            description='Use simulation (Gazebo) clock if true'
        ),
        DeclareLaunchArgument(
            'left_camera_device',
            default_value=left_camera_device,
            description='Left camera device file'
        ),
        DeclareLaunchArgument(
            'right_camera_device',
            default_value=right_camera_device,
            description='Right camera device file'
        ),
        DeclareLaunchArgument(
            'resolution',
            default_value=resolution,
            description='Camera resolution (widthxheight)'
        ),
        DeclareLaunchArgument(
            'framerate',
            default_value=framerate,
            description='Camera framerate'
        ),
        DeclareLaunchArgument(
            'rtabmap_args',
            default_value=rtabmap_args,
            description='RTAB-Map additional arguments'
        ),
        DeclareLaunchArgument(
            'delete_db_on_start',
            default_value=delete_db_on_start,
            description='Delete database on startup'
        ),
        
        # 左相机节点
        Node(
            package='v4l2_camera',
            executable='v4l2_camera_node',
            name='left_camera',
            namespace='left_camera',
            parameters=[{
                'video_device': left_camera_device,
                'image_size': [640, 480],
                'time_per_frame': [1, 30],
                'camera_info_url': '',
                'camera_name': 'left_camera',
                'use_image_transport': True,
            }],
            remappings=[
                ('image_raw', 'image_raw'),
                ('camera_info', 'camera_info'),
            ],
            output='screen'
        ),
        
        # 右相机节点
        Node(
            package='v4l2_camera',
            executable='v4l2_camera_node',
            name='right_camera',
            namespace='right_camera',
            parameters=[{
                'video_device': right_camera_device,
                'image_size': [640, 480],
                'time_per_frame': [1, 30],
                'camera_info_url': '',
                'camera_name': 'right_camera',
                'use_image_transport': True,
            }],
            remappings=[
                ('image_raw', 'image_raw'),
                ('camera_info', 'camera_info'),
            ],
            output='screen'
        ),
        
        # 时间同步节点
        Node(
            package='stereo_sync',
            executable='stereo_sync_node',
            name='stereo_sync',
            parameters=[{
                'queue_size': 10,
                'time_tolerance': 0.033,
                'left_camera_name': 'left_camera',
                'right_camera_name': 'right_camera',
            }],
            output='screen',
            emulate_tty=True
        ),
        
        # 图像校正节点 (stereo_image_proc)
        Node(
            package='stereo_image_proc',
            executable='stereo_image_proc',
            name='stereo_image_proc',
            namespace='stereo',
            parameters=[{
                'approximate_sync': True,
                'queue_size': 10,
                'stereo_algorithm': 'StereoBM',
                'prefilter_size': 9,
                'prefilter_cap': 31,
                'correlation_window_size': 15,
                'min_disparity': 0,
                'disparity_range': 64,
                'uniqueness_ratio': 15,
                'texture_threshold': 10,
                'speckle_size': 100,
                'speckle_range': 4,
            }],
            remappings=[
                ('left/image_raw', '/stereo/left/image_raw'),
                ('left/camera_info', '/stereo/left/camera_info'),
                ('right/image_raw', '/stereo/right/image_raw'),
                ('right/camera_info', '/stereo/right/camera_info'),
                ('left/image_rect', 'left/image_rect'),
                ('right/image_rect', 'right/image_rect'),
                ('left/image_rect_color', 'left/image_rect_color'),
                ('right/image_rect_color', 'right/image_rect_color'),
                ('disparity', 'disparity'),
            ],
            output='screen'
        ),
        
        # RTAB-Map 节点
        Node(
            package='rtabmap_ros',
            executable='rtabmap',
            name='rtabmap',
            parameters=[{
                'subscribe_stereo': True,
                'frame_id': 'base_link',
                'odom_frame_id': 'odom',
                'map_frame_id': 'map',
                
                # 相机参数
                'Stereo/MaxDisparity': 64.0,
                'Stereo/MinDisparity': 0.0,
                'Stereo/BM/UniqueRatio': 10.0,
                'Stereo/BM/TextureThreshold': 10.0,
                'Stereo/BM/SpeckleWindowSize': 100,
                'Stereo/BM/SpeckleRange': 4,
                
                # 视觉里程计参数
                'Odom/Strategy': 0,  # 0=Frame-to-Map, 1=Frame-to-Frame
                'Vis/MaxFeatures': 600,
                'Vis/MinInliers': 20,
                'Vis/CorGuessWinSize': 20,
                'Vis/CorNNDR': 0.6,
                'Vis/CorNNType': 6,
                
                # 内存管理
                'Mem/RehearsalSimilarity': 0.45,
                'Mem/BadSignaturesIgnored': True,
                'Mem/STMSize': 30,
                'Mem/NotLinkedNodesKept': False,
                'RGBD/ProximityBySpace': True,
                'RGBD/AngularUpdate': 0.1,
                'RGBD/LinearUpdate': 0.1,
                'RGBD/ProximityByTime': False,
                'Mem/IncrementalMemory': True,
                'Mem/InitWMWithAllNodes': False,
                
                # 检测新位置
                'RGBD/ProximityPathMaxNeighbors': 1,
                'RGBD/LocalRadius': 1.0,
                'RGBD/LocalLoopDetectionRadius': 3.0,
                'RGBD/GlobalLoopDetectionRadius': 10.0,
                'RGBD/OptimizeFromGraphEnd': False,
                'RGBD/OptimizeMaxError': 1.0,
                'RGBD/OptimizeIterations': 10,
                
                # 3D地图参数
                'Grid/CellSize': 0.05,
                'Grid/RangeMax': 4.0,
                'Grid/RangeMin': 0.2,
                'Grid/3D': True,
                'Grid/FromDepth': False,
                'Grid/MaxObstacleHeight': 2.0,
                'Grid/MinClusterSize': 20,
                'Grid/NormalsSegmentation': True,
                
                'Rtabmap/TimeThr': 700,
                'Rtabmap/MemoryThr': 0,
                'Rtabmap/DetectionRate': 1.0,
                
                'Kp/MaxFeatures': 400,
                'Kp/DetectorStrategy': 0,  # 0=SURF, 1=SIFT, 2=ORB, 3=FAST+FREAK, 4=FAST+BRIEF, 5=GFTT+FREAK, 6=GFTT+BRIEF, 7=BRISK, 8=ORB(OAK-D)
                'Kp/NNStrategy': 1,  # 1=BruteForce
                
                'Reg/Strategy': 0,  # 0=Visual, 1=ICP, 2=VisIcp
                'Reg/Force3DoF': False,
                'Vis/EstimationType': 1,  # 1=3D->2D (PnP)
                'Vis/PnPRefineIterations': 1,
                
                'Optimizer/GravitySigma': 0.0,
                'Optimizer/GravitySigma': 0.0,
            }],
            remappings=[
                ('left/image_rect', '/stereo/left/image_rect'),
                ('right/image_rect', '/stereo/right/image_rect'),
                ('left/camera_info', '/stereo/left/camera_info'),
                ('right/camera_info', '/stereo/right/camera_info'),
                ('odom', '/odom'),
                ('rgbd_image', '/rtabmap/rgbd_image'),
                ('grid_map', '/rtabmap/grid_map'),
            ],
            arguments=['--delete_db_on_start' if delete_db_on_start == 'true' else ''],
            output='screen',
            emulate_tty=True
        ),
        
        # 可视化节点
        Node(
            package='rtabmap_ros',
            executable='rtabmapviz',
            name='rtabmapviz',
            parameters=[{
                'subscribe_odom_info': True,
                'subscribe_scan': False,
                'frame_id': 'base_link',
            }],
            remappings=[
                ('rgb/image', '/stereo/left/image_rect_color'),
                ('depth/image', '/stereo/disparity'),
                ('rgb/camera_info', '/stereo/left/camera_info'),
                ('grid_map', '/rtabmap/grid_map'),
            ],
            output='screen',
            emulate_tty=True
        ),
    ])
