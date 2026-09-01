import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    LaunchConfiguration,
    NotEqualsSubstitution,
    PathJoinSubstitution,
)
from launch_ros.actions import Node
from nav2_common.launch import ReplaceString, RewrittenYaml


def generate_launch_description():
    """使用 CAPO 2D 里程计和 TF 链启动 RTAB-Map/Nav2。"""

    base_frame = LaunchConfiguration('base_frame')
    odom_frame = LaunchConfiguration('odom_frame')
    map_frame = LaunchConfiguration('map_frame')
    odom_topic = LaunchConfiguration('odom_topic')
    use_viz = LaunchConfiguration('use_viz')
    localization = LaunchConfiguration('localization')
    use_nav2 = LaunchConfiguration('use_nav2')
    database_path = LaunchConfiguration('database_path')
    nav2_params_file = LaunchConfiguration('nav2_params')
    keepout_mask = LaunchConfiguration('keepout_mask')
    keepout_enabled = NotEqualsSubstitution(keepout_mask, '')
    left_image = LaunchConfiguration('left_image')
    right_image = LaunchConfiguration('right_image')
    left_camera_info = LaunchConfiguration('left_camera_info')
    right_camera_info = LaunchConfiguration('right_camera_info')
    start_robot_state_publisher = LaunchConfiguration(
        'start_robot_state_publisher')
    use_stereo_odometry = LaunchConfiguration('use_stereo_odometry')

    rtabmap_odom_params = {
        'frame_id': base_frame,
        'subscribe_rgbd': False,
        'subscribe_stereo': True,
        'subscribe_odom_info': True,
        'use_sim_time': False,
        'approx_sync': True,
        'approx_sync_max_interval': 0.1,
        'sync_queue_size': 10,
        'topic_queue_size': 5,
        'wait_for_transform': 0.5,
        'Rtabmap/ImagesAlreadyRectified': 'true',
        'publish_tf': False,
        'Vis/FeatureType': '8',
        'Vis/EstimationType': '1',
        'Vis/MinInliers': '12',
        'Vis/MaxFeatures': '1000',
        'Vis/CorType': '0',
        'Odom/ResetCountdown': '1',
        'Odom/Strategy': '0',
        'OdomF2M/MaxSize': '1000',
        'GFTT/MinDistance': '5',
        'GFTT/QualityLevel': '0.0001',
        'Stereo/MaxDisparity': '256',
        'wait_imu_to_init': False,
        'qos': 2,
        'qos_image': 2,
        'qos_camera_info': 1,
    }

    rtabmap_grid_filter_params = {
        'Grid/3D': 'true',
        'Grid/RayTracing': 'true',
        'Grid/RangeMin': '0.02',
        'Grid/RangeMax': '4.0',
        # 稠密视差仍按原图计算，此项只减少投影点云及后续分割点数。
        # 当前 640×480 不能被 6 同时整除，本机 RTAB-Map 会自动回退为 5。
        'Grid/DepthDecimation': '8',
        'Grid/CellSize': '0.05',
        # 使用法向量夹角区分地面，并增大邻域以降低平地法线抖动。
        'Grid/NormalsSegmentation': 'true',
        'Grid/MaxGroundAngle': '45',
        'Grid/NormalK': '20',
        'Grid/ClusterRadius': '0.15',
        'Grid/MinClusterSize': '20',
        'Grid/FlatObstacleDetected': 'false',
        'Grid/GroundIsObstacle': 'false',
        # 高度范围同时约束地面候选点和可进入局部栅格的障碍点。
        'Grid/MinGroundHeight': '-0.5',
        'Grid/MaxGroundHeight': '0.10',
        'Grid/MinObstacleHeight': '0.05',
        'Grid/MaxObstacleHeight': '0.7',
        'Grid/NoiseFilteringRadius': '0.12',
        'Grid/NoiseFilteringMinNeighbors': '4',
        'Grid/MapFrameProjection': 'false',
    }

    # 回环检测、几何验证和位姿图优化参数参考优化建图配置。
    rtabmap_loop_closure_params = {
        # 回环假设阈值与单帧处理预算。
        'Rtabmap/ImageBufferSize': '1',
        'Rtabmap/CreateIntermediateNodes': 'false',
        'Rtabmap/LoopThr': '0.11',
        'Rtabmap/LoopRatio': '0',
        'Rtabmap/PublishStats': 'true',
        'Rtabmap/PublishLastSignature': 'true',
        'Rtabmap/PublishPdf': 'false',
        'Rtabmap/PublishLikelihood': 'false',
        'Rtabmap/MemoryThr': '0',
        'Rtabmap/TimeThr': '450',

        # 保留回环所需的词袋、描述子和图约束数据。
        'Mem/IncrementalMemory': 'true',
        'Mem/LocalizationReadOnly': 'false',
        'Mem/ImageKept': 'false',
        'Mem/BinDataKept': 'true',
        'Mem/RawDescriptorsKept': 'true',
        'Mem/IntermediateNodeDataKept': 'false',
        'Mem/InitWMWithAllNodes': 'false',
        'Mem/UseOdomFeatures': 'false',
        'Mem/UseOdomGravity': 'true',
        'Mem/CovOffDiagIgnored': 'true',

        # 控制关键帧、空间邻近回环和回环后图优化验证。
        'RGBD/Enabled': 'true',
        'RGBD/LinearUpdate': '0.10',
        'RGBD/AngularUpdate': '0.10',
        'RGBD/LinearSpeedUpdate': '0.0',
        'RGBD/AngularSpeedUpdate': '0.0',
        'RGBD/OptimizeFromGraphEnd': 'false',
        'RGBD/OptimizeMaxError': '1.5',
        'RGBD/ProximityBySpace': 'true',
        'RGBD/ProximityByTime': 'false',
        'RGBD/NeighborLinkRefining': 'false',
        'RGBD/LoopClosureIdentityGuess': 'false',
        'RGBD/LoopClosureReextractFeatures': 'false',
        'RGBD/LocalBundleOnLoopClosure': 'false',
        'RGBD/MaxLoopClosureDistance': '0.0',
        'RGBD/MaxOdomCacheSize': '10',

        # 使用视觉特征对回环候选进行几何一致性验证。
        'Reg/Strategy': '0',
        'Reg/Force3DoF': 'true',
        'Reg/RepeatOnce': 'true',
        'Vis/MinInliers': '20',
        'Vis/Iterations': '300',
        'Vis/FeatureType': '8',
        'Vis/MaxFeatures': '800',
        'Vis/SSC': 'false',
        'Vis/DepthAsMask': 'true',
        'Vis/MinDepth': '0.1',
        'Vis/MaxDepth': '6.0',
        'Vis/GridRows': '5',
        'Vis/GridCols': '5',
        'Vis/CorType': '0',
        'Vis/CorNNType': '1',
        'Vis/CorNNDR': '0.8',
        'Vis/CorGuessWinSize': '40',
        'Vis/PnPReprojError': '2.0',
        'Vis/PnPRefineIterations': '1',
        'Vis/PnPVarianceMedianRatio': '4',
        'Vis/BundleAdjustment': '1',

        # 词袋字典参数决定回环候选检索质量。
        'Kp/DetectorStrategy': '8',
        'Kp/MaxFeatures': '600',
        'Kp/BadSignRatio': '0.5',
        'Kp/NndrRatio': '0.8',
        'Kp/NNStrategy': '1',
        'Kp/IncrementalDictionary': 'true',
        'Kp/IncrementalFlann': 'true',

        # 回环约束通过验证后使用 g2o 优化二维位姿图。
        'Optimizer/Strategy': '1',
        'Optimizer/Iterations': '15',
        'Optimizer/Epsilon': '0.00001',
        'Optimizer/Robust': 'false',
        'Optimizer/VarianceIgnored': 'false',
        'Optimizer/GravitySigma': '0.3',
    }

    rtabmap_slam_params = {
        'frame_id': base_frame,
        'subscribe_rgbd': False,
        'subscribe_stereo': True,
        'subscribe_odom_info': False,
        'subscribe_odom': True,
        'odom_frame_id': odom_frame,
        'map_frame_id': map_frame,
        'use_sim_time': False,
        'approx_sync': True,
        'approx_sync_max_interval': 0.1,
        'sync_queue_size': 10,
        'topic_queue_size': 5,
        'wait_for_transform': 0.5,
        'tf_delay': 0.05,
        'Rtabmap/ImagesAlreadyRectified': 'true',
        'Rtabmap/DetectionRate': '5',
        'GFTT/MinDistance': '5',
        'GFTT/QualityLevel': '0.0001',
        'GFTT/MaxCorners': '800',
        'Stereo/MaxDisparity': '256',
        'qos': 2,
        'qos_image': 2,
        'qos_camera_info': 1,
        **rtabmap_loop_closure_params,
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
        ('left/image_rect', left_image),
        ('right/image_rect', right_image),
        ('left/camera_info', left_camera_info),
        ('right/camera_info', right_camera_info),
        ('odom', '/vo'),
    ]

    slam_remaps = [
        ('left/image_rect', left_image),
        ('right/image_rect', right_image),
        ('left/camera_info', left_camera_info),
        ('right/camera_info', right_camera_info),
        ('odom', odom_topic),
    ]

    pkg_robot_slam_bringup = get_package_share_directory('robot_slam_bringup')
    pkg_go2_description = get_package_share_directory('go2_description')
    pkg_nav2_bringup = get_package_share_directory('nav2_bringup')

    go2_urdf_path = os.path.join(
        pkg_go2_description, 'urdf', 'go2_description.urdf')
    with open(go2_urdf_path, encoding='utf-8') as urdf_file:
        go2_robot_description = urdf_file.read()

    nav2_launch = PathJoinSubstitution(
        [pkg_nav2_bringup, 'launch', 'navigation_launch.py'])
    # 将启动参数和安装后的包路径同步写入 Nav2，避免源码路径或坐标系被写死。
    replaced_nav2_params_file = ReplaceString(
        source_file=nav2_params_file,
        replacements={
            'GO2_MAP_FRAME': map_frame,
            'GO2_ODOM_FRAME': odom_frame,
            'SLAM_WS_SHARE': pkg_robot_slam_bringup,
            'KEEPOUT_ZONE_ENABLED': keepout_enabled,
        },
    )
    configured_nav2_params_file = RewrittenYaml(
        source_file=replaced_nav2_params_file,
        param_rewrites={
            'robot_base_frame': base_frame,
            'odom_topic': odom_topic,
        },
        convert_types=True,
    )
    # KeepoutFilter 使用独立 mask map_server 和过滤信息服务，不替换
    # RTAB-Map 发布的 /map。只有传入 mask 路径时才启动这组节点。
    keepout_mask_server = Node(
        package='nav2_map_server',
        executable='map_server',
        name='keepout_filter_mask_server',
        output='screen',
        parameters=[
            {
                'use_sim_time': False,
                'yaml_filename': keepout_mask,
                'topic_name': 'keepout_filter_mask',
                'frame_id': map_frame,
            }
        ],
        remappings=[('/tf', 'tf'), ('/tf_static', 'tf_static')],
    )
    keepout_filter_info_server = Node(
        package='nav2_map_server',
        executable='costmap_filter_info_server',
        name='keepout_costmap_filter_info_server',
        output='screen',
        parameters=[
            {
                'use_sim_time': False,
                'type': 0,
                'filter_info_topic': '/keepout_costmap_filter_info',
                'mask_topic': '/keepout_filter_mask',
                'base': 0.0,
                'multiplier': 1.0,
            }
        ],
        remappings=[('/tf', 'tf'), ('/tf_static', 'tf_static')],
    )
    keepout_lifecycle_manager = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_keepout_zone',
        output='screen',
        parameters=[
            {
                'use_sim_time': False,
                'autostart': True,
                'node_names': [
                    'keepout_filter_mask_server',
                    'keepout_costmap_filter_info_server',
                ],
            }
        ],
    )
    keepout_nodes = GroupAction(
        condition=IfCondition(keepout_enabled),
        actions=[
            keepout_mask_server,
            keepout_filter_info_server,
            keepout_lifecycle_manager,
        ],
    )

    return LaunchDescription([

        DeclareLaunchArgument(
            'base_frame',
            default_value='base_footprint',
            description='RTAB-Map 与 Nav2 使用的机器人基座坐标系'
        ),
        DeclareLaunchArgument(
            'odom_frame',
            default_value='odom',
            description='CAPO 2D 里程计的父坐标系'
        ),
        DeclareLaunchArgument(
            'map_frame',
            default_value='map',
            description='RTAB-Map 与 Nav2 使用的全局坐标系'
        ),
        DeclareLaunchArgument(
            'odom_topic',
            default_value='/SMX/Odom_2D',
            description='CAPO 发布的 2D 里程计话题'
        ),
        DeclareLaunchArgument(
            'use_viz',
            default_value='false',
            description='是否启动 RTAB-Map 可视化界面'
        ),
        DeclareLaunchArgument(
            'start_robot_state_publisher',
            default_value='false',
            description='是否发布 GO2 URDF 坐标变换树'
        ),
        DeclareLaunchArgument(
            'use_stereo_odometry',
            default_value='false',
            description='是否同时启动输出到 /vo 的 RTAB-Map 双目视觉里程计'
        ),

        # D435i 已发布矫正后的红外图像及对应 CameraInfo，直接订阅原始话题。
        DeclareLaunchArgument(
            'left_image',
            default_value='/camera/camera/infra1/image_rect_raw'
        ),
        DeclareLaunchArgument(
            'right_image',
            default_value='/camera/camera/infra2/image_rect_raw'
        ),
        DeclareLaunchArgument(
            'left_camera_info',
            default_value='/camera/camera/infra1/camera_info'
        ),
        DeclareLaunchArgument(
            'right_camera_info',
            default_value='/camera/camera/infra2/camera_info'
        ),

        DeclareLaunchArgument(
            'localization',
            default_value='false',
            description='是否以已有数据库启动 RTAB-Map 重定位模式'
        ),
        DeclareLaunchArgument(
            'use_nav2',
            default_value='false',
            description='是否启动 Nav2 导航栈'
        ),

        DeclareLaunchArgument(
            'database_path',
            default_value='~/.ros/rtabmap_go2_leg_d435i.db',
            description='RTAB-Map 数据库路径，重定位模式必须指向已有数据库'
        ),
        DeclareLaunchArgument(
            'nav2_params',
            default_value=os.path.join(
                pkg_robot_slam_bringup, 'config', 'nav.yaml'),
            description='CAPO + RTAB-Map 使用的 Nav2 参数文件'
        ),
        DeclareLaunchArgument(
            'keepout_mask',
            default_value='',
            description=(
                'Keepout mask YAML 路径；留空表示不启用。PGM/YAML 应与原始地图'
                '保持相同的尺寸、分辨率和原点。'
            ),
        ),

        # 不再启动旧的 /odom_leg 发布器，odom -> base_footprint 由 CAPO 独占发布。
        Node(
            condition=IfCondition(start_robot_state_publisher),
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{'robot_description': go2_robot_description}]
        ),

        Node(
            condition=IfCondition(use_stereo_odometry),
            package='rtabmap_odom',
            executable='stereo_odometry',
            name='d435i_stereo_odometry',
            output='screen',
            parameters=[rtabmap_odom_params],
            remappings=odom_remaps,
            arguments=['--ros-args', '--log-level', 'warn']
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

        GroupAction(
            condition=IfCondition(use_nav2),
            actions=[
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource([nav2_launch]),
                    launch_arguments=[
                        ('use_sim_time', 'false'),
                        ('params_file', configured_nav2_params_file)
                    ]
                ),
                keepout_nodes,
            ],
        ),
    ])
