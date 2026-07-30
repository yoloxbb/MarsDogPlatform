import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


THIS_DIR = os.path.dirname(__file__)
DEFAULT_CONFIG_DIR = os.path.normpath(os.path.join(THIS_DIR, "..", "config"))


def generate_launch_description():
    """启动单目前端 OpenVINS 与 RTAB-Map 建图兼容流程。"""
    params_file = LaunchConfiguration("params_file")
    openvins_config_path = LaunchConfiguration("openvins_config_path")
    namespace = LaunchConfiguration("namespace")
    use_sim_time = LaunchConfiguration("use_sim_time")
    log_level = LaunchConfiguration("log_level")

    frame_id = LaunchConfiguration("frame_id")
    odom_frame_id = LaunchConfiguration("odom_frame_id")
    map_frame_id = LaunchConfiguration("map_frame_id")

    image_topic = LaunchConfiguration("image_topic")
    camera_info_topic = LaunchConfiguration("camera_info_topic")
    right_image_topic = LaunchConfiguration("right_image_topic")
    right_camera_info_topic = LaunchConfiguration("right_camera_info_topic")
    imu_topic = LaunchConfiguration("imu_topic")
    odom_topic = LaunchConfiguration("odom_topic")
    odom_info_topic = LaunchConfiguration("odom_info_topic")

    database_path = LaunchConfiguration("database_path")
    delete_db_on_start = LaunchConfiguration("delete_db_on_start")
    launch_mapping = LaunchConfiguration("launch_mapping")
    launch_viz = LaunchConfiguration("launch_viz")

    odometry_package = LaunchConfiguration("odometry_package")
    odometry_executable = LaunchConfiguration("odometry_executable")

    declared_arguments = [
        DeclareLaunchArgument("namespace", default_value="", description="ROS2 命名空间。"),
        DeclareLaunchArgument("use_sim_time", default_value="false", description="是否使用仿真时间。"),
        DeclareLaunchArgument("log_level", default_value="info", description="节点日志等级。"),
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(DEFAULT_CONFIG_DIR, "rtabmap_openvins_mono_frontend_params.yaml"),
            description="RTAB-Map core OpenVINS 单目前端参数文件。",
        ),
        DeclareLaunchArgument(
            "openvins_config_path",
            default_value="",
            description="可选：OpenVINS 原生 yaml。非空时会覆盖 OdomOpenVINS/* 同名参数。",
        ),
        DeclareLaunchArgument("frame_id", default_value="camera_link", description="机器人/相机基坐标系。"),
        DeclareLaunchArgument("odom_frame_id", default_value="odom", description="局部里程计坐标系。"),
        DeclareLaunchArgument("map_frame_id", default_value="map", description="全局地图坐标系。"),
        DeclareLaunchArgument(
            "image_topic",
            default_value="/camera/camera/infra1/image_rect_raw",
            description="OpenVINS 单目前端图像话题，默认使用 RealSense 左红外矫正图。",
        ),
        DeclareLaunchArgument(
            "camera_info_topic",
            default_value="/camera/camera/infra1/camera_info",
            description="OpenVINS 单目前端 CameraInfo 话题，必须和 image_topic 同一相机。",
        ),
        DeclareLaunchArgument(
            "right_image_topic",
            default_value="/camera/camera/infra2/image_rect_raw",
            description="RTAB-Map 双目建图右目图像话题。OpenVINS 单目前端不会使用它。",
        ),
        DeclareLaunchArgument(
            "right_camera_info_topic",
            default_value="/camera/camera/infra2/camera_info",
            description="RTAB-Map 双目建图右目 CameraInfo 话题。OpenVINS 单目前端不会使用它。",
        ),
        DeclareLaunchArgument("imu_topic", default_value="/camera/camera/imu", description="RealSense IMU 话题。"),
        DeclareLaunchArgument("odom_topic", default_value="/odom", description="OpenVINS 前端输出里程计话题。"),
        DeclareLaunchArgument("odom_info_topic", default_value="/odom_info", description="OpenVINS 前端调试信息话题。"),
        DeclareLaunchArgument(
            "database_path",
            default_value=os.path.expanduser("~/.ros/rtabmap_openvins_mono_stereo_mapping.db"),
            description="RTAB-Map 数据库路径。",
        ),
        DeclareLaunchArgument("delete_db_on_start", default_value="true", description="启动时是否删除旧地图。"),
        DeclareLaunchArgument("launch_mapping", default_value="true", description="是否启动 RTAB-Map 双目建图节点。"),
        DeclareLaunchArgument("launch_viz", default_value="true", description="是否启动 rtabmap_viz。"),
        DeclareLaunchArgument(
            "odometry_package",
            default_value="rtabmap_openvins_mono",
            description="单目 wrapper 所在包。默认仍写 rtabmap_odom，方便你后续补 mono_odometry 可执行。",
        ),
        DeclareLaunchArgument(
            "odometry_executable",
            default_value="mono_odometry",
            description="单目 OpenVINS wrapper 可执行名。rtabmap_ros 常规安装通常没有这个可执行，需要你自己补 wrapper。",
        ),
    ]

    # 单目 OpenVINS 前端节点：
    openvins_odometry_node = Node(
        package=odometry_package,
        executable=odometry_executable,
        name="openvins_mono_odometry",
        namespace=namespace,
        output="screen",
        parameters=[
            params_file,
            {
                "use_sim_time": use_sim_time,
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "OdomOpenVINS/ConfigPath": openvins_config_path,
            },
        ],
        remappings=[
            ("image", image_topic),
            ("camera_info", camera_info_topic),
            ("imu", imu_topic),
            ("odom", odom_topic),
            ("odom_info", odom_info_topic),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    # RTAB-Map 双目建图节点：
    # 继续订阅左右目和 OpenVINS 发布的 /odom，用双目深度建图，但不直接订阅 RealSense 原始 IMU。
    rtabmap_node = Node(
        package="rtabmap_slam",
        executable="rtabmap",
        name="rtabmap",
        namespace=namespace,
        output="screen",
        condition=IfCondition(launch_mapping),
        parameters=[
            params_file,
            {
                "use_sim_time": use_sim_time,
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "map_frame_id": map_frame_id,
                "database_path": database_path,
                "delete_db_on_start": delete_db_on_start,
            },
        ],
        remappings=[
            ("left/image_rect", image_topic),
            ("right/image_rect", right_image_topic),
            ("left/camera_info", camera_info_topic),
            ("right/camera_info", right_camera_info_topic),
            ("odom", odom_topic),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    # 可视化节点：
    rtabmap_viz_node = Node(
        package="rtabmap_viz",
        executable="rtabmap_viz",
        name="rtabmap_viz",
        namespace=namespace,
        output="screen",
        condition=IfCondition(launch_viz),
        parameters=[
            params_file,
            {
                "use_sim_time": use_sim_time,
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "map_frame_id": map_frame_id,
            },
        ],
        remappings=[
            ("left/image_rect", image_topic),
            ("right/image_rect", right_image_topic),
            ("left/camera_info", camera_info_topic),
            ("right/camera_info", right_camera_info_topic),
            ("odom", odom_topic),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    return LaunchDescription(
        declared_arguments
        + [
            openvins_odometry_node,
            rtabmap_node,
            rtabmap_viz_node,
        ]
    )
