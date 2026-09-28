# Copyright 2026 bird
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""启动单次 bbox 深度定位节点."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """加载默认参数文件，并允许启动时替换整份配置."""
    package_share = get_package_share_directory('person_3d_localization')
    default_config = os.path.join(
        package_share, 'config', 'person_3d_localization.yaml')
    config_file = LaunchConfiguration('config_file')

    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=default_config,
            description='单次 bbox 深度定位参数文件。',
        ),
        Node(
            package='person_3d_localization',
            executable='bbox_depth_goal_node',
            name='bbox_depth_goal_node',
            output='screen',
            parameters=[config_file],
        ),
    ])
