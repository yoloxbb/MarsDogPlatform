"""启动 Marsdog 时间、内部需求、情绪和性格节点。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    """生成联调用的四节点启动描述。"""
    timeMode = LaunchConfiguration("time_mode")
    virtualStartTime = LaunchConfiguration("virtual_start_time")
    randomSeed = ParameterValue(LaunchConfiguration("random_seed"), value_type=int)
    timeControllerParameters = {
        "time_mode": timeMode,
        "virtual_start_time": virtualStartTime,
    }
    calculationTimeParameters = {
        "time_mode": timeMode,
        "virtual_start_time": virtualStartTime,
        "random_seed": randomSeed,
    }
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "time_mode",
                default_value="standard_24h",
                description="standard_24h, demo_12h or demo_2h",
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
            Node(
                package="marsdog_behavior",
                executable="time_controller_node",
                name="time_controller_node",
                output="screen",
                parameters=[timeControllerParameters],
            ),
            Node(
                package="marsdog_behavior",
                executable="personality_node",
                name="personality_node",
                output="screen",
            ),
            Node(
                package="marsdog_behavior",
                executable="internal_need_node",
                name="internal_need_node",
                output="screen",
                parameters=[calculationTimeParameters],
            ),
            Node(
                package="marsdog_behavior",
                executable="emotion_engine_node",
                name="emotion_engine_node",
                output="screen",
                parameters=[calculationTimeParameters],
            ),
        ]
    )
