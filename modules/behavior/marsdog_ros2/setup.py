"""ROS2 ament_python package setup for marsdog_ros2."""

from setuptools import find_packages, setup

package_name = "marsdog_ros2"

setup(
    name=package_name,
    version="0.1.0",
    packages=["marsdog_ros2"],
    data_files=[
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/behavior_tree.launch.py"]),
        ("share/" + package_name + "/msg", [
            "msg/BehaviorSignal.msg",
            "msg/BehaviorFeedback.msg",
        ]),
        ("share/" + package_name + "/action", [
            "action/ExecuteBehavior.action",
        ]),
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "behavior_tree_node = marsdog_ros2.behavior_tree_node:main",
            "action_executor_node = marsdog_ros2.mock_action_executor_node:main",
        ],
    },
)
