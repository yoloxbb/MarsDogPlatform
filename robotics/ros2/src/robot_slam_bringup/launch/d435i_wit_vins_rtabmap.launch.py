"""启动 D435i、WIT IMU、VINS-Fusion 外部里程计和 RTAB-Map 建图。"""

import os

from ament_index_python.packages import (
    get_package_prefix,
    get_package_share_directory,
)
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def package_launch(package_name, launch_name):
    """返回指定 ROS 2 包中 Python launch 文件的启动源。"""
    launch_path = os.path.join(
        get_package_share_directory(package_name),
        "launch",
        launch_name,
    )
    return PythonLaunchDescriptionSource(launch_path)


def generate_launch_description():
    """组合传感器、VINS 外部 odom、RTAB-Map 回环与可视化节点。"""
    bringup_share = get_package_share_directory("robot_slam_bringup")
    vins_share = get_package_share_directory("vins")
    vins_executable = os.path.join(
        get_package_prefix("vins"),
        "lib",
        "vins",
        "vins_node",
    )

    start_sensors = LaunchConfiguration("start_sensors")
    use_sim_time = LaunchConfiguration("use_sim_time")
    launch_viz = LaunchConfiguration("launch_viz")
    publish_body_camera_tf = LaunchConfiguration("publish_body_camera_tf")
    delete_db_on_start = LaunchConfiguration("delete_db_on_start")
    vins_startup_delay = LaunchConfiguration("vins_startup_delay")
    rtabmap_startup_delay = LaunchConfiguration("rtabmap_startup_delay")
    log_level = LaunchConfiguration("log_level")

    vins_config = LaunchConfiguration("vins_config")
    rtabmap_params = LaunchConfiguration("rtabmap_params")
    vins_output_dir = LaunchConfiguration("vins_output_dir")
    database_path = LaunchConfiguration("database_path")

    imu_topic = LaunchConfiguration("imu_topic")
    left_image_topic = LaunchConfiguration("left_image_topic")
    right_image_topic = LaunchConfiguration("right_image_topic")
    left_info_topic = LaunchConfiguration("left_info_topic")
    right_info_topic = LaunchConfiguration("right_info_topic")
    odom_topic = LaunchConfiguration("odom_topic")

    camera_profile = LaunchConfiguration("camera_profile")
    exposure = LaunchConfiguration("exposure")
    gain = LaunchConfiguration("gain")

    declared_arguments = [
        DeclareLaunchArgument(
            "start_sensors",
            default_value="true",
            description="是否同时启动 D435i 和 WIT IMU。",
        ),
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="false",
            description="回放 rosbag 时是否使用 /clock。",
        ),
        DeclareLaunchArgument(
            "launch_viz",
            default_value="true",
            description="是否启动 rtabmap_viz。",
        ),
        DeclareLaunchArgument(
            "publish_body_camera_tf",
            default_value="true",
            description="是否发布标定后的 body 到 camera_link 静态 TF。",
        ),
        DeclareLaunchArgument(
            "delete_db_on_start",
            default_value="true",
            description="启动建图时是否删除旧 RTAB-Map 数据库。",
        ),
        DeclareLaunchArgument(
            "vins_startup_delay",
            default_value="2.0",
            description="等待传感器稳定后启动 VINS 的秒数。",
        ),
        DeclareLaunchArgument(
            "rtabmap_startup_delay",
            default_value="8.0",
            description="等待 VINS 订阅建立后启动 RTAB-Map 的秒数。",
        ),
        DeclareLaunchArgument(
            "log_level",
            default_value="info",
            description="VINS 和 RTAB-Map 节点日志等级。",
        ),
        DeclareLaunchArgument(
            "vins_config",
            default_value=os.path.join(
                vins_share,
                "config",
                "realsense_d435i",
                "realsense_stereo_wit_imu_config.yaml",
            ),
            description="D435i + WIT IMU 的 VINS-Fusion 参数文件。",
        ),
        DeclareLaunchArgument(
            "rtabmap_params",
            default_value=os.path.join(
                bringup_share,
                "config",
                "openvins_rtabmap.yaml",
            ),
            description="复用其中 rtabmap/rtabmap_viz 节点的建图参数。",
        ),
        DeclareLaunchArgument(
            "vins_output_dir",
            default_value=os.environ.get(
                "ROBOT_OUTPUT_DIR",
                os.path.join(os.path.expanduser("~"), "robot_ws", "output"),
            ),
            description="VINS 轨迹和位姿图输出目录；目录需要预先存在。",
        ),
        DeclareLaunchArgument(
            "database_path",
            default_value=os.path.join(
                os.path.expanduser("~"),
                ".ros",
                "rtabmap_vins_fusion_mapping.db",
            ),
            description="RTAB-Map 建图数据库路径。",
        ),
        DeclareLaunchArgument(
            "imu_topic",
            default_value="/imu/data_raw",
            description="VINS 使用的外置 WIT 原始 IMU 话题。",
        ),
        DeclareLaunchArgument(
            "left_image_topic",
            default_value="/camera/camera/infra1/image_rect_raw",
            description="D435i 左红外矫正图像话题。",
        ),
        DeclareLaunchArgument(
            "right_image_topic",
            default_value="/camera/camera/infra2/image_rect_raw",
            description="D435i 右红外矫正图像话题。",
        ),
        DeclareLaunchArgument(
            "left_info_topic",
            default_value="/camera/camera/infra1/camera_info",
            description="D435i 左红外 CameraInfo 话题。",
        ),
        DeclareLaunchArgument(
            "right_info_topic",
            default_value="/camera/camera/infra2/camera_info",
            description="D435i 右红外 CameraInfo 话题。",
        ),
        DeclareLaunchArgument(
            "odom_topic",
            default_value="/odometry",
            description="VINS 输出、RTAB-Map 输入的外部里程计话题。",
        ),
        DeclareLaunchArgument(
            "camera_profile",
            default_value="640x480x15",
            description="D435i 红外双目采集规格。",
        ),
        DeclareLaunchArgument(
            "exposure",
            default_value="5000",
            description="D435i 红外相机手动曝光值。",
        ),
        DeclareLaunchArgument(
            "gain",
            default_value="16",
            description="D435i 红外相机手动增益。",
        ),
    ]

    # 只启用红外双目；VIO 使用外置 WIT，因此关闭 D435i 内置 IMU。
    camera_launch = IncludeLaunchDescription(
        package_launch("realsense2_camera", "rs_launch.py"),
        condition=IfCondition(start_sensors),
        launch_arguments={
            "camera_namespace": "camera",
            "camera_name": "camera",
            "enable_color": "false",
            "enable_depth": "false",
            "enable_infra": "false",
            "enable_infra1": "true",
            "enable_infra2": "true",
            "depth_module.infra_profile": camera_profile,
            "depth_module.enable_auto_exposure": "false",
            "depth_module.exposure": exposure,
            "depth_module.gain": gain,
            "enable_sync": "true",
            "enable_gyro": "false",
            "enable_accel": "false",
            "unite_imu_method": "0",
            "publish_tf": "true",
            "pointcloud.enable": "false",
            "align_depth.enable": "false",
        }.items(),
    )

    wit_imu_launch = IncludeLaunchDescription(
        package_launch("wit_imu", "wit_imu.launch.py"),
        condition=IfCondition(start_sensors),
        launch_arguments={
            "expected_rate_hz": "200.0",
            "raw_topic": imu_topic,
            "filtered_topic": "/imu/data_filtered",
            "enable_low_pass": "true",
            "low_pass_cutoff_hz": "20.0",
        }.items(),
    )

    # VINS 的 body 就是 WIT IMU 坐标系。这里发布 2026-08-03 16:45
    # Kalibr 外参转换后的 body -> camera_link，使 RTAB-Map 能把
    # D435i 图像转换到 body 坐标系。
    body_to_camera_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="vins_body_to_d435i_camera_20260803",
        output="screen",
        condition=IfCondition(publish_body_camera_tf),
        arguments=[
            "--x", "0.0039123383007284565",
            "--y", "-0.020411618176131557",
            "--z", "-0.03470357781542836",
            "--qx", "-0.7052099474822251",
            "--qy", "0.011074111237417432",
            "--qz", "0.7087317863872082",
            "--qw", "0.015985899937620437",
            "--frame-id", "body",
            "--child-frame-id", "camera_link",
        ],
    )

    # VINS 只提供连续局部里程计；本启动文件不会启动 VINS loop_fusion。
    vins_node = ExecuteProcess(
        cmd=[vins_executable, vins_config],
        output="screen",
        emulate_tty=True,
        # launch_ros.actions.Node 会自动追加 --ros-args，而当前 VINS
        # 主程序要求 argc == 2；直接执行可确保只传入一个配置路径。
        additional_env={"ROBOT_OUTPUT_DIR": vins_output_dir},
    )

    rtabmap_remappings = [
        ("left/image_rect", left_image_topic),
        ("right/image_rect", right_image_topic),
        ("left/camera_info", left_info_topic),
        ("right/camera_info", right_info_topic),
        ("odom", odom_topic),
    ]

    # RTAB-Map 直接消费 /odometry，不再启动任何 rtabmap_odom 节点。
    # Mem/UseOdomFeatures=false 强制回环词袋特征由 RTAB-Map 从图像提取。
    rtabmap_node = Node(
        package="rtabmap_slam",
        executable="rtabmap",
        name="rtabmap",
        output="screen",
        emulate_tty=True,
        parameters=[
            rtabmap_params,
            {
                "use_sim_time": use_sim_time,
                "frame_id": "body",
                # 留空后 RTAB-Map 才会订阅外部 /odometry；它会从消息
                # header.frame_id 自动取得 VINS 使用的 world 里程计系。
                "odom_frame_id": "",
                "map_frame_id": "map",
                "publish_tf": True,
                "database_path": database_path,
                "delete_db_on_start": ParameterValue(
                    delete_db_on_start,
                    value_type=bool,
                ),
                "subscribe_stereo": True,
                "subscribe_rgb": False,
                "subscribe_rgbd": False,
                "subscribe_depth": False,
                "subscribe_odom_info": False,
                "subscribe_imu": False,
                "approx_sync": True,
                "Mem/IncrementalMemory": "true",
                "Mem/InitWMWithAllNodes": "false",
                "Mem/UseOdomFeatures": "false",
                "RGBD/Enabled": "true",
                "Rtabmap/ImagesAlreadyRectified": "true",
            },
        ],
        remappings=rtabmap_remappings,
        arguments=["--ros-args", "--log-level", log_level],
    )

    rtabmap_viz_node = Node(
        package="rtabmap_viz",
        executable="rtabmap_viz",
        name="rtabmap_viz",
        output="screen",
        condition=IfCondition(launch_viz),
        parameters=[
            rtabmap_params,
            {
                "use_sim_time": use_sim_time,
                "frame_id": "body",
                "odom_frame_id": "",
                "map_frame_id": "map",
                "subscribe_stereo": True,
                "subscribe_odom_info": False,
                "approx_sync": True,
            },
        ],
        remappings=rtabmap_remappings,
        arguments=["--ros-args", "--log-level", log_level],
    )

    delayed_vins = TimerAction(
        period=vins_startup_delay,
        actions=[vins_node],
    )
    delayed_rtabmap = TimerAction(
        period=rtabmap_startup_delay,
        actions=[rtabmap_node, rtabmap_viz_node],
    )

    return LaunchDescription(
        declared_arguments
        + [
            camera_launch,
            wit_imu_launch,
            body_to_camera_tf,
            delayed_vins,
            delayed_rtabmap,
        ]
    )
