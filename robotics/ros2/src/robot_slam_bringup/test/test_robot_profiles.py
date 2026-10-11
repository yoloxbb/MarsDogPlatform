"""Pure configuration and TF conversion checks; no hardware or DDS connection."""

from copy import deepcopy
from pathlib import Path
import unittest
import hashlib
import xml.etree.ElementTree as ET

import yaml

from robot_slam_bringup.robot_profiles import (
    ROBOTS, load_profile, merge_nav2, prepare_description, sensor_transform,
)


SHARE = Path(__file__).resolve().parents[1]


class RobotProfilesTest(unittest.TestCase):
    def setUp(self):
        self.common = yaml.safe_load((SHARE / 'config' / 'nav.yaml').read_text(encoding='utf-8'))

    def test_lite3_has_exactly_original_nav2_values(self):
        profile, _ = load_profile(SHARE, 'lite3')
        self.assertEqual(merge_nav2(self.common, profile['nav2_overrides']), self.common)
        self.assertEqual(profile['launch']['odom_topic'], '/leg_odom2')
        self.assertFalse(profile['launch']['publish_odom_tf'])

    def test_three_profiles_keep_same_algorithms_but_own_geometry_and_limits(self):
        geometry = set()
        for robot in ROBOTS:
            with self.subTest(robot=robot):
                profile, _ = load_profile(SHARE, robot)
                result = merge_nav2(self.common, profile['nav2_overrides'])
                geometry.add(result['local_costmap']['local_costmap']['ros__parameters']['footprint'])
                self.assertEqual(result['planner_server'], self.common['planner_server'])
                self.assertEqual(result['smoother_server'], self.common['smoother_server'])
                for kind in ('local_costmap', 'global_costmap'):
                    layer = result[kind][kind]['ros__parameters']['stvl_layer']
                    self.assertEqual(layer, self.common[kind][kind]['ros__parameters']['stvl_layer'])
        self.assertEqual(len(geometry), 3)

    def test_different_databases_and_required_odom_tf_owner(self):
        profiles = [load_profile(SHARE, robot)[0] for robot in ROBOTS]
        self.assertEqual(len({p['launch']['database_path'] for p in profiles}), 3)
        self.assertTrue(profiles[2]['launch']['publish_odom_tf'])
        self.assertFalse(profiles[1]['launch']['publish_odom_tf'])

    def test_unknown_robot_and_cross_robot_file_rejected(self):
        with self.assertRaises(ValueError):
            load_profile(SHARE, 'not-a-robot')
        with self.assertRaises(ValueError):
            load_profile(SHARE, 'go2', str(SHARE / 'config/robots/lite3.yaml'))

    def test_unknown_parameter_path_rejected(self):
        with self.assertRaisesRegex(ValueError, '没有参数'):
            merge_nav2(self.common, {'controller_server': {'ros__parameters': {'FollowPth': {}}}})

    def test_undersized_recovery_radius_and_smoother_rejected(self):
        with self.assertRaisesRegex(ValueError, '外接圆'):
            merge_nav2(self.common, {'behavior_server': {'ros__parameters': {'robot_radius': 0.1}}})
        with self.assertRaisesRegex(ValueError, 'MPPI'):
            merge_nav2(self.common, {'velocity_smoother': {'ros__parameters':
                                                        {'max_velocity': [0.1, 0.0, 1.2]}}})

    def test_unknown_mount_cannot_be_published(self):
        for robot in ROBOTS:
            with self.subTest(robot=robot), self.assertRaisesRegex(ValueError, '尚未标定'):
                sensor_transform(load_profile(SHARE, robot)[0])

    def test_explicit_mount_uses_supplied_values(self):
        profile = deepcopy(load_profile(SHARE, 'lingmao')[0])
        profile['sensor_mount'].update(xyz=[0.12, 0.0, 0.08], rpy=[0.0, 0.05, 0.0])
        self.assertEqual(sensor_transform(profile)['xyz'], [0.12, 0.0, 0.08])

    def test_cyvet_alias_mesh_resolution_and_original_asset_unchanged(self):
        from ament_index_python.packages import get_package_share_directory
        share = Path(get_package_share_directory('cyvet_description'))
        filename = 'robots/cyvet/urdf/cyvet.urdf'
        before = hashlib.sha256((share / filename).read_bytes()).hexdigest()
        tree = ET.fromstring(prepare_description(share, filename, 'cyvet_description',
                                                'base_link', 'BASE_LINK'))
        links = {link.get('name') for link in tree.findall('link')}
        children = {child.get('link') for child in tree.findall('joint/child')}
        self.assertEqual(links - children, {'base_link'})
        alias = tree.find("joint[@name='navigation_base_alias']")
        self.assertEqual(alias.find('origin').get('xyz'), '0 0 0')
        for mesh in tree.findall('.//mesh'):
            uri = mesh.get('filename')
            self.assertTrue(uri.startswith('package://cyvet_description/'))
            self.assertTrue((share / uri.removeprefix('package://cyvet_description/')).is_file())
        self.assertEqual(hashlib.sha256((share / filename).read_bytes()).hexdigest(), before)


class OdometryConversionTest(unittest.TestCase):
    def setUp(self):
        from nav_msgs.msg import Odometry
        self.message = Odometry()
        self.message.header.frame_id = 'odom'
        self.message.child_frame_id = 'base_link'
        self.message.header.stamp.sec = 123
        self.message.header.stamp.nanosec = 456
        self.message.pose.pose.position.x = 1.25
        self.message.pose.pose.orientation.w = 1.0

    def test_message_pose_and_timestamp_preserved(self):
        from robot_slam_bringup.odometry_tf_relay import odometry_transform
        result = odometry_transform(self.message, 'odom', 'base_link')
        self.assertEqual(result.header, self.message.header)
        self.assertEqual(result.transform.translation.x, 1.25)
        self.assertEqual(result.transform.rotation, self.message.pose.pose.orientation)

    def test_frame_mismatch_rejected(self):
        from robot_slam_bringup.odometry_tf_relay import odometry_transform
        with self.assertRaises(ValueError):
            odometry_transform(self.message, 'odom', 'base_footprint')

    def test_bad_quaternion_nonfinite_pose_and_zero_stamp_rejected(self):
        from robot_slam_bringup.odometry_tf_relay import odometry_transform
        for kind in ('quaternion', 'nonfinite', 'zero_stamp'):
            with self.subTest(kind=kind):
                bad = deepcopy(self.message)
                if kind == 'quaternion':
                    bad.pose.pose.orientation.w = 0.0
                elif kind == 'nonfinite':
                    bad.pose.pose.position.x = float('nan')
                else:
                    bad.header.stamp.sec = 0
                    bad.header.stamp.nanosec = 0
                with self.assertRaises(ValueError):
                    odometry_transform(bad, 'odom', 'base_link')


if __name__ == '__main__':
    unittest.main()
