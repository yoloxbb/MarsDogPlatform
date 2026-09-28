"""ROS2 ament_python package setup for marsdog_behavior.

This is the single ROS2 package in this repository.
The bionic_dog_bt module is a pure-Python submodule shipped inside this package.
Both packages can be symlinked together into ~/ros2_ws/src.
"""

from setuptools import find_packages, setup

package_name = "marsdog_behavior"

setup(
    name=package_name,
    version="0.2.0",
    maintainer="MarsDog Team",
    maintainer_email="dev@marsdog.local",
    url="https://github.com/yoloxbb/20260702_MarsDogTree",
    packages=["marsdog_behavior", "bionic_dog_bt"],
    data_files=[
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/behavior_tree.launch.py"]),
        ("share/" + package_name + "/config", [
            "config/behaviors.yaml",
            "config/behavior_categories.yaml",
            "config/event_intent_map.yaml",
            "config/intent_action_pool.yaml",
            "config/emotion_behavior_map.yaml",
            "config/legacy_behavior_aliases.yaml",
            "config/voice_engagement.yaml",
        ]),
        ("share/ament_index/resource_index/packages",
         ["resource/marsdog_behavior"]),
    ],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "behavior_tree_node = marsdog_behavior.ros_node:main",
        ],
    },
)
