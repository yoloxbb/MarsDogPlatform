"""启动新 USB 双目相机、WIT IMU、OpenVINS 和 RTAB-Map。"""

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


def package_launch(package_name, launch_name):
    """返回指定 ROS 包内 Python launch 文件的启动源。"""
    launch_path = os.path.join(
        get_package_share_directory(package_name), 'launch', launch_name)
    return PythonLaunchDescriptionSource(launch_path)


def static_camera_transform(name, child_frame, translation, quaternion):
    """创建从 imu_link 到相机光学坐标系的标定静态 TF 节点。"""
    x, y, z = translation
    qx, qy, qz, qw = quaternion
    return Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name=name,
        output='screen',
        arguments=[
            '--x', str(x),
            '--y', str(y),
            '--z', str(z),
            '--qx', str(qx),
            '--qy', str(qy),
            '--qz', str(qz),
            '--qw', str(qw),
            '--frame-id', 'imu_link',
            '--child-frame-id', child_frame,
        ],
    )


def rectify_node(camera_namespace):
    """创建使用 plumb_bob CameraInfo 的单目校正节点。"""
    return Node(
        package='image_proc',
        executable='rectify_node',
        namespace=camera_namespace,
        name='rectify',
        output='screen',
        remappings=[
            ('image', 'image_raw'),
            ('camera_info', 'camera_info'),
            ('image_rect', 'image_rect'),
        ],
    )


def generate_launch_description():
    """组合新 USB 双目、WIT IMU、标定 TF、OpenVINS 和 RTAB-Map。"""
    package_config_dir = os.path.join(
        get_package_share_directory('stereo_slam_legacy_bringup'), 'config')

    params_file = LaunchConfiguration('params_file')
    database_path = LaunchConfiguration('database_path')
    delete_db_on_start = LaunchConfiguration('delete_db_on_start')
    launch_viz = LaunchConfiguration('launch_viz')
    start_sensors = LaunchConfiguration('start_sensors')
    base_frame_id = LaunchConfiguration('base_frame_id')
    camera_time_offset_ms = LaunchConfiguration('camera_time_offset_ms')

    declared_arguments = [
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                package_config_dir, 'rtabmap_openvins_mapping_params.yaml'),
            description='沿用现有 OpenVINS 和 RTAB-Map 参数文件。',
        ),
        DeclareLaunchArgument(
            'database_path',
            default_value=os.path.expanduser(
                '~/.ros/rtabmap_openvins_hb_mapping.db'),
            description='新 USB 双目相机使用的独立 RTAB-Map 数据库。',
        ),
        DeclareLaunchArgument(
            'delete_db_on_start',
            default_value='true',
            description='true 表示本次从空数据库开始建图。',
        ),
        DeclareLaunchArgument(
            'launch_viz',
            default_value='true',
            description='是否同时启动 rtabmap_viz。',
        ),
        DeclareLaunchArgument(
            'base_frame_id',
            default_value='imu_link',
            description='独立测试使用 imu_link，装机后可改成 base_link。',
        ),
        DeclareLaunchArgument(
            'start_sensors',
            default_value='true',
            description='false 时不重复启动已经运行的相机和 IMU。',
        ),
        DeclareLaunchArgument(
            'camera_time_offset_ms',
            # 两目 Kalibr 时偏的平均值，方向为 t_imu=t_cam+shift。
            default_value='40.0',
            description='Kalibr 相机到 IMU 时间偏移，单位为毫秒。',
        ),
    ]

    camera_launch = IncludeLaunchDescription(
        package_launch(
            'stereo_v4l2_camera', 'hb_yuyv_1280x480_15fps.launch.py'),
        condition=IfCondition(start_sensors),
        launch_arguments={
            # 覆盖相机启动文件中的 0 ms 占位值。
            'camera_time_offset_ms': camera_time_offset_ms,
        }.items(),
    )
    imu_launch = IncludeLaunchDescription(
        package_launch('wit_imu', 'wit_imu.launch.py'),
        condition=IfCondition(start_sensors),
    )

    # Kalibr 的 T_ic 表示相机坐标到 IMU 坐标的变换，对应 TF 的 imu_link -> cam。
    imu_to_cam0 = static_camera_transform(
        'imu_to_hb_cam0',
        'cam0',
        (-0.04834574, -0.02707217, -0.00892512),
        (-0.501654061932, -0.471951072115, 0.500099410078, 0.524886623677),
    )
    imu_to_cam1 = static_camera_transform(
        'imu_to_hb_cam1',
        'cam1',
        (-0.04748951, 0.02311057, -0.00924460),
        (-0.519104501097, -0.493945949931, 0.480755105280, 0.505393355946),
    )

    mapping_launch = IncludeLaunchDescription(
        package_launch(
            'stereo_slam_legacy_bringup',
            'rtabmap_openvins_stereo_mapping.launch.py'),
        launch_arguments={
            'params_file': params_file,
            'frame_id': base_frame_id,
            # OpenVINS 使用原始图像和 Kalibr 原始相机外参，避免遗漏
            # CameraInfo rectification R 带来的约 3 度坐标轴旋转。
            'odom_left_image_topic': '/cam0/image_raw',
            'odom_right_image_topic': '/cam1/image_raw',
            'odom_left_info_topic': '/cam0/camera_info',
            'odom_right_info_topic': '/cam1/camera_info',
            'odom_images_already_rectified': 'false',
            # RTAB-Map 仍使用极线矫正后的图像生成双目深度和地图。
            'left_image_topic': '/cam0/image_rect',
            'right_image_topic': '/cam1/image_rect',
            'left_info_topic': '/cam0/camera_info',
            'right_info_topic': '/cam1/camera_info',
            # OpenVINS使用200 Hz、20 Hz截止的低通IMU；原始数据仍保留用于标定。
            'imu_topic': '/imu/data_filtered',
            'odom_topic': '/odom',
            'odom_info_topic': '/odom_info',
            'database_path': database_path,
            'delete_db_on_start': delete_db_on_start,
            'launch_viz': launch_viz,
        }.items(),
    )

    # 先稳定传感器 5 秒，再同时启动 OpenVINS 和 RTAB-Map 建图链路。
    delayed_openvins_pipeline_launch = TimerAction(
        period=5.0,
        actions=[mapping_launch],
    )

    return LaunchDescription(declared_arguments + [
        camera_launch,
        imu_launch,
        imu_to_cam0,
        imu_to_cam1,
        rectify_node('cam0'),
        rectify_node('cam1'),
        delayed_openvins_pipeline_launch,
    ])
