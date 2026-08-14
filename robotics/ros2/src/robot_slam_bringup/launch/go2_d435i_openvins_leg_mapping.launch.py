"""以 base_footprint 启动 GO2 的平面 OpenVINS/RTAB-Map 建图管线."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """创建不嵌套其他 launch 文件的完整建图启动描述."""
    package_share = get_package_share_directory("robot_slam_bringup")

    params_file = LaunchConfiguration("params_file")
    database_path = LaunchConfiguration("database_path")
    delete_db_on_start = LaunchConfiguration("delete_db_on_start")
    use_sim_time = LaunchConfiguration("use_sim_time")
    startup_delay = LaunchConfiguration("startup_delay")
    log_level = LaunchConfiguration("log_level")

    start_realsense = LaunchConfiguration("start_realsense")
    start_wit_imu = LaunchConfiguration("start_wit_imu")
    launch_viz = LaunchConfiguration("launch_viz")
    publish_camera_imu_tf = LaunchConfiguration("publish_camera_imu_tf")

    camera_profile = LaunchConfiguration("camera_profile")
    wit_port = LaunchConfiguration("wit_port")
    wit_baud = LaunchConfiguration("wit_baud")

    frame_id = LaunchConfiguration("frame_id")
    odom_frame_id = LaunchConfiguration("odom_frame_id")
    map_frame_id = LaunchConfiguration("map_frame_id")
    publish_odom_tf = LaunchConfiguration("publish_odom_tf")
    publish_map_tf = LaunchConfiguration("publish_map_tf")
    planar_mode = LaunchConfiguration("planar_mode")

    left_image_topic = LaunchConfiguration("left_image_topic")
    right_image_topic = LaunchConfiguration("right_image_topic")
    left_info_topic = LaunchConfiguration("left_info_topic")
    right_info_topic = LaunchConfiguration("right_info_topic")
    imu_topic = LaunchConfiguration("imu_topic")
    leg_odom_topic = LaunchConfiguration("leg_odom_topic")
    odom_topic = LaunchConfiguration("odom_topic")
    odom_info_topic = LaunchConfiguration("odom_info_topic")

    declared_arguments = [
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(
                package_share,
                "config",
                "go2_d435i_openvins_leg_mapping_optimized.yaml",
            ),
            description="本管线独立使用的优化参数文件。",
        ),
        DeclareLaunchArgument(
            "database_path",
            default_value=os.path.expanduser(
                "~/.ros/rtabmap_go2_openvins_leg_mapping.db"
            ),
            description="RTAB-Map 建图数据库路径。",
        ),
        DeclareLaunchArgument(
            "delete_db_on_start",
            default_value="true",
            description="启动时是否删除同路径旧数据库。",
        ),
        DeclareLaunchArgument(
            "use_sim_time", default_value="false", description="是否使用 /clock。"
        ),
        DeclareLaunchArgument(
            "startup_delay",
            default_value="3.0",
            description="等待相机、IMU 和外部机器人 TF 稳定的秒数。",
        ),
        DeclareLaunchArgument(
            "log_level", default_value="info", description="建图节点日志等级。"
        ),
        DeclareLaunchArgument(
            "start_realsense",
            default_value="false",
            description="是否由本文件直接启动 D435i。",
        ),
        DeclareLaunchArgument(
            "start_wit_imu",
            default_value="false",
            description="是否由本文件直接启动外置 WIT IMU。",
        ),
        DeclareLaunchArgument(
            "launch_viz",
            default_value="false",
            description="是否启动 rtabmap_viz；机器人端默认关闭以节省资源。",
        ),
        DeclareLaunchArgument(
            "publish_camera_imu_tf",
            default_value="true",
            description="是否发布标定的 camera_link 到 imu_link 静态 TF。",
        ),
        DeclareLaunchArgument(
            "camera_profile",
            default_value="640x480x15",
            description="D435i 红外双目分辨率和帧率。",
        ),
        DeclareLaunchArgument(
            "wit_port", default_value="/dev/ttyUSB0", description="WIT IMU 串口。"
        ),
        DeclareLaunchArgument(
            "wit_baud", default_value="115200", description="WIT IMU 波特率。"
        ),
        DeclareLaunchArgument(
            "frame_id",
            default_value="base_footprint",
            description=(
                "OpenVINS/RTAB-Map 平面参考系；必须与 /odom_leg "
                "child_frame_id 一致。"
            ),
        ),
        DeclareLaunchArgument(
            "odom_frame_id", default_value="odom", description="局部里程计坐标系。"
        ),
        DeclareLaunchArgument(
            "map_frame_id", default_value="map", description="全局地图坐标系。"
        ),
        DeclareLaunchArgument(
            "publish_odom_tf",
            default_value="true",
            description="是否由 OpenVINS 发布 odom 到 base_footprint TF。",
        ),
        DeclareLaunchArgument(
            "publish_map_tf",
            default_value="true",
            description="是否由 RTAB-Map 发布 map 到 odom TF。",
        ),
        DeclareLaunchArgument(
            "planar_mode",
            default_value="true",
            description=(
                "是否将发布的里程计和 RTAB-Map 图优化限制为 x/y/yaw；"
                "OpenVINS 内部仍保留完整惯性 6DoF 状态。"
            ),
        ),
        DeclareLaunchArgument(
            "left_image_topic",
            default_value="/camera/camera/infra1/image_rect_raw",
            description="D435i 左红外矫正图像。",
        ),
        DeclareLaunchArgument(
            "right_image_topic",
            default_value="/camera/camera/infra2/image_rect_raw",
            description="D435i 右红外矫正图像。",
        ),
        DeclareLaunchArgument(
            "left_info_topic",
            default_value="/camera/camera/infra1/camera_info",
            description="D435i 左红外 CameraInfo。",
        ),
        DeclareLaunchArgument(
            "right_info_topic",
            default_value="/camera/camera/infra2/camera_info",
            description="D435i 右红外 CameraInfo。",
        ),
        DeclareLaunchArgument(
            "imu_topic",
            default_value="/camera/camera/imu",
            description="OpenVINS 使用的外置 WIT 原始 IMU。",
        ),
        DeclareLaunchArgument(
            "leg_odom_topic",
            default_value="/odom_leg",
            description="用户单独启动的 GO2 足式里程计；本文件不发布它。",
        ),
        DeclareLaunchArgument(
            "odom_topic", default_value="/odom", description="OpenVINS 输出里程计。"
        ),
        DeclareLaunchArgument(
            "odom_info_topic",
            default_value="/odom_info",
            description="OpenVINS 输出给 RTAB-Map 的诊断和特征信息。",
        ),
    ]

    # 只启用红外双目。使用外置 WIT 后关闭 D435i 内置运动模块，
    # 避免之前日志中的 Motion Module hardware failure 及额外 USB/CPU 开销。
    realsense_node = Node(
        condition=IfCondition(start_realsense),
        package="realsense2_camera",
        executable="realsense2_camera_node",
        namespace="camera",
        name="camera",
        output="screen",
        emulate_tty=True,
        parameters=[{
            "enable_color": False,
            "enable_depth": False,
            "enable_infra": False,
            "enable_infra1": True,
            "enable_infra2": True,
            "depth_module.infra_profile": ParameterValue(
                camera_profile, value_type=str
            ),
            "depth_module.infra1_format": "Y8",
            "depth_module.infra2_format": "Y8",
            "depth_module.enable_auto_exposure": True,
            "enable_sync": True,
            "enable_gyro": False,
            "enable_accel": False,
            "enable_motion": False,
            "unite_imu_method": 0,
            "publish_tf": True,
            "tf_publish_rate": 0.0,
            "pointcloud.enable": False,
            "align_depth.enable": False,
            "initial_reset": False,
        }],
        arguments=["--ros-args", "--log-level", log_level],
    )

    wit_imu_node = Node(
        condition=IfCondition(start_wit_imu),
        package="wit_imu",
        executable="wit_imu_node",
        name="wit_imu_node",
        output="screen",
        parameters=[{
            "port": wit_port,
            "baud": ParameterValue(wit_baud, value_type=int),
            "frame_id": "imu_link",
            "topic": imu_topic,
            "filtered_topic": "/imu/data_filtered",
            "enable_low_pass": True,
            "low_pass_cutoff_hz": 20.0,
            "expected_rate_hz": 200.0,
            "qos_depth": 5,
            "poll_timeout_ms": 500,
            "serial_data_timeout_ms": 2000,
            "reconnect_delay_ms": 1000,
            "timestamp_resync_threshold_ms": 20.0,
            "angular_velocity_covariance": 0.0,
            "linear_acceleration_covariance": 0.0,
        }],
    )

    # 2026-08-03 16:45 Kalibr 标定；时间偏移由参数文件中的
    # imu_lookahead 和 OpenVINS 在线 CalibCamTimeoffset 处理。
    camera_to_wit_imu_tf = Node(
        condition=IfCondition(publish_camera_imu_tf),
        package="tf2_ros",
        executable="static_transform_publisher",
        name="d435i_camera_to_wit_imu_20260803",
        output="screen",
        arguments=[
            "--x", "-0.03453964436591465",
            "--y", "-0.020484129171029215",
            "--z", "0.00486747161468371",
            "--qx", "0.7052099474822251",
            "--qy", "-0.011074111237417432",
            "--qz", "-0.7087317863872082",
            "--qw", "0.015985899937620437",
            "--frame-id", "camera_link",
            "--child-frame-id", "imu_link",
        ],
    )

    odometry_remappings = [
        ("left/image_rect", left_image_topic),
        ("right/image_rect", right_image_topic),
        ("left/camera_info", left_info_topic),
        ("right/camera_info", right_info_topic),
        ("imu", imu_topic),
        ("leg_odom", leg_odom_topic),
        ("odom", odom_topic),
        ("odom_info", odom_info_topic),
    ]
    mapping_remappings = [
        ("left/image_rect", left_image_topic),
        ("right/image_rect", right_image_topic),
        ("left/camera_info", left_info_topic),
        ("right/camera_info", right_info_topic),
        ("odom", odom_topic),
        ("odom_info", odom_info_topic),
    ]

    openvins_odometry_node = Node(
        package="rtabmap_odom",
        executable="stereo_odometry",
        name="openvins_stereo_odometry",
        output="screen",
        emulate_tty=True,
        parameters=[
            params_file,
            {
                "use_sim_time": use_sim_time,
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "publish_tf": ParameterValue(publish_odom_tf, value_type=bool),
                "Reg/Force3DoF": ParameterValue(planar_mode, value_type=str),
            },
        ],
        remappings=odometry_remappings,
        arguments=["--ros-args", "--log-level", log_level],
    )

    rtabmap_node = Node(
        package="rtabmap_slam",
        executable="rtabmap",
        name="rtabmap",
        output="screen",
        emulate_tty=True,
        parameters=[
            params_file,
            {
                "use_sim_time": use_sim_time,
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "map_frame_id": map_frame_id,
                "publish_tf": ParameterValue(publish_map_tf, value_type=bool),
                "database_path": database_path,
                "delete_db_on_start": ParameterValue(
                    delete_db_on_start, value_type=bool
                ),
                "Reg/Force3DoF": ParameterValue(planar_mode, value_type=str),
            },
        ],
        remappings=mapping_remappings,
        arguments=["--ros-args", "--log-level", log_level],
    )

    rtabmap_viz_node = Node(
        condition=IfCondition(launch_viz),
        package="rtabmap_viz",
        executable="rtabmap_viz",
        name="rtabmap_viz",
        output="screen",
        parameters=[
            params_file,
            {
                "use_sim_time": use_sim_time,
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "map_frame_id": map_frame_id,
            },
        ],
        remappings=mapping_remappings,
        arguments=["--ros-args", "--log-level", log_level],
    )

    # /odom_leg 和 robot_state_publisher 由用户先行启动；本文件不创建它们。
    # planar_mode=true 时，/odom_leg.child_frame_id 必须为 base_footprint，且
    # TF 树中只能由 OpenVINS 发布 odom -> base_footprint。
    delayed_mapping = TimerAction(
        period=startup_delay,
        actions=[openvins_odometry_node, rtabmap_node, rtabmap_viz_node],
    )

    return LaunchDescription(
        declared_arguments
        + [
            realsense_node,
            wit_imu_node,
            camera_to_wit_imu_tf,
            delayed_mapping,
        ]
    )
