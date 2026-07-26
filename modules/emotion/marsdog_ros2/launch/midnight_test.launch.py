"""在可配置真实时长内运行虚拟 00:00-06:00 凌晨场景。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, RegisterEventHandler, Shutdown
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    """生成凌晨场景时间源、性格、需求和情绪节点启动描述。"""
    randomSeed = ParameterValue(LaunchConfiguration("random_seed"), value_type=int)
    scenarioDuration = ParameterValue(
        LaunchConfiguration("scenario_duration_seconds"),
        value_type=float,
    )
    completionHold = ParameterValue(
        LaunchConfiguration("completion_hold_seconds"),
        value_type=float,
    )
    autoStartSleep = ParameterValue(
        LaunchConfiguration("auto_start_sleep"),
        value_type=bool,
    )
    calculationParameters = {
        "time_scale": 24,
        "virtual_start_time": "00:00",
        "random_seed": randomSeed,
    }
    scenarioNode = Node(
        package="marsdog_need_emotion",
        executable="midnight_test_node",
        name="midnight_test_node",
        output="screen",
        parameters=[
            {
                "scenario_duration_seconds": scenarioDuration,
                "completion_hold_seconds": completionHold,
                "auto_start_sleep": autoStartSleep,
            }
        ],
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "scenario_duration_seconds",
                default_value="30.0",
                description="Real seconds used to run virtual 00:00-06:00",
            ),
            DeclareLaunchArgument(
                "completion_hold_seconds",
                default_value="2.0",
                description="Real seconds to wait for the final need state",
            ),
            DeclareLaunchArgument(
                "auto_start_sleep",
                default_value="true",
                description="Automatically publish ACTION_SLEEP STARTED",
            ),
            DeclareLaunchArgument(
                "random_seed",
                default_value="12345",
                description="Random seed used by calculation nodes",
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
                parameters=[calculationParameters],
            ),
            Node(
                package="marsdog_need_emotion",
                executable="emotion_engine_node",
                name="emotion_engine_node",
                output="screen",
                parameters=[calculationParameters],
            ),
            scenarioNode,
            RegisterEventHandler(
                OnProcessExit(
                    target_action=scenarioNode,
                    on_exit=[
                        Shutdown(
                            reason="Midnight test scenario finished",
                        )
                    ],
                )
            ),
        ]
    )
