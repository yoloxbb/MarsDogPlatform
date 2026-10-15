import os
from glob import glob

from setuptools import find_packages, setup


package_name = 'robot_slam_bringup'


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        ('share/' + package_name, ['package.xml', 'README.md']),
        (
            os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py'),
        ),
        (
            os.path.join('share', package_name, 'config'),
            glob('config/*.yaml') + glob('config/*.xml'),
        ),
        (
            os.path.join('share', package_name, 'config', 'robots'),
            glob('config/robots/*.yaml'),
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='yahboom',
    maintainer_email='your.email@example.com',
    description='Lite3, GO2 and Cyvet D435i stereo SLAM and navigation bringup.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'odometry_tf_relay = robot_slam_bringup.odometry_tf_relay:main',
            (
                'd435i_extrinsics_relay = '
                'robot_slam_bringup.d435i_extrinsics_relay:main'
            ),
        ],
    },
)
