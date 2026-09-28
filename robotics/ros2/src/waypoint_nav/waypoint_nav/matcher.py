"""waypoints.yaml 加载与地点名匹配。

本模块不依赖 ROS，可在任意 Python 3.10+ 环境直接测试。
文件格式与 occupancy-editor 的地点层输出保持一致：

    version: 1
    frame_id: map
    map: "rtabmap_d435i_camera_imu.pgm"
    resolution: 0.05
    origin: [-10, -10, 0]
    size: [384, 384]
    waypoints:
      - id: "A"
        name: "客厅"
        pose:
          position: {x: 1.625, y: -0.525, z: 0.0}
          orientation: {x: 0, y: 0, z: 0.2948, w: 0.9556}

匹配策略是精确匹配：调用方传入已标注的地点名或点位 ID，
本模块只去首尾空白，不做模糊匹配或意图解析。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml


SUPPORTED_VERSION = 1
RANDOM_PLACE_ID = '11'
RANDOM_PLACE_ALIASES = frozenset({RANDOM_PLACE_ID, 'K'})


@dataclass
class Waypoint:
    id: str
    name: str
    position: dict = field(default_factory=dict)      # {x, y, z}
    orientation: dict = field(default_factory=dict)   # {x, y, z, w}


@dataclass
class WaypointsFile:
    version: int
    frame_id: str
    map: str
    resolution: float
    origin: tuple
    size: tuple
    waypoints: list


class WaypointsError(Exception):
    """地点文件加载或校验失败。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WaypointsError(message)


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def load_waypoints(path: str | Path) -> WaypointsFile:
    """加载并做结构校验；与实际地图是否一致由节点对着 /map 判断。"""
    path = Path(path)
    if not path.is_file():
        raise WaypointsError(f'地点文件不存在: {path}')
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        raise WaypointsError(f'地点文件 YAML 解析失败: {exc}') from exc
    _require(isinstance(data, dict), '地点文件顶层必须是映射')

    version = data.get('version', SUPPORTED_VERSION)
    _require(isinstance(version, int) and not isinstance(version, bool)
             and version == SUPPORTED_VERSION,
             f'地点文件版本 {version} 不受支持，当前支持 {SUPPORTED_VERSION}')
    frame_id = data.get('frame_id', 'map')
    _require(isinstance(frame_id, str) and frame_id.strip(), 'frame_id 无效')
    frame_id = frame_id.strip()

    resolution = data.get('resolution')
    _require(_is_finite_number(resolution) and resolution > 0, 'resolution 无效')
    origin = data.get('origin')
    _require(isinstance(origin, (list, tuple)) and len(origin) == 3, 'origin 必须是 3 个数字')
    _require(all(_is_finite_number(value) for value in origin), 'origin 必须是 3 个有限数字')
    size = data.get('size')
    _require(isinstance(size, (list, tuple)) and len(size) == 2, 'size 必须是 [宽, 高]')
    _require(all(isinstance(value, int) and not isinstance(value, bool) and value > 0
                 for value in size), 'size 必须是两个正整数')
    map_name = data.get('map', '')
    _require(isinstance(map_name, str), 'map 必须是字符串')

    raw_waypoints = data.get('waypoints', [])
    if raw_waypoints is None:
        raw_waypoints = []
    _require(isinstance(raw_waypoints, list), 'waypoints 必须是列表')
    waypoints = []
    seen_ids = set()
    seen_names = set()
    for item in raw_waypoints:
        _require(isinstance(item, dict), 'waypoints 条目必须是映射')
        wp_id = item.get('id')
        _require(isinstance(wp_id, str) and wp_id.strip(), 'waypoint 缺少 id')
        wp_id = wp_id.strip()
        _require(wp_id not in RANDOM_PLACE_ALIASES,
                 f'waypoint id {wp_id} 保留给随机导航目标')
        _require(wp_id not in seen_ids, f'重复的 waypoint id: {wp_id}')
        seen_ids.add(wp_id)
        pose = item.get('pose')
        _require(isinstance(pose, dict), f'{wp_id} 缺少 pose')
        position = pose.get('position')
        orientation = pose.get('orientation')
        _require(isinstance(position, dict) and 'x' in position and 'y' in position,
                 f'{wp_id} 的 pose.position 缺少 x/y')
        _require(isinstance(orientation, dict)
                 and all(k in orientation for k in ('x', 'y', 'z', 'w')),
                 f'{wp_id} 的 pose.orientation 缺少 x/y/z/w')
        for key in ('x', 'y'):
            _require(_is_finite_number(position[key]),
                     f'{wp_id} 的 pose.position.{key} 必须是有限数字')
        if 'z' in position:
            _require(_is_finite_number(position['z']),
                     f'{wp_id} 的 pose.position.z 必须是有限数字')
        for key in ('x', 'y', 'z', 'w'):
            _require(_is_finite_number(orientation[key]),
                     f'{wp_id} 的 pose.orientation.{key} 必须是有限数字')
        _require(any(orientation[key] != 0 for key in ('x', 'y', 'z', 'w')),
                 f'{wp_id} 的 pose.orientation 不能是零四元数')
        name = item.get('name')
        _require(isinstance(name, str) and name.strip(), f'{wp_id} 的 name 必须是非空字符串')
        name = name.strip()
        _require(name not in seen_names, f'重复的 waypoint name: {name}')
        seen_names.add(name)
        waypoints.append(Waypoint(
            id=wp_id,
            name=name,
            position=dict(position),
            orientation=dict(orientation),
        ))

    return WaypointsFile(
        version=int(version),
        frame_id=frame_id,
        map=map_name,
        resolution=float(resolution),
        origin=tuple(float(v) for v in origin),
        size=(int(size[0]), int(size[1])),
        waypoints=waypoints,
    )


def normalize_place_name(text: str) -> str:
    """地点名归一化：只去首尾空白，不改写调用方输入。"""
    if not text:
        return ''
    return str(text).strip()


@dataclass
class MatchResult:
    matched: bool
    waypoint: Waypoint | None = None
    reason: str = ''


def match_place(place_text: str, waypoints_file: WaypointsFile) -> MatchResult:
    """优先精确匹配 ID，再匹配地点名，避免名称与其他点位 ID 冲突。"""
    if not waypoints_file.waypoints:
        return MatchResult(False, None, '地点文件里没有任何点位')

    query = normalize_place_name(place_text)
    if not query:
        return MatchResult(False, None, '地点名为空')

    for waypoint in waypoints_file.waypoints:
        if query == waypoint.id:
            return MatchResult(True, waypoint)

    for waypoint in waypoints_file.waypoints:
        if query == normalize_place_name(waypoint.name):
            return MatchResult(True, waypoint)

    known = '、'.join(wp.name for wp in waypoints_file.waypoints)
    return MatchResult(False, None, f'未找到地点 "{place_text}"，已标记的地点: {known}')
