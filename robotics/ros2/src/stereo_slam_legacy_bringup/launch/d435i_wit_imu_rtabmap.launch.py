"""使用 2026-07-30 外参启动 D435i、WIT IMU、OpenVINS 和 RTAB-Map。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def package_launch(package_name, launch_name):
    """返回指定 ROS 包内 Python launch 文件的启动源。"""
    launch_path = os.path.join(
        get_package_share_directory(package_name),
        'launch',
        launch_name,
    )
    return PythonLaunchDescriptionSource(launch_path)


def calibrated_camera_transforms():
    """创建 D435i 左目光学坐标系到外置 WIT IMU 的标定静态 TF。"""
    # RealSense 已发布 camera_link -> 左右光学坐标系。这里只补充外置
    # WIT IMU 的 T_cam_imu，避免再次发布相机 TF 导致同一 child 有两个父节点。
    left_camera_to_imu = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='d435i_left_to_wit_imu_20260730',
        output='screen',
        arguments=[
            '--x', '0.020166844204201728',
            '--y', '-0.0046062476678805945',
            '--z', '-0.0404088146852058',
            '--qx', '-0.7098667935119302',
            '--qy', '-0.7042787194571575',
            '--qz', '-0.0078207559766047',
            '--qw', '0.0044109596270819',
            '--frame-id', 'camera_infra1_optical_frame',
            '--child-frame-id', 'imu_link',
        ],
    )
    return [left_camera_to_imu]


def generate_launch_description():
    """组合 D435i 矫正双目、外置 WIT IMU 和公共建图管线。"""
    package_share = get_package_share_directory('stereo_slam_legacy_bringup')
    config_dir = os.path.join(package_share, 'config')

    params_file = LaunchConfiguration('params_file')
    database_path = LaunchConfiguration('database_path')
    delete_db_on_start = LaunchConfiguration('delete_db_on_start')
    launch_viz = LaunchConfiguration('launch_viz')
    start_sensors = LaunchConfiguration('start_sensors')
    use_sim_time = LaunchConfiguration('use_sim_time')
    base_frame_id = LaunchConfiguration('base_frame_id')
    startup_delay = LaunchConfiguration('startup_delay')
    exposure = LaunchConfiguration('exposure')
    gain = LaunchConfiguration('gain')
    log_level = LaunchConfiguration('log_level')
    imu_time_offset_ms = LaunchConfiguration('imu_time_offset_ms')
    openvins_imu_topic = LaunchConfiguration('openvins_imu_topic')

    declared_arguments = [
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                config_dir, 'rtabmap_openvins_mapping_params.yaml'),
            description='沿用 HB 启动文件的 OpenVINS 与 RTAB-Map 参数。',
        ),
        DeclareLaunchArgument(
            'database_path',
            default_value=os.path.expanduser(
                '~/.ros/rtabmap_d435i_wit_20260730.db'),
            description='D435i 与外置 WIT IMU 使用的独立地图数据库。',
        ),
        DeclareLaunchArgument(
            'delete_db_on_start',
            default_value='true',
            description='true 表示从空数据库开始建图。',
        ),
        DeclareLaunchArgument(
            'launch_viz',
            default_value='true',
            description='是否同时启动 rtabmap_viz。',
        ),
        DeclareLaunchArgument(
            'start_sensors',
            default_value='true',
            description='false 时不重复启动已经运行的 D435i 和 WIT IMU。',
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='回放 bag 时可改为 true 使用 /clock。',
        ),
        DeclareLaunchArgument(
            'base_frame_id',
            default_value='camera_link',
            description='OpenVINS 输出使用的 D435i 原生机体坐标系。',
        ),
        DeclareLaunchArgument(
            'startup_delay',
            default_value='5.0',
            description='等待相机和 IMU 稳定后再启动建图，单位秒。',
        ),
        DeclareLaunchArgument(
            'exposure',
            default_value='5000',
            description='D435i 红外相机手动曝光值。',
        ),
        DeclareLaunchArgument(
            'gain',
            default_value='16',
            description='D435i 红外相机手动增益。',
        ),
        DeclareLaunchArgument(
            'log_level',
            default_value='info',
            description='OpenVINS 和 RTAB-Map 的日志等级。',
        ),
        DeclareLaunchArgument(
            'imu_time_offset_ms',
            default_value='-13.371873203856067',
            description=(
                '加到 IMU 消息时间戳上的偏移，单位 ms。Kalibr 给出 '
                't_imu=t_cam+13.371873 ms，因此这里取负值对齐到相机时间。'
            ),
        ),
        DeclareLaunchArgument(
            'openvins_imu_topic',
            default_value='/imu/data_filtered_time_aligned',
            description='完成固定时间偏移后，仅供 OpenVINS 使用的 IMU 话题。',
        ),
    ]

    camera_launch = IncludeLaunchDescription(
        package_launch('realsense2_camera', 'rs_launch.py'),
        condition=IfCondition(start_sensors),
        launch_arguments={
            # 保持与联合标定 bag 一致的 640x480@15 Hz 矫正红外双目。
            'camera_namespace': 'camera',
            'camera_name': 'camera',
            'enable_color': 'false',
            'enable_depth': 'false',
            'enable_infra': 'false',
            'enable_infra1': 'true',
            'enable_infra2': 'true',
            'depth_module.infra_profile': '640x480x15',
            'depth_module.enable_auto_exposure': 'false',
            'depth_module.exposure': exposure,
            'depth_module.gain': gain,
            'enable_sync': 'true',
            # 本启动文件使用外置 WIT IMU，不启动 D435i 内置 IMU。
            'enable_gyro': 'false',
            'enable_accel': 'false',
            'unite_imu_method': '0',
            # 使用 D435i 原生相机 TF；本文件只额外补充外置 IMU 的 TF。
            'publish_tf': 'true',
            'pointcloud.enable': 'false',
            'align_depth.enable': 'false',
        }.items(),
    )
    imu_launch = IncludeLaunchDescription(
        package_launch('wit_imu', 'wit_imu.launch.py'),
        condition=IfCondition(start_sensors),
    )

    # Kalibr 给出 t_imu=t_cam+13.371873 ms。转发节点的参数会直接加到
    # IMU 时间戳，因此使用负值，把 IMU 时间轴平移回相机时间轴。
    imu_time_relay = Node(
        package='stereo_slam_legacy_bringup',
        executable='d435i_extrinsics_relay',
        name='wit_imu_time_offset_20260730',
        output='screen',
        parameters=[{
            'input_topic': '/imu/data_filtered',
            'output_topic': openvins_imu_topic,
            'output_frame_id': 'imu_link',
            'imu_time_offset_ms': ParameterValue(
                imu_time_offset_ms, value_type=float),
            # 本节点这里只转发 IMU；使用不存在的输入话题关闭 CameraInfo 转发。
            'right_info_input_topic':
                '/rtabmap/unused_right_camera_info_input',
            'right_info_output_topic':
                '/rtabmap/unused_right_camera_info_output',
            'stereo_baseline': 0.050039552364669865,
        }],
    )

    mapping_launch = IncludeLaunchDescription(
        package_launch(
            'stereo_slam_legacy_bringup',
            'rtabmap_openvins_stereo_mapping.launch.py',
        ),
        launch_arguments={
            'params_file': params_file,
            'frame_id': base_frame_id,
            'odom_frame_id': 'odom',
            'map_frame_id': 'map',
            'publish_odom_tf': 'true',
            'publish_map_tf': 'true',
            'planar_mode': 'false',
            'localization': 'false',
            'use_sim_time': use_sim_time,
            # 本次 Kalibr 外参属于 D435i 已矫正的红外光学坐标系。
            'odom_left_image_topic':
                '/camera/camera/infra1/image_rect_raw',
            'odom_right_image_topic':
                '/camera/camera/infra2/image_rect_raw',
            'odom_left_info_topic':
                '/camera/camera/infra1/camera_info',
            'odom_right_info_topic':
                '/camera/camera/infra2/camera_info',
            'odom_images_already_rectified': 'true',
            'left_image_topic':
                '/camera/camera/infra1/image_rect_raw',
            'right_image_topic':
                '/camera/camera/infra2/image_rect_raw',
            'left_info_topic':
                '/camera/camera/infra1/camera_info',
            'right_info_topic':
                '/camera/camera/infra2/camera_info',
            # OpenVINS 使用已低通并完成固定时间对齐的 IMU 数据。
            'imu_topic': openvins_imu_topic,
            # 滤波话题同样没有有效 orientation，禁止送给RTAB-Map异步接口。
            'orientation_imu_topic': '/rtabmap/unused_orientation_imu',
            'odom_topic': '/odom',
            'odom_info_topic': '/odom_info',
            'database_path': database_path,
            'delete_db_on_start': delete_db_on_start,
            'launch_viz': launch_viz,
            'log_level': log_level,
        }.items(),
    )

    # 传感器先运行一段时间，确保 OpenVINS 启动时已有连续 IMU 数据。
    delayed_mapping = TimerAction(
        period=startup_delay,
        actions=[mapping_launch],
    )

    return LaunchDescription(declared_arguments + [
        camera_launch,
        imu_launch,
        imu_time_relay,
        delayed_mapping,
    ] + calibrated_camera_transforms())
