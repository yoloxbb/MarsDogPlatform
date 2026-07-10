from setuptools import setup
import os
from glob import glob

package_name = 'wit_imu'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # 安装 launch 文件
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools', 'pyserial'],
    zip_safe=True,
    maintainer='yahboom',
    maintainer_email='yahboom@todo.todo',
    description='维特(WIT)串口 IMU 发布为 sensor_msgs/Imu 的 ROS2 节点',
    license='MIT',
    entry_points={
        'console_scripts': [
            # ros2 run wit_imu wit_imu_node
            'wit_imu_node = wit_imu.wit_imu_node:main',
        ],
    },
)
