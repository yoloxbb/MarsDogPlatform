import os
from glob import glob

from setuptools import find_packages, setup


package_name = 'stereo_slam_legacy_bringup'


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
            glob('config/*'),
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='yahboom',
    maintainer_email='your.email@example.com',
    description='迁移自传感器包的历史双目 SLAM、定位和导航兼容入口。',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            (
                'd435i_extrinsics_relay = '
                'stereo_slam_legacy_bringup.d435i_extrinsics_relay:main'
            ),
        ],
    },
)
