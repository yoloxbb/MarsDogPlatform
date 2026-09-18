from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    share = FindPackageShare("marsdog_vision_interaction")
    config_path = LaunchConfiguration("config_path")
    fastdds_profile = LaunchConfiguration("fastdds_profile")
    log_level = LaunchConfiguration("log_level")
    log_dir = LaunchConfiguration("log_dir")
    pose_model_variant = LaunchConfiguration("pose_model_variant")
    landmarker_running_mode = LaunchConfiguration("landmarker_running_mode")
    face_api_host = LaunchConfiguration("face_api_host")
    face_api_port = LaunchConfiguration("face_api_port")
    test_run_id = LaunchConfiguration("test_run_id")
    test_case_id = LaunchConfiguration("test_case_id")
    return LaunchDescription([
        DeclareLaunchArgument(
            "config_path",
            default_value=PathJoinSubstitution([share, "config", "vision.yaml"]),
        ),
        DeclareLaunchArgument(
            "fastdds_profile",
            default_value=PathJoinSubstitution([share, "config", "fastdds.xml"]),
        ),
        SetEnvironmentVariable(
            name="RMW_IMPLEMENTATION", value="rmw_fastrtps_cpp"
        ),
        SetEnvironmentVariable(
            name="FASTRTPS_DEFAULT_PROFILES_FILE", value=fastdds_profile
        ),
        SetEnvironmentVariable(
            name="RMW_FASTRTPS_USE_QOS_FROM_XML", value="0"
        ),
        DeclareLaunchArgument("log_level", default_value="INFO"),
        DeclareLaunchArgument("log_dir", default_value="log"),
        DeclareLaunchArgument("pose_model_variant", default_value=""),
        DeclareLaunchArgument("landmarker_running_mode", default_value=""),
        DeclareLaunchArgument("face_api_host", default_value=""),
        DeclareLaunchArgument("face_api_port", default_value="0"),
        DeclareLaunchArgument("test_run_id", default_value=""),
        DeclareLaunchArgument("test_case_id", default_value=""),
        Node(
            package="marsdog_vision_interaction",
            executable="vision_interaction",
            name="vision_interaction",
            output="screen",
            parameters=[{
                "config_path": config_path,
                "log_level": log_level,
                "log_dir": log_dir,
                "pose_model_variant": pose_model_variant,
                "landmarker_running_mode": landmarker_running_mode,
                "face_api_host": ParameterValue(
                    face_api_host, value_type=str
                ),
                "face_api_port": face_api_port,
                "test_run_id": ParameterValue(test_run_id, value_type=str),
                "test_case_id": ParameterValue(test_case_id, value_type=str),
            }],
        ),
    ])
