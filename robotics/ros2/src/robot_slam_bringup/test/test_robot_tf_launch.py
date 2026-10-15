"""Standalone TF launch contract checks without starting ROS nodes."""

import builtins
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from launch import LaunchContext
from launch.substitutions import LaunchConfiguration

from robot_slam_bringup.profile_launch import (
    configure_robot_profile, declare_tf_arguments, show_tf_configuration,
)


SHARE = Path(__file__).resolve().parents[1]


class RobotTfLaunchTest(unittest.TestCase):
    def test_tf_launch_loads_without_nav2_or_rtabmap_imports(self):
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.startswith(('nav2', 'rtabmap')):
                raise AssertionError('TF-only entry must not import navigation: ' + name)
            return original_import(name, *args, **kwargs)

        filename = SHARE / 'launch' / 'robot_tf.launch.py'
        spec = importlib.util.spec_from_file_location('isolated_robot_tf_launch', filename)
        module = importlib.util.module_from_spec(spec)
        with patch('builtins.__import__', guarded_import):
            spec.loader.exec_module(module)
            description = module.generate_launch_description()
        self.assertTrue(description.entities)

    def test_shared_tf_defaults_keep_profile_values_and_explicit_height_override(self):
        context = LaunchContext()
        context.launch_configurations.update(robot='lingmao', robot_config='', body_height='0.35')
        with patch('robot_slam_bringup.profile_launch.get_package_share_directory',
                   return_value=str(SHARE)):
            for action in configure_robot_profile(context):
                action.execute(context)
        for action in declare_tf_arguments():
            action.execute(context)
        self.assertEqual(LaunchConfiguration('base_frame').perform(context), 'base_footprint')
        self.assertEqual(LaunchConfiguration('body_frame').perform(context), 'base_link')
        self.assertEqual(LaunchConfiguration('nav2_odom_topic').perform(context), '/odom_nav')
        self.assertEqual(LaunchConfiguration('body_height').perform(context), '0.35')
        # Configuration display also works without constructing a Nav2 YAML.
        self.assertEqual(len(show_tf_configuration(context)), 1)


if __name__ == '__main__':
    unittest.main()
