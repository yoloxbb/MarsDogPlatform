"""启动可复用的 OpenVINS 双目里程计和 RTAB-Map 管线。"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


THIS_DIR = os.path.dirname(__file__)
DEFAULT_CONFIG_DIR = os.path.normpath(os.path.join(THIS_DIR, "..", "config"))


def generate_launch_description():
    """同时启动 OpenVINS、RTAB-Map 建图/重定位节点和可视化节点。"""
    params_file = LaunchConfiguration("params_file")
    openvins_config_path = LaunchConfiguration("openvins_config_path")
    namespace = LaunchConfiguration("namespace")
    use_sim_time = LaunchConfiguration("use_sim_time")
    log_level = LaunchConfiguration("log_level")

    frame_id = LaunchConfiguration("frame_id")
    odom_frame_id = LaunchConfiguration("odom_frame_id")
    map_frame_id = LaunchConfiguration("map_frame_id")
    publish_odom_tf = LaunchConfiguration("publish_odom_tf")
    publish_map_tf = LaunchConfiguration("publish_map_tf")
    planar_mode = LaunchConfiguration("planar_mode")
    localization = LaunchConfiguration("localization")

    left_image_topic = LaunchConfiguration("left_image_topic")
    right_image_topic = LaunchConfiguration("right_image_topic")
    left_info_topic = LaunchConfiguration("left_info_topic")
    right_info_topic = LaunchConfiguration("right_info_topic")
    odom_left_image_topic = LaunchConfiguration("odom_left_image_topic")
    odom_right_image_topic = LaunchConfiguration("odom_right_image_topic")
    odom_left_info_topic = LaunchConfiguration("odom_left_info_topic")
    odom_right_info_topic = LaunchConfiguration("odom_right_info_topic")
    odom_images_already_rectified = LaunchConfiguration(
        "odom_images_already_rectified")
    imu_topic = LaunchConfiguration("imu_topic")
    orientation_imu_topic = LaunchConfiguration("orientation_imu_topic")
    odom_topic = LaunchConfiguration("odom_topic")
    odom_info_topic = LaunchConfiguration("odom_info_topic")
    map_topic = LaunchConfiguration("map_topic")
    local_grid_obstacle_topic = LaunchConfiguration(
        "local_grid_obstacle_topic")
    local_grid_ground_topic = LaunchConfiguration("local_grid_ground_topic")

    database_path = LaunchConfiguration("database_path")
    delete_db_on_start = LaunchConfiguration("delete_db_on_start")
    launch_viz = LaunchConfiguration("launch_viz")

    declared_arguments = [
        DeclareLaunchArgument(
            "namespace", default_value="", description="ROS2 namespace。"),
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="false",
            description="是否使用仿真时间。",
        ),
        DeclareLaunchArgument(
            "log_level", default_value="info", description="节点日志等级。"),
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(
                DEFAULT_CONFIG_DIR, "rtabmap_openvins_mapping_params.yaml"),
            description="RTAB-Map + OpenVINS 参数文件。",
        ),
        DeclareLaunchArgument(
            "openvins_config_path",
            default_value="",
            description=(
                "可选：OpenVINS 原生 yaml。非空时会覆盖 "
                "OdomOpenVINS/* 中同名参数。"
            ),
        ),
        DeclareLaunchArgument(
            "frame_id",
            default_value="camera_link",
            description="机器人基坐标系。",
        ),
        DeclareLaunchArgument(
            "odom_frame_id",
            default_value="odom",
            description="局部里程计坐标系。",
        ),
        DeclareLaunchArgument(
            "map_frame_id",
            default_value="map",
            description="全局地图坐标系。",
        ),
        DeclareLaunchArgument(
            "publish_odom_tf",
            default_value="true",
            description="是否由 OpenVINS 发布 odom 到机体的 TF。",
        ),
        DeclareLaunchArgument(
            "publish_map_tf",
            default_value="true",
            description="是否由 RTAB-Map 发布 map 到 odom 的 TF。",
        ),
        DeclareLaunchArgument(
            "planar_mode",
            default_value="false",
            description=(
                "true 时将里程计和地图限制为 x/y/yaw；"
                "默认 false 保持 HB 原有 6DoF 行为。"
            ),
        ),
        DeclareLaunchArgument(
            "localization",
            default_value="false",
            description="false 为建图，true 为使用已有数据库重定位。",
        ),
        DeclareLaunchArgument(
            "left_image_topic",
            default_value="/camera/camera/infra1/image_rect_raw",
            description="左目校正图像话题。",
        ),
        DeclareLaunchArgument(
            "right_image_topic",
            default_value="/camera/camera/infra2/image_rect_raw",
            description="右目校正图像话题。",
        ),
        DeclareLaunchArgument(
            "left_info_topic",
            default_value="/camera/camera/infra1/camera_info_kalibr",
            description="左目 CameraInfo 话题。",
        ),
        DeclareLaunchArgument(
            "right_info_topic",
            default_value="/camera/camera/infra2/camera_info_kalibr",
            description="右目 CameraInfo 话题。",
        ),
        DeclareLaunchArgument(
            "odom_left_image_topic",
            default_value=left_image_topic,
            description=(
                "OpenVINS 左目图像话题；默认与建图话题一致，"
                "使用原始相机外参时可单独传入未矫正图像。"
            ),
        ),
        DeclareLaunchArgument(
            "odom_right_image_topic",
            default_value=right_image_topic,
            description=(
                "OpenVINS 右目图像话题；默认与建图话题一致，"
                "使用原始相机外参时可单独传入未矫正图像。"
            ),
        ),
        DeclareLaunchArgument(
            "odom_left_info_topic",
            default_value=left_info_topic,
            description=(
                "OpenVINS 左目 CameraInfo；"
                "应与其图像和外参属于同一原始坐标系。"
            ),
        ),
        DeclareLaunchArgument(
            "odom_right_info_topic",
            default_value=right_info_topic,
            description=(
                "OpenVINS 右目 CameraInfo；"
                "应与其图像和外参属于同一原始坐标系。"
            ),
        ),
        DeclareLaunchArgument(
            "odom_images_already_rectified",
            default_value="true",
            description=(
                "OpenVINS 输入是否已矫正；false 时使用 CameraInfo 原始 K/D "
                "和原始相机 TF。"
            ),
        ),
        DeclareLaunchArgument(
            "imu_topic",
            default_value="/camera/camera/imu",
            description="OpenVINS 使用的原始 IMU 话题。",
        ),
        DeclareLaunchArgument(
            "orientation_imu_topic",
            # 默认沿用 imu_topic，保证 HB 不传该参数时保持原来的重映射。
            default_value=imu_topic,
            description=(
                "RTAB-Map 使用的带 orientation IMU；"
                "原始 IMU 无姿态时应传入一个未发布话题。"
            ),
        ),
        DeclareLaunchArgument(
            "odom_topic",
            default_value="/odom",
            description="OpenVINS 输出里程计话题。",
        ),
        DeclareLaunchArgument(
            "odom_info_topic",
            default_value="/odom_info",
            description=(
                "OpenVINS odometry info 话题，"
                "RTAB-Map 用它读取特征/内点统计。"
            ),
        ),
        DeclareLaunchArgument(
            "map_topic",
            default_value="map",
            description="RTAB-Map 输出地图话题。",
        ),
        DeclareLaunchArgument(
            "local_grid_obstacle_topic",
            default_value="local_grid_obstacle",
            description="RTAB-Map 输出局部障碍物点云话题。",
        ),
        DeclareLaunchArgument(
            "local_grid_ground_topic",
            default_value="local_grid_ground",
            description="RTAB-Map 输出局部地面点云话题。",
        ),
        DeclareLaunchArgument(
            "database_path",
            default_value=os.path.expanduser(
                "~/.ros/rtabmap_openvins_mapping.db"),
            description="RTAB-Map 数据库路径。",
        ),
        DeclareLaunchArgument(
            "delete_db_on_start",
            default_value="true",
            description="启动时是否删除旧地图。",
        ),
        DeclareLaunchArgument(
            "launch_viz",
            default_value="true",
            description="是否启动 rtabmap_viz。",
        ),
    ]

    # OpenVINS 双目惯性里程计节点。
    openvins_odometry_node = Node(
        package="rtabmap_odom",
        executable="stereo_odometry",
        name="openvins_stereo_odometry",
        namespace=namespace,
        # 同时写屏幕和 launch 进程日志，确保 OpenVINS 原生诊断可在运行后复查。
        output="both",
        emulate_tty=True,
        parameters=[
            params_file,
            {
                "use_sim_time": use_sim_time,
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "publish_tf": ParameterValue(
                    publish_odom_tf, value_type=bool),
                "OdomOpenVINS/ConfigPath": openvins_config_path,
                # RTAB-Map core 参数在 ROS 2 中按字符串传递。
                "Reg/Force3DoF": ParameterValue(
                    planar_mode, value_type=str),
                "Rtabmap/ImagesAlreadyRectified": ParameterValue(
                    odom_images_already_rectified, value_type=str),
            },
        ],
        remappings=[
            # OpenVINS 可以直接处理原始 radtan/equidistant 图像。
            # 独立话题避免把矫正图像射线和原始相机外参混用。
            ("left/image_rect", odom_left_image_topic),
            ("right/image_rect", odom_right_image_topic),
            ("left/camera_info", odom_left_info_topic),
            ("right/camera_info", odom_right_info_topic),
            ("imu", imu_topic),
            ("odom", odom_topic),
            ("odom_info", odom_info_topic),
        ],
        # --uinfo 打开 RTAB-Map core/OpenVINS 的 INFO 输出；ROS 日志等级仍由 log_level 控制。
        arguments=["--uinfo", "--ros-args", "--log-level", log_level],
    )

    rtabmap_common_parameters = [
        params_file,
        {
            "use_sim_time": use_sim_time,
            "frame_id": frame_id,
            "odom_frame_id": odom_frame_id,
            "map_frame_id": map_frame_id,
            "publish_tf": ParameterValue(publish_map_tf, value_type=bool),
            "database_path": database_path,
            "Reg/Force3DoF": ParameterValue(
                planar_mode, value_type=str),
        },
    ]
    rtabmap_remappings = [
        ("left/image_rect", left_image_topic),
        ("right/image_rect", right_image_topic),
        ("left/camera_info", left_info_topic),
        ("right/camera_info", right_info_topic),
        ("imu", orientation_imu_topic),
        ("odom", odom_topic),
        ("odom_info", odom_info_topic),
        ("map", map_topic),
        ("local_grid_obstacle", local_grid_obstacle_topic),
        ("local_grid_ground", local_grid_ground_topic),
    ]

    # 默认建图节点保持 HB 原有的增量建图行为。
    rtabmap_mapping_node = Node(
        condition=UnlessCondition(localization),
        package="rtabmap_slam",
        executable="rtabmap",
        name="rtabmap",
        namespace=namespace,
        output="screen",
        parameters=rtabmap_common_parameters + [{
            "delete_db_on_start": ParameterValue(
                delete_db_on_start, value_type=bool),
            "Mem/IncrementalMemory": "true",
            "Mem/InitWMWithAllNodes": "false",
            "Mem/LocalizationReadOnly": "false",
        }],
        remappings=rtabmap_remappings,
        arguments=["--ros-args", "--log-level", log_level],
    )

    # 重定位模式禁止删除数据库，并关闭增量记忆，避免增加新地图节点。
    rtabmap_localization_node = Node(
        condition=IfCondition(localization),
        package="rtabmap_slam",
        executable="rtabmap",
        name="rtabmap",
        namespace=namespace,
        output="screen",
        parameters=rtabmap_common_parameters + [{
            "delete_db_on_start": False,
            "Mem/IncrementalMemory": "false",
            "Mem/InitWMWithAllNodes": "true",
            # RTAB-Map 0.23.8 仍需写入数据库 Info 表，不能使用只读模式。
            "Mem/LocalizationReadOnly": "false",
        }],
        remappings=rtabmap_remappings,
        arguments=["--ros-args", "--log-level", log_level],
    )

    # 可视化节点。
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
        remappings=rtabmap_remappings,
        arguments=["--ros-args", "--log-level", log_level],
    )

    return LaunchDescription(
        declared_arguments
        + [
            openvins_odometry_node,
            rtabmap_mapping_node,
            rtabmap_localization_node,
            rtabmap_viz_node,
        ]
    )
