import os

from setuptools import find_packages, setup

package_name = 'waypoint_nav'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), ['launch/waypoint_nav.launch.py']),
        (os.path.join('share', package_name, 'docs'), ['docs/INTERFACE.md']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='xx',
    maintainer_email='xx@example.com',
    description='点位与随机目标导航：匹配 waypoints.yaml 或实时地图，下发 Nav2 NavigateToPose。',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'waypoint_nav_dispatcher = waypoint_nav.waypoint_nav_dispatcher:main',
        ],
    },
)
