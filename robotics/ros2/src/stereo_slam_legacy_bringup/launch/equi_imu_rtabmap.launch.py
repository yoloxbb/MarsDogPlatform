import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def package_launch(package_name, launch_name):
    """返回指定ROS包内Python launch文件的启动源。"""
    launch_path = os.path.join(
        get_package_share_directory(package_name), 'launch', launch_name)
    return PythonLaunchDescriptionSource(launch_path)


def static_camera_transform(name, child_frame, translation, quaternion):
    """创建从imu_link到相机光学坐标系的标定静态TF节点。"""
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
    """创建支持equidistant CameraInfo的单目鱼眼整流节点。"""
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
    """启动TST鱼眼双目、WIT IMU、整流、标定TF及OpenVINS RTAB-Map建图。"""
    package_config_dir = os.path.join(
        get_package_share_directory('stereo_slam_legacy_bringup'), 'config')

    params_file = LaunchConfiguration('params_file')
    database_path = LaunchConfiguration('database_path')
    delete_db_on_start = LaunchConfiguration('delete_db_on_start')
    launch_viz = LaunchConfiguration('launch_viz')
    start_sensors = LaunchConfiguration('start_sensors')
    base_frame_id = LaunchConfiguration('base_frame_id')

    declared_arguments = [
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                package_config_dir, 'rtabmap_openvins_mapping_params.yaml')),
        DeclareLaunchArgument(
            'database_path',
            default_value=os.path.expanduser(
                '~/.ros/rtabmap_openvins_equi_mapping.db')),
        DeclareLaunchArgument('delete_db_on_start', default_value='true'),
        DeclareLaunchArgument('launch_viz', default_value='true'),
        DeclareLaunchArgument(
            'base_frame_id',
            default_value='imu_link',
            description=(
                '建图基坐标系；独立组件用imu_link，装车后可改为base_link。')),
        DeclareLaunchArgument(
            'start_sensors',
            default_value='true',
            description='false时只启动整流、TF和建图，适合传感器已单独启动的情况。'),
    ]

    camera_launch = IncludeLaunchDescription(
        package_launch('stereo_v4l2_camera', 'equi_yuyv_2560x960_20fps.launch.py'),
        condition=IfCondition(start_sensors),
    )
    imu_launch = IncludeLaunchDescription(
        package_launch('wit_imu', 'wit_imu.launch.py'),
        condition=IfCondition(start_sensors),
    )

    # 这里使用Kalibr的T_imu_cam（相机光心在IMU坐标系中的位姿），不是T_cam_imu。
    imu_to_cam0 = static_camera_transform(
        'imu_to_cam0',
        'cam0',
        (-0.042963489, -0.025828586, -0.026652652),
        (-0.511529228, -0.489185607, 0.495066366, 0.503929146),
    )
    imu_to_cam1 = static_camera_transform(
        'imu_to_cam1',
        'cam1',
        (-0.042918185, 0.023611724, -0.026089266),
        (-0.502205097, -0.501198054, 0.497948507, 0.498635976),
    )

    mapping_launch = IncludeLaunchDescription(
        package_launch(
            'stereo_slam_legacy_bringup',
            'rtabmap_openvins_stereo_mapping.launch.py'),
        launch_arguments={
            'params_file': params_file,
            'frame_id': base_frame_id,
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

    return LaunchDescription(declared_arguments + [
        camera_launch,
        imu_launch,
        imu_to_cam0,
        imu_to_cam1,
        rectify_node('cam0'),
        rectify_node('cam1'),
        mapping_launch,
    ])
