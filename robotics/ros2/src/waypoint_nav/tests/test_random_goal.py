"""随机目标优先落在有效地图中央，并能回退到其他已知空闲区。"""

import math
import random
import unittest
from types import SimpleNamespace

from waypoint_nav.random_goal import RandomGoalError, select_random_goal


def make_grid(width, height, data, resolution=1.0, origin=(0.0, 0.0, 0.0)):
    x, y, yaw = origin
    pose = SimpleNamespace(
        position=SimpleNamespace(x=x, y=y),
        orientation=SimpleNamespace(
            x=0.0, y=0.0, z=math.sin(yaw / 2), w=math.cos(yaw / 2)),
    )
    return SimpleNamespace(
        info=SimpleNamespace(width=width, height=height,
                             resolution=resolution, origin=pose),
        data=data,
    )


class RandomGoalTests(unittest.TestCase):

    def test_only_marked_free_cell_in_center_can_be_selected(self):
        data = [-1] * 64
        data[3 * 8 + 4] = 0
        grid = make_grid(8, 8, data)
        self.assertEqual(select_random_goal(grid, 0.0), (4.5, 3.5))

    def test_center_is_based_on_known_bounds_not_canvas_bounds(self):
        data = [-1] * 400
        for row in range(14, 18):
            for col in range(1, 5):
                data[row * 20 + col] = 0
        grid = make_grid(20, 20, data)
        for seed in range(20):
            x, y = select_random_goal(grid, 0.0, random.Random(seed))
            self.assertIn(int(x), (2, 3))
            self.assertIn(int(y), (15, 16))

    def test_clearance_rejects_unknown_and_obstacle_neighbors(self):
        data = [0] * 64
        data[3 * 8 + 3] = 100
        data[2 * 8 + 5] = -1
        grid = make_grid(8, 8, data)
        for seed in range(20):
            x, y = select_random_goal(grid, 1.0, random.Random(seed))
            col, row = int(x), int(y)
            self.assertIn(col, range(2, 6))
            self.assertIn(row, range(2, 6))
            for near_row in range(row - 1, row + 2):
                for near_col in range(col - 1, col + 2):
                    self.assertEqual(data[near_row * 8 + near_col], 0)

    def test_origin_rotation_is_applied_to_cell_center(self):
        data = [100] * 16
        data[1 * 4 + 1] = 0
        grid = make_grid(4, 4, data, 0.5, (2.0, 3.0, math.pi / 2))
        x, y = select_random_goal(grid, 0.0)
        self.assertAlmostEqual(x, 1.25)
        self.assertAlmostEqual(y, 3.75)

    def test_no_clearance_falls_back_to_known_free_cell_in_center(self):
        data = [100] * 64
        data[3 * 8 + 3] = 0
        grid = make_grid(8, 8, data)
        self.assertEqual(select_random_goal(grid, 1.0), (3.5, 3.5))

    def test_no_free_cell_in_center_expands_to_known_area(self):
        data = [100] * 100
        data[0] = 0
        grid = make_grid(10, 10, data)
        self.assertEqual(select_random_goal(grid, 1.0), (0.5, 0.5))

    def test_no_known_area_cannot_create_a_goal(self):
        grid = make_grid(8, 8, [-1] * 64)
        with self.assertRaisesRegex(RandomGoalError, '没有已知区域'):
            select_random_goal(grid, 0.35)

    def test_all_known_cells_blocked_cannot_create_a_goal(self):
        grid = make_grid(8, 8, [100] * 64)
        with self.assertRaisesRegex(RandomGoalError, '没有已知空闲栅格'):
            select_random_goal(grid, 0.35)


if __name__ == '__main__':
    unittest.main()
