"""从实时 OccupancyGrid 的有效区域选择已知空闲导航目标。"""

from __future__ import annotations

import math
import random


class RandomGoalError(ValueError):
    """地图无效或整张实时地图没有已知空闲栅格。"""


def select_random_goal(grid, clearance_m: float, rng=None) -> tuple[float, float]:
    """优先在已知区域中央选点；必要时扩展到所有已知空闲栅格。"""
    info = grid.info
    width, height = int(info.width), int(info.height)
    resolution = float(info.resolution)
    if width <= 0 or height <= 0 or not math.isfinite(resolution) or resolution <= 0:
        raise RandomGoalError('实时地图的尺寸或分辨率无效')
    if len(grid.data) != width * height:
        raise RandomGoalError('实时地图栅格数量与尺寸不一致')
    if not math.isfinite(clearance_m) or clearance_m < 0:
        raise RandomGoalError('随机点位安全距离必须是非负有限数')

    # 有效地图的边界由已知栅格确定，不使用整张地图画布的宽高。
    # 0 才是已知空闲；未知(-1)和任意占用值都不能落点。
    stride = width + 1
    blocked_sum = [0] * ((height + 1) * stride)
    min_col, min_row, max_col, max_row = width, height, -1, -1
    for row in range(height):
        row_blocked = 0
        for col in range(width):
            value = grid.data[row * width + col]
            if value >= 0:
                min_col, min_row = min(min_col, col), min(min_row, row)
                max_col, max_row = max(max_col, col), max(max_row, row)
            row_blocked += value != 0
            blocked_sum[(row + 1) * stride + col + 1] = (
                blocked_sum[row * stride + col + 1] + row_blocked)
    if max_col < 0:
        raise RandomGoalError('实时地图没有已知区域')

    known_width, known_height = max_col - min_col + 1, max_row - min_row + 1
    span_x, span_y = max(1, known_width // 2), max(1, known_height // 2)
    start_x = min_col + (known_width - span_x) // 2
    start_y = min_row + (known_height - span_y) // 2
    clearance_cells = math.ceil(clearance_m / resolution)
    safe_center, safe_anywhere, free_center, free_anywhere = [], [], [], []
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            if grid.data[row * width + col] != 0:
                continue
            cell = (col, row)
            in_center = (start_x <= col < start_x + span_x
                         and start_y <= row < start_y + span_y)
            free_anywhere.append(cell)
            if in_center:
                free_center.append(cell)
            x0, y0 = col - clearance_cells, row - clearance_cells
            x1, y1 = col + clearance_cells + 1, row + clearance_cells + 1
            if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
                continue
            blocked = (blocked_sum[y1 * stride + x1] - blocked_sum[y0 * stride + x1]
                       - blocked_sum[y1 * stride + x0] + blocked_sum[y0 * stride + x0])
            if blocked == 0:
                safe_anywhere.append(cell)
                if in_center:
                    safe_center.append(cell)
    # 优先有效区域中央；中央无空闲点时才扩大到整个已知区域。
    candidates = safe_center or free_center or safe_anywhere or free_anywhere
    if not candidates:
        raise RandomGoalError('实时地图没有已知空闲栅格')

    col, row = (rng or random).choice(candidates)
    # OccupancyGrid 的第 0 行从地图原点开始；原点可能有旋转。
    local_x, local_y = (col + 0.5) * resolution, (row + 0.5) * resolution
    origin = info.origin
    q = origin.orientation
    yaw = math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )
    x = origin.position.x + math.cos(yaw) * local_x - math.sin(yaw) * local_y
    y = origin.position.y + math.sin(yaw) * local_x + math.cos(yaw) * local_y
    if not math.isfinite(x) or not math.isfinite(y):
        raise RandomGoalError('实时地图原点无效')
    return x, y
