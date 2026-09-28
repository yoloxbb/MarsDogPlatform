"""marsdog_behavior — MarsDog Behavior Tree ROS2 package.

The central decision-making node in the MarsDog behavior stack.
Depends on marsdog_interfaces for ROS2 action/msg/srv definitions.

Internal modules:
  bionic_dog_bt/  — Pure Python behavior tree framework (co-located)

Nodes:
  /behavior_tree_node  — Main BT runtime, subscribes to signals, ticks tree

Run without ROS2:
  uv run python -m marsdog_behavior.standalone_demo
"""

__version__ = "0.2.0"
