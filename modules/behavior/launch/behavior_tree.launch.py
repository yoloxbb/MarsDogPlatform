"""Launch behavior_tree_node.

Usage:
  ros2 launch marsdog_behavior behavior_tree.launch.py

Nodes launched:
  /behavior_tree_node  — candidate pool + arbiter + blackboard + 10Hz BT tick

Note: The action executor (marsdog_action_executor) is a separate project
and should be launched independently.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    tick_rate = LaunchConfiguration("tick_rate", default="0.1")

    return LaunchDescription([
        DeclareLaunchArgument(
            "tick_rate",
            default_value="0.1",
            description="BT tick rate in seconds (10Hz default)",
        ),

        Node(
            package="marsdog_behavior",
            executable="behavior_tree_node",
            name="behavior_tree_node",
            output="screen",
            parameters=[{
                "tick_rate": tick_rate,
            }],
        ),
    ])
