"""启动 Marsdog 内部需求、情绪和性格计算节点。"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """生成联调用的三节点启动描述。"""
    return LaunchDescription(
        [
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
            ),
            Node(
                package="marsdog_behavior",
                executable="emotion_engine_node",
                name="emotion_engine_node",
                output="screen",
            ),
        ]
    )
