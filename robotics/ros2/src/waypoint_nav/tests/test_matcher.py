"""点位名称与 ID 的精确匹配边界。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from waypoint_nav.matcher import Waypoint, WaypointsError, WaypointsFile, load_waypoints, match_place


class MatcherTests(unittest.TestCase):

    def test_id_takes_priority_over_another_waypoints_name(self):
        waypoints = WaypointsFile(
            version=1, frame_id='map', map='test.pgm', resolution=0.05,
            origin=(0.0, 0.0, 0.0), size=(10, 10),
            waypoints=[
                Waypoint(id='A', name='B'),
                Waypoint(id='B', name='厨房'),
            ],
        )

        self.assertEqual(match_place('B', waypoints).waypoint.id, 'B')
        self.assertEqual(match_place('厨房', waypoints).waypoint.id, 'B')
        self.assertFalse(match_place('厨', waypoints).matched)

    def test_random_target_id_cannot_be_used_in_waypoint_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'waypoints.yaml'
            template = '''version: 1
frame_id: map
resolution: 0.05
origin: [0, 0, 0]
size: [10, 10]
waypoints:
  - id: "11"
    name: "普通地点"
    pose:
      position: {x: 1, y: 1, z: 0}
      orientation: {x: 0, y: 0, z: 0, w: 1}
'''
            for reserved_id in ('11', 'K'):
                with self.subTest(reserved_id=reserved_id):
                    path.write_text(template.replace('id: "11"', f'id: "{reserved_id}"'),
                                    encoding='utf-8')
                    with self.assertRaisesRegex(WaypointsError, '保留给随机导航目标'):
                        load_waypoints(path)


if __name__ == '__main__':
    unittest.main()
