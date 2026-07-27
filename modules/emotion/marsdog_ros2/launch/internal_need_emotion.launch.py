"""启动 Marsdog 时间、内部需求、情绪和性格节点。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    """生成联调用的四节点启动描述。"""
    timeScale = ParameterValue(LaunchConfiguration("time_scale"), value_type=int)
    virtualStartTime = LaunchConfiguration("virtual_start_time")
    randomSeed = ParameterValue(LaunchConfiguration("random_seed"), value_type=int)
    midnightAccelerationEnabled = ParameterValue(
        LaunchConfiguration("midnight_acceleration_enabled"),
        value_type=bool,
    )
    midnightDurationSeconds = ParameterValue(
        LaunchConfiguration("midnight_duration_seconds"),
        value_type=float,
    )
    timeControllerParameters = {
        "time_scale": timeScale,
        "virtual_start_time": virtualStartTime,
        "midnight_acceleration_enabled": midnightAccelerationEnabled,
        "midnight_duration_seconds": midnightDurationSeconds,
    }
    calculationTimeParameters = {
        "time_scale": timeScale,
        "virtual_start_time": virtualStartTime,
        "random_seed": randomSeed,
    }
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "time_scale",
                default_value="1",
                description="Virtual time scale: integer from 1 to 100",
            ),
            DeclareLaunchArgument(
                "virtual_start_time",
                default_value="auto",
                description="Virtual start time: auto or HH:MM",
            ),
            DeclareLaunchArgument(
                "random_seed",
                default_value="-1",
                description="Random seed: -1 or a non-negative integer",
            ),
            DeclareLaunchArgument(
                "midnight_acceleration_enabled",
                default_value="false",
                description="Accelerate every virtual 00:00-06:00 window",
            ),
            DeclareLaunchArgument(
                "midnight_duration_seconds",
                default_value="30.0",
                description="Real seconds used for virtual 00:00-06:00",
            ),
            Node(
                package="marsdog_need_emotion",
                executable="time_controller_node",
                name="time_controller_node",
                output="screen",
                parameters=[timeControllerParameters],
            ),
            Node(
                package="marsdog_need_emotion",
                executable="personality_node",
                name="personality_node",
                output="screen",
            ),
            Node(
                package="marsdog_need_emotion",
                executable="internal_need_node",
                name="internal_need_node",
                output="screen",
                parameters=[calculationTimeParameters],
            ),
            Node(
                package="marsdog_need_emotion",
                executable="emotion_engine_node",
                name="emotion_engine_node",
                output="screen",
                parameters=[calculationTimeParameters],
            ),
        ]
    )
