"""marsdog_ros2 — ROS2 nodes for the bionic dog behavior tree.

Nodes:
  /behavior_tree_node       — Main BT runtime, subscribes to signals, ticks tree
  /action_executor_node     — Mock Action Server for /execute_behavior

Run without ROS2:
  uv run python -m marsdog_ros2.standalone_demo
"""

__version__ = "0.1.0"
