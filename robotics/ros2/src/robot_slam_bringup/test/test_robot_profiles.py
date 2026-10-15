"""Pure configuration and TF conversion checks; no hardware or DDS connection."""

from copy import deepcopy
from pathlib import Path
import unittest
import hashlib
import xml.etree.ElementTree as ET
from tempfile import TemporaryDirectory

import yaml

from robot_slam_bringup.robot_profiles import (
    ROBOTS, load_profile, merge_nav2, prepare_description, sensor_transform, uwb_transform,
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
        for robot in ('lite3', 'go2'):
            with self.subTest(robot=robot), self.assertRaisesRegex(ValueError, '尚未标定'):
                sensor_transform(load_profile(SHARE, robot)[0])

    def test_lingmao_initial_mount_and_frame_roles_are_explicit(self):
        profile, _ = load_profile(SHARE, 'lingmao')
        self.assertEqual(profile['launch']['base_frame'], 'base_footprint')
        self.assertEqual(profile['launch']['body_frame'], 'base_link')
        self.assertEqual(profile['launch']['odom_child_frame'], 'base_link')
        self.assertEqual(profile['launch']['odom_topic'], '/odom')
        self.assertEqual(profile['launch']['nav2_odom_topic'], '/odom_nav')
        self.assertTrue(profile['launch']['split_base_frames'])
        self.assertEqual(profile['body_geometry']['height'], 0.36)
        self.assertEqual(profile['sensor_mount']['calibration_status'], 'initial_model_estimate')
        self.assertEqual(sensor_transform(profile)['xyz'], [0.289, 0.0, 0.114])

    def test_explicit_mount_uses_supplied_values(self):
        profile = deepcopy(load_profile(SHARE, 'lingmao')[0])
        profile['sensor_mount'].update(xyz=[0.12, 0.0, 0.08], rpy=[0.0, 0.05, 0.0])
        self.assertEqual(sensor_transform(profile)['xyz'], [0.12, 0.0, 0.08])

    def test_cyvet_single_body_root_preserves_geometry_and_original_asset(self):
        from ament_index_python.packages import get_package_share_directory
        share = Path(get_package_share_directory('cyvet_description'))
        filename = 'robots/cyvet/urdf/cyvet.urdf'
        before = hashlib.sha256((share / filename).read_bytes()).hexdigest()
        original = ET.parse(share / filename).getroot()
        tree = ET.fromstring(prepare_description(share, filename, 'cyvet_description',
                                                'base_link', 'BASE_LINK'))
        links = {link.get('name') for link in tree.findall('link')}
        children = {child.get('link') for child in tree.findall('joint/child')}
        self.assertEqual(links - children, {'base_link'})
        self.assertNotIn('BASE_LINK', links)
        self.assertEqual(len(tree.findall('link')), len(original.findall('link')))
        self.assertIsNone(tree.find("joint[@name='navigation_base_alias']"))
        self.assertEqual(
            ET.tostring(tree.find("link[@name='base_link']/inertial")),
            ET.tostring(original.find("link[@name='BASE_LINK']/inertial")))
        self.assertEqual(len(tree.findall('joint')), len(original.findall('joint')))
        for joint in tree.findall('joint'):
            source = original.find(f"joint[@name='{joint.get('name')}']")
            for tag in ('origin', 'axis', 'limit'):
                actual, expected = joint.find(tag), source.find(tag)
                self.assertEqual(ET.tostring(actual) if actual is not None else None,
                                 ET.tostring(expected) if expected is not None else None)
            for tag in ('parent', 'child'):
                self.assertIn(joint.find(tag).get('link'), links)
        self.assertEqual(
            len([p for p in tree.findall('joint/parent') if p.get('link') == 'base_link']), 4)
        for mesh in tree.findall('.//mesh'):
            uri = mesh.get('filename')
            self.assertTrue(uri.startswith('package://cyvet_description/'))
            self.assertTrue((share / uri.removeprefix('package://cyvet_description/')).is_file())
        self.assertEqual(hashlib.sha256((share / filename).read_bytes()).hexdigest(), before)

    def test_root_rename_rejects_child_as_root_and_existing_link_name(self):
        from ament_index_python.packages import get_package_share_directory
        share = get_package_share_directory('cyvet_description')
        for body, root in (('base_link', 'FL_ABAD_LINK'), ('FL_ABAD_LINK', 'BASE_LINK')):
            with self.subTest(body=body, root=root), self.assertRaises(ValueError):
                prepare_description(share, 'robots/cyvet/urdf/cyvet.urdf',
                                    'cyvet_description', body, root)

    def test_root_rename_keeps_gazebo_link_reference_consistent(self):
        with TemporaryDirectory() as folder:
            Path(folder, 'robot.urdf').write_text(
                '<robot name="test"><link name="BASE_LINK"/><link name="leg"/>'
                '<joint name="hip" type="fixed"><parent link="BASE_LINK"/>'
                '<child link="leg"/></joint><gazebo reference="BASE_LINK"/></robot>',
                encoding='utf-8')
            tree = ET.fromstring(prepare_description(
                folder, 'robot.urdf', 'test', 'base_link', 'BASE_LINK'))
            self.assertEqual(tree.find('gazebo').get('reference'), 'base_link')

    def test_camera_is_fixed_to_body_not_navigation_projection(self):
        from ament_index_python.packages import get_package_share_directory
        profile, _ = load_profile(SHARE, 'lingmao')
        share = Path(get_package_share_directory('cyvet_description'))
        tree = ET.fromstring(prepare_description(
            share, 'robots/cyvet/urdf/cyvet.urdf', 'cyvet_description',
            'base_link', 'BASE_LINK', sensor_transform(profile),
            profile['description_joint_aliases']))
        joints = [
            joint for joint in tree.findall('joint')
            if joint.find('child').get('link') == 'camera_link']
        self.assertEqual(len(joints), 1)
        self.assertEqual(joints[0].get('type'), 'fixed')
        self.assertEqual(joints[0].find('parent').get('link'), 'base_link')
        self.assertEqual(joints[0].find('origin').get('xyz'), '0.289 0.0 0.114')
        self.assertNotIn('base_footprint', {link.get('name') for link in tree.findall('link')})
        self.assertTrue(set(profile['description_joint_aliases'].values()).issubset(
            {joint.get('name') for joint in tree.findall('joint')}))

    def test_joint_alias_collisions_are_rejected(self):
        from ament_index_python.packages import get_package_share_directory
        with self.assertRaisesRegex(ValueError, '名称重复'):
            prepare_description(get_package_share_directory('cyvet_description'),
                                'robots/cyvet/urdf/cyvet.urdf', 'cyvet_description',
                                'base_link', 'BASE_LINK', joint_aliases={
                                    'FL_ABAD_JOINT': 'same', 'FR_ABAD_JOINT': 'same'})

    def test_mount_on_wrong_parent_is_rejected(self):
        from ament_index_python.packages import get_package_share_directory
        profile, _ = load_profile(SHARE, 'lingmao')
        mount = deepcopy(sensor_transform(profile))
        mount['parent_frame'] = 'base_footprint'
        with self.assertRaisesRegex(ValueError, 'body_frame'):
            prepare_description(get_package_share_directory('cyvet_description'),
                                'robots/cyvet/urdf/cyvet.urdf', 'cyvet_description',
                                'base_link', 'BASE_LINK', mount)

    def test_uwb_mount_keeps_camera_parent_and_relative_orientation(self):
        from ament_index_python.packages import get_package_share_directory
        profile = deepcopy(load_profile(SHARE, 'lingmao')[0])
        # A tilted camera catches attaching UWB directly to the body by accident.
        profile['sensor_mount']['rpy'] = [0.1, 0.2, 0.3]
        tree = ET.fromstring(prepare_description(
            get_package_share_directory('cyvet_description'),
            'robots/cyvet/urdf/cyvet.urdf', 'cyvet_description',
            'base_link', 'BASE_LINK', sensor_transform(profile),
            profile['description_joint_aliases'], uwb_mount=uwb_transform(profile)))
        uwb = tree.find("joint[@name='robot_uwb_mount']")
        self.assertEqual(uwb.get('type'), 'fixed')
        self.assertEqual(uwb.find('parent').get('link'), 'camera_link')
        self.assertEqual(uwb.find('child').get('link'), 'uwb_link')
        self.assertEqual(uwb.find('origin').get('xyz'), '-0.04 0.0 -0.05')
        self.assertEqual(uwb.find('origin').get('rpy'), '0.0 0.0 0.0')
        self.assertEqual(
            tree.find("joint[@name='robot_camera_mount']/origin").get('rpy'), '0.1 0.2 0.3')
        parents = [j for j in tree.findall('joint') if j.find('child').get('link') == 'uwb_link']
        self.assertEqual(len(parents), 1)

    def test_uwb_missing_configuration_invalid_offset_and_duplicate_frame_rejected(self):
        from ament_index_python.packages import get_package_share_directory
        for robot in ('lite3', 'go2'):
            self.assertIsNone(uwb_transform(load_profile(SHARE, robot)[0]))
        profile = deepcopy(load_profile(SHARE, 'lingmao')[0])
        profile['uwb_mount']['xyz'][0] = float('nan')
        with self.assertRaisesRegex(ValueError, 'uwb_mount'):
            uwb_transform(profile)
        profile = deepcopy(load_profile(SHARE, 'lingmao')[0])
        profile['uwb_mount']['child_frame'] = 'base_link'
        with self.assertRaisesRegex(ValueError, '已有 UWB 坐标系'):
            prepare_description(get_package_share_directory('cyvet_description'),
                                'robots/cyvet/urdf/cyvet.urdf', 'cyvet_description',
                                'base_link', 'BASE_LINK', sensor_transform(profile),
                                uwb_mount=uwb_transform(profile))

    def test_uwb_tf_has_one_owner_with_or_without_the_model(self):
        from launch import LaunchContext
        from robot_slam_bringup.profile_launch import create_uwb_transform
        for model, camera, count in ((True, True, 0), (False, True, 1),
                                     (True, False, 1), (False, False, 1)):
            with self.subTest(model=model, camera=camera):
                context = LaunchContext()
                context.extend_locals({'robot_profile': load_profile(SHARE, 'lingmao')[0]})
                context.launch_configurations.update(
                    start_robot_state_publisher=str(model).lower(),
                    publish_sensor_tf=str(camera).lower())
                self.assertEqual(len(create_uwb_transform(context)), count)


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

    def test_split_keeps_navigation_planar_and_does_not_mutate_vendor_message(self):
        import math
        from robot_slam_bringup.odometry_tf_relay import split_odometry_transforms
        self.message.pose.pose.orientation.z = math.sin(0.6)
        self.message.pose.pose.orientation.w = math.cos(0.6)
        self.message.pose.pose.position.z = 0.0  # Legacy vendor field is reserved.
        before = deepcopy(self.message)
        footprint, body = split_odometry_transforms(
            self.message, 'odom', 'base_link', 'base_footprint', 'base_link', 0.38)
        self.assertEqual(footprint.child_frame_id, 'base_footprint')
        self.assertEqual(footprint.transform.translation.z, 0.0)
        self.assertAlmostEqual(footprint.transform.rotation.z, math.sin(0.6))
        self.assertEqual(body.header.frame_id, 'base_footprint')
        self.assertEqual(body.child_frame_id, 'base_link')
        self.assertAlmostEqual(body.transform.translation.z, 0.38)
        self.assertAlmostEqual(body.transform.rotation.z, 0.0)
        self.assertAlmostEqual(body.transform.rotation.w, 1.0)
        self.assertEqual(body.header.stamp, footprint.header.stamp)
        self.assertEqual(self.message, before)

    def test_split_orientation_composition_recovers_full_input_attitude(self):
        import math
        from robot_slam_bringup.odometry_tf_relay import split_odometry_transforms
        # Nonzero roll, pitch and yaw catch lost attitude and duplicated yaw.
        roll, pitch, yaw = 0.25, -0.18, 0.8
        cr, sr = math.cos(roll/2), math.sin(roll/2)
        cp, sp = math.cos(pitch/2), math.sin(pitch/2)
        cy, sy = math.cos(yaw/2), math.sin(yaw/2)
        q = self.message.pose.pose.orientation
        q.x = sr*cp*cy - cr*sp*sy
        q.y = cr*sp*cy + sr*cp*sy
        q.z = cr*cp*sy - sr*sp*cy
        q.w = cr*cp*cy + sr*sp*sy
        f, b = split_odometry_transforms(
            self.message, 'odom', 'base_link', 'base_footprint', 'base_link', 0.38)
        a, c = f.transform.rotation, b.transform.rotation
        composed = (
            a.w*c.x + a.x*c.w + a.y*c.z - a.z*c.y,
            a.w*c.y - a.x*c.z + a.y*c.w + a.z*c.x,
            a.w*c.z + a.x*c.y - a.y*c.x + a.z*c.w,
            a.w*c.w - a.x*c.x - a.y*c.y - a.z*c.z,
        )
        for actual, expected in zip(composed, (q.x, q.y, q.z, q.w)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(f.transform.rotation.x, 0.0)
        self.assertEqual(f.transform.rotation.y, 0.0)

    def test_split_rejects_invalid_height_and_frame_roles(self):
        from robot_slam_bringup.odometry_tf_relay import split_odometry_transforms
        for height in (0.0, -0.1, float('nan'), True):
            with self.subTest(height=height), self.assertRaises(ValueError):
                split_odometry_transforms(self.message, 'odom', 'base_link',
                                          'base_footprint', 'base_link', height)
        with self.assertRaises(ValueError):
            split_odometry_transforms(self.message, 'odom', 'base_link',
                                      'base_link', 'base_link', 0.38)

    def test_missing_body_height_does_not_publish_a_fake_ground_to_body_transform(self):
        from robot_slam_bringup.odometry_tf_relay import split_odometry_transforms
        result = split_odometry_transforms(self.message, 'odom', 'base_link',
                                           'base_footprint', 'base_link')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].child_frame_id, 'base_footprint')


if __name__ == '__main__':
    unittest.main()
