"""单独启动全迹 ONE1000 摸头事件适配节点。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    """生成 ONE1000 独立硬件联调启动描述。"""
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "serial_port",
                default_value="/dev/ttyUSB1",
                description="ONE1000 serial device path",
            ),
            DeclareLaunchArgument(
                "auto_start_sentry",
                default_value="true",
                description="Configure and start ONE1000 sentry automatically",
            ),
            DeclareLaunchArgument(
                "touch_threshold",
                default_value="30",
                description="ONE1000 head-touch threshold",
            ),
            DeclareLaunchArgument(
                "touch_cooldown_seconds",
                default_value="1.0",
                description="Real-time cooldown between head-pet events",
            ),
            Node(
                package="marsdog_need_emotion",
                executable="one1000_tactile_node",
                name="one1000_tactile_node",
                output="screen",
                parameters=[
                    {
                        "serial_port": LaunchConfiguration("serial_port"),
                        "auto_start_sentry": ParameterValue(
                            LaunchConfiguration("auto_start_sentry"),
                            value_type=bool,
                        ),
                        "touch_threshold": ParameterValue(
                            LaunchConfiguration("touch_threshold"),
                            value_type=int,
                        ),
                        "touch_cooldown_seconds": ParameterValue(
                            LaunchConfiguration("touch_cooldown_seconds"),
                            value_type=float,
                        ),
                    }
                ],
            ),
        ]
    )
