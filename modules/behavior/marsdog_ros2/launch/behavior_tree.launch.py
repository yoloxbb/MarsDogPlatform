"""Launch behavior_tree_node + mock_action_executor_node.

Usage:
  # 全部启动
  ros2 launch marsdog_ros2 behavior_tree.launch.py

  # 只启动 BT 节点（动作执行器用外部真实节点）
  ros2 launch marsdog_ros2 behavior_tree.launch.py use_mock_executor:=false

Nodes launched:
  /behavior_tree_node   — 候选池 + 仲裁器 + Blackboard + 10Hz BT tick
  /action_executor_node — 虚拟动作执行器（可选，use_mock_executor:=true）
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_mock_executor = LaunchConfiguration("use_mock_executor", default="true")
    tick_rate = LaunchConfiguration("tick_rate", default="0.1")

    return LaunchDescription([
        DeclareLaunchArgument(
            "use_mock_executor",
            default_value="true",
            description="Launch mock action executor (set false if using real executor)",
        ),
        DeclareLaunchArgument(
            "tick_rate",
            default_value="0.1",
            description="BT tick rate in seconds (10Hz default)",
        ),

        # ── Behavior Tree Node ───────────────────────────────────────────
        Node(
            package="marsdog_ros2",
            executable="behavior_tree_node",
            name="behavior_tree_node",
            output="screen",
            parameters=[{
                "tick_rate": tick_rate,
            }],
        ),

        # ── Mock Action Executor (optional) ──────────────────────────────
        Node(
            package="marsdog_ros2",
            executable="action_executor_node",
            name="action_executor_node",
            output="screen",
            condition=use_mock_executor == "true",
        ),
    ])
