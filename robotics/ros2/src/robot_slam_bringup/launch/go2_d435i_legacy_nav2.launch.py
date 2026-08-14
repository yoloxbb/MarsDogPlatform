"""在 GO2 上使用原生 D435i 双目与原生 WIT IMU，复用 OpenVINS/RTAB-Map 管线并可选启动 Nav2。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterFile
from launch_ros.parameter_descriptions import ParameterValue
from nav2_common.launch import ReplaceString, RewrittenYaml


def package_launch(package_name, launch_name):
    """返回指定 ROS 包中 Python launch 文件的启动源."""
    launch_path = os.path.join(
        get_package_share_directory(package_name), 'launch', launch_name)
    return PythonLaunchDescriptionSource(launch_path)


def generate_launch_description():
    """组合原生 D435i、原生 WIT IMU、通用建图/重定位管线以及可选 Nav2 导航."""
    legacy_package_share = get_package_share_directory(
        'stereo_slam_legacy_bringup')
    nav2_package_share = get_package_share_directory('robot_slam_bringup')
    legacy_config_dir = os.path.join(legacy_package_share, 'config')
    nav2_config_dir = os.path.join(nav2_package_share, 'config')

    params_file = LaunchConfiguration('params_file')
    nav2_params_file = LaunchConfiguration('nav2_params_file')
    database_path = LaunchConfiguration('database_path')
    planar_mode = LaunchConfiguration('planar_mode')
    localization = LaunchConfiguration('localization')
    navigation = LaunchConfiguration('navigation')
    delete_db_on_start = LaunchConfiguration('delete_db_on_start')
    launch_viz = LaunchConfiguration('launch_viz')
    use_sim_time = LaunchConfiguration('use_sim_time')
    base_frame_id = LaunchConfiguration('base_frame_id')
    odom_frame_id = LaunchConfiguration('odom_frame_id')
    map_frame_id = LaunchConfiguration('map_frame_id')
    publish_odom_tf = LaunchConfiguration('publish_odom_tf')
    publish_map_tf = LaunchConfiguration('publish_map_tf')
    left_image_topic = LaunchConfiguration('left_image_topic')
    right_image_topic = LaunchConfiguration('right_image_topic')
    left_info_topic = LaunchConfiguration('left_info_topic')
    right_info_topic = LaunchConfiguration('right_info_topic')
    imu_topic = LaunchConfiguration('imu_topic')
    orientation_imu_topic = LaunchConfiguration('orientation_imu_topic')
    odom_topic = LaunchConfiguration('odom_topic')
    odom_info_topic = LaunchConfiguration('odom_info_topic')
    leg_velocity_enabled = LaunchConfiguration('leg_velocity_enabled')
    leg_odom_topic = LaunchConfiguration('leg_odom_topic')
    startup_delay = LaunchConfiguration('startup_delay')
    nav2_startup_delay = LaunchConfiguration('nav2_startup_delay')
    nav2_autostart = LaunchConfiguration('nav2_autostart')
    nav2_use_composition = LaunchConfiguration('nav2_use_composition')
    log_level = LaunchConfiguration('log_level')

    declared_arguments = [
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                legacy_config_dir, 'rtabmap_openvins_mapping_params.yaml'),
            description='D435i OpenVINS 与 RTAB-Map 参数文件。',
        ),
        DeclareLaunchArgument(
            'nav2_params_file',
            default_value=os.path.join(
                nav2_config_dir, 'go2_nav2_refactor.yaml'),
            description='GO2 使用的 Nav2 Humble 参数文件。',
        ),
        DeclareLaunchArgument(
            'database_path',
            default_value=os.path.expanduser(
                '~/.ros/rtabmap_go2_d435i.db'),
            description='建图时写入、重定位时读取的 RTAB-Map 数据库。',
        ),
        DeclareLaunchArgument(
            'planar_mode',
            default_value='true',
            description=(
                '平地 Nav2 时设为 true，将里程计和地图限制为 x/y/yaw；'
                '需要保留坡道、楼梯高度时设为 false。'
            ),
        ),
        DeclareLaunchArgument(
            'localization',
            default_value='false',
            description='false 为增量建图；true 为读取已有数据库重定位。',
        ),
        DeclareLaunchArgument(
            'navigation',
            default_value='false',
            description='是否启动 Nav2 导航服务器。',
        ),
        DeclareLaunchArgument(
            'delete_db_on_start',
            default_value='true',
            description=(
                '建图模式是否删除旧数据库；重定位模式始终不会删除数据库。'
            ),
        ),
        DeclareLaunchArgument(
            'launch_viz',
            default_value='false',
            description='是否启动 rtabmap_viz；GO2 无桌面运行时建议关闭。',
        ),
        DeclareLaunchArgument(
            'leg_velocity_enabled',
            default_value='true',
            description='视觉退化时是否启用 OpenVINS 足式速度辅助。',
        ),
        DeclareLaunchArgument(
            'leg_odom_topic',
            default_value='/odom_leg',
            description='足式运动学里程计话题。',
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='是否使用 /clock 仿真时钟。',
        ),
        DeclareLaunchArgument(
            'base_frame_id',
            default_value='base_link',
            description=(
                'GO2 机体坐标系；必须已能通过 TF 连接到 D435i 光学坐标系。'
            ),
        ),
        DeclareLaunchArgument(
            'odom_frame_id',
            default_value='odom',
            description='OpenVINS 和 Nav2 使用的局部里程计坐标系。',
        ),
        DeclareLaunchArgument(
            'map_frame_id',
            default_value='map',
            description='RTAB-Map 和 Nav2 使用的全局地图坐标系。',
        ),
        DeclareLaunchArgument(
            'publish_odom_tf',
            default_value='true',
            description=(
                '是否由 OpenVINS 发布 odom 到 base 的 TF；'
                '已有同名 TF 发布者时必须设为 false。'
            ),
        ),
        DeclareLaunchArgument(
            'publish_map_tf',
            default_value='true',
            description='是否由 RTAB-Map 发布 map 到 odom 的 TF。',
        ),
        DeclareLaunchArgument(
            'left_image_topic',
            default_value='/camera/camera/infra1/image_rect_raw',
            description='D435i 左红外校正图像话题。',
        ),
        DeclareLaunchArgument(
            'right_image_topic',
            default_value='/camera/camera/infra2/image_rect_raw',
            description='D435i 右红外校正图像话题。',
        ),
        DeclareLaunchArgument(
            'left_info_topic',
            default_value='/camera/camera/infra1/camera_info',
            description='D435i 驱动发布的左红外 CameraInfo 话题。',
        ),
        DeclareLaunchArgument(
            'right_info_topic',
            default_value='/camera/camera/infra2/camera_info',
            description='D435i 驱动原生发布的右红外 CameraInfo 话题。',
        ),
        DeclareLaunchArgument(
            'imu_topic',
            default_value='/imu/data_raw',
            description='WIT IMU 驱动原生话题，直接供 OpenVINS 使用，不做转发。',
        ),
        DeclareLaunchArgument(
            'orientation_imu_topic',
            default_value='/rtabmap/unused_orientation_imu',
            description=(
                'RTAB-Map 异步姿态 IMU 输入；当前不使用，默认保持为未发布话题。'
            ),
        ),
        DeclareLaunchArgument(
            'odom_topic',
            default_value='/odom',
            description=(
                'OpenVINS 输出和 Nav2 读取的里程计话题；'
                '已有 /odom 发布者时请改为独立话题。'
            ),
        ),
        DeclareLaunchArgument(
            'odom_info_topic',
            default_value='/odom_info',
            description='OpenVINS 输出给 RTAB-Map 的特征统计话题。',
        ),
        DeclareLaunchArgument(
            'startup_delay',
            default_value='1.0',
            description='等待外部 D435i 和 TF 稳定后启动 VIO/RTAB-Map 的秒数。',
        ),
        DeclareLaunchArgument(
            'nav2_startup_delay',
            default_value='5.0',
            description='等待 RTAB-Map 发布地图和 TF 后启动 Nav2 的秒数。',
        ),
        DeclareLaunchArgument(
            'nav2_autostart',
            default_value='false',
            description=(
                '是否自动激活 Nav2 生命周期节点；仅在 navigation=true 时生效。'
            ),
        ),
        DeclareLaunchArgument(
            'nav2_use_composition',
            # Humble navigation_launch.py 用 PythonExpression 解析该值，需使用
            # Python 布尔字面量，不能写成小写的 false。
            default_value='True',
            description='是否把 Nav2 节点加载到同一个组件容器。',
        ),
        DeclareLaunchArgument(
            'log_level',
            default_value='info',
            description='OpenVINS、RTAB-Map 和 Nav2 的日志等级。',
        ),
    ]


    kalibr_extrinsic_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='camera_to_wit_imu_kalibr_extrinsic_tf',
        output='screen',
        arguments=[
            '--x', '-0.034675482490387',
            '--y', '-0.020943006517538',
            '--z', '0.008633613611199',
            '--qx', '0.707265522596187',
            '--qy', '-0.005278522343855',
            '--qz', '-0.706848217515136 ',
            '--qw', '0.010640260536412',
            '--frame-id', 'camera_link',
            '--child-frame-id', 'imu_link',
        ],
    )


    # D435i 图像/CameraInfo 与 WIT IMU 均直接使用各自驱动的原生话题。
    # 不启动 relay，不改写 IMU header.frame_id，也不生成 CameraInfo 中间话题。

    # 与 HB 启动文件使用同一个公共建图管线；D435i 的红外图像已经校正，
    # 因此 OpenVINS 和 RTAB-Map 可以消费同一组 image_rect_raw。
    mapping_launch = IncludeLaunchDescription(
        package_launch(
            'stereo_slam_legacy_bringup',
            'rtabmap_openvins_stereo_mapping.launch.py'),
        launch_arguments={
            'params_file': params_file,
            'frame_id': base_frame_id,
            'odom_frame_id': odom_frame_id,
            'map_frame_id': map_frame_id,
            'publish_odom_tf': publish_odom_tf,
            'publish_map_tf': publish_map_tf,
            'planar_mode': planar_mode,
            'localization': localization,
            'use_sim_time': use_sim_time,
            'odom_left_image_topic': left_image_topic,
            'odom_right_image_topic': right_image_topic,
            'odom_left_info_topic': left_info_topic,
            'odom_right_info_topic': right_info_topic,
            'odom_images_already_rectified': 'true',
            'left_image_topic': left_image_topic,
            'right_image_topic': right_image_topic,
            'left_info_topic': left_info_topic,
            'right_info_topic': right_info_topic,
            'imu_topic': imu_topic,
            # 当前不向 RTAB-Map 提供异步 orientation IMU。
            'orientation_imu_topic': orientation_imu_topic,
            'odom_topic': odom_topic,
            'odom_info_topic': odom_info_topic,
            'leg_velocity_enabled': leg_velocity_enabled,
            'leg_odom_topic': leg_odom_topic,
            # 使用绝对话题名与 GO2 Nav2 参数保持一致。
            'map_topic': '/map',
            'local_grid_obstacle_topic': '/local_grid_obstacle',
            'local_grid_ground_topic': '/local_grid_ground',
            'database_path': database_path,
            'delete_db_on_start': delete_db_on_start,
            'launch_viz': launch_viz,
            'log_level': log_level,
        }.items(),
    )

    # 用启动参数覆盖 Nav2 配置中的机体坐标、里程计话题和时钟。
    nav2_params_with_frames = ReplaceString(
        source_file=nav2_params_file,
        replacements={
            'GO2_MAP_FRAME': map_frame_id,
            'GO2_ODOM_FRAME': odom_frame_id,
            'SLAM_WS_SHARE': nav2_package_share,
        },
    )
    rewritten_nav2_params = RewrittenYaml(
        source_file=nav2_params_with_frames,
        param_rewrites={
            'use_sim_time': use_sim_time,
            'robot_base_frame': base_frame_id,
            'odom_topic': odom_topic,
        },
        convert_types=True,
    )
    configured_nav2_params = ParameterFile(
        rewritten_nav2_params, allow_substs=True)
    nav2_container = Node(
        condition=IfCondition(nav2_use_composition),
        package='rclcpp_components',
        executable='component_container_isolated',
        name='nav2_container',
        output='screen',
        parameters=[
            configured_nav2_params,
            {'autostart': ParameterValue(nav2_autostart, value_type=bool)},
        ],
        arguments=['--ros-args', '--log-level', log_level],
        remappings=[('/tf', 'tf'), ('/tf_static', 'tf_static')],
    )
    nav2_launch = IncludeLaunchDescription(
        package_launch('nav2_bringup', 'navigation_launch.py'),
        launch_arguments={
            'use_sim_time': use_sim_time,
            # navigation_launch.py 会在内部把临时 YAML 包装成 ParameterFile。
            'params_file': rewritten_nav2_params,
            'autostart': nav2_autostart,
            'use_composition': nav2_use_composition,
            'container_name': 'nav2_container',
            'log_level': log_level,
        }.items(),
    )

    # 两段延时分别保证外部传感器和 RTAB-Map 全局坐标系已经稳定。
    delayed_mapping_pipeline = TimerAction(
        period=startup_delay,
        actions=[mapping_launch],
    )
    delayed_nav2 = TimerAction(
        period=nav2_startup_delay,
        actions=[
            GroupAction(
                condition=IfCondition(navigation),
                actions=[nav2_container, nav2_launch],
            ),
        ],
    )

    return LaunchDescription(declared_arguments + [
        kalibr_extrinsic_tf,
        delayed_mapping_pipeline,
        delayed_nav2,
    ])