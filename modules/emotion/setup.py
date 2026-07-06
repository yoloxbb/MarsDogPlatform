"""ROS2 ament_python 安装入口。"""

from glob import glob

from setuptools import find_packages, setup


PACKAGE_NAME = "marsdog_behavior"


setup(
    name=PACKAGE_NAME,
    version="0.1.0",
    packages=find_packages(include=["marsdog_core", "marsdog_core.*", "marsdog_ros2", "marsdog_ros2.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{PACKAGE_NAME}"]),
        (f"share/{PACKAGE_NAME}", ["package.xml"]),
        (f"share/{PACKAGE_NAME}/configs", glob("configs/*.yaml")),
        (f"share/{PACKAGE_NAME}/launch", glob("marsdog_ros2/launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=False,
    maintainer="Marsdog Team",
    maintainer_email="dev@marsdog.local",
    description="Marsdog internal need and emotion calculation nodes.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "internal_need_node = marsdog_ros2.internal_need_node:main",
            "emotion_engine_node = marsdog_ros2.emotion_engine_node:main",
            "personality_node = marsdog_ros2.personality_node:main",
        ],
    },
)
