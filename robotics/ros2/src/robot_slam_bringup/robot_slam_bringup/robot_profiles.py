"""Load robot-specific defaults and overlay the shared Nav2 configuration."""

from copy import deepcopy
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml


ROBOTS = ('lite3', 'go2', 'lingmao')
PROFILE_ARGUMENTS = {
    'base_frame', 'odom_frame', 'map_frame', 'sensor_frame', 'odom_topic',
    'cmd_vel_topic', 'stereo_odom_topic', 'database_path', 'description_package',
    'description_file', 'description_root_frame', 'publish_odom_tf',
}


def load_profile(share, robot, filename=''):
    """Load a selected profile; custom files must identify the same robot."""
    if robot not in ROBOTS:
        raise ValueError(f'未知机器人 {robot!r}，可选值：{", ".join(ROBOTS)}')
    path = Path(filename).expanduser() if filename else (
        Path(share) / 'config' / 'robots' / f'{robot}.yaml')
    with path.open(encoding='utf-8') as stream:
        profile = yaml.safe_load(stream)
    if not isinstance(profile, dict) or profile.get('schema_version') != 1:
        raise ValueError(f'机器人配置格式错误：{path}')
    if profile.get('robot') != robot:
        raise ValueError(f'配置中的 robot 必须与 robot:={robot} 一致：{path}')
    defaults = profile.get('launch', {})
    if not isinstance(defaults, dict) or set(defaults) - PROFILE_ARGUMENTS:
        raise ValueError(f'配置包含不支持的启动参数：{path}')
    for name, value in defaults.items():
        if not isinstance(value, (str, bool)):
            raise ValueError(f'启动参数 {name} 必须为字符串或布尔值')
    if not isinstance(profile.get('nav2_overrides'), dict):
        raise ValueError('nav2_overrides 必须为字典')
    return profile, path.resolve()


def launch_value(value):
    """Convert YAML defaults into launch argument strings."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def merge_nav2(common, overrides):
    """Overlay existing parameters, rejecting typos and unknown parameter paths."""
    result = deepcopy(common)

    def overlay(target, changes, prefix=''):
        for key, value in changes.items():
            path = f'{prefix}.{key}' if prefix else key
            if key not in target:
                raise ValueError(f'公共 Nav2 配置没有参数 {path}')
            if isinstance(value, dict):
                if not isinstance(target[key], dict):
                    raise ValueError(f'参数结构不匹配：{path}')
                overlay(target[key], value, path)
            else:
                target[key] = deepcopy(value)

    overlay(result, overrides)
    validate_navigation(result)
    return result


def validate_navigation(params):
    """Check geometry and consistent MPPI/smoother limits before starting nodes."""
    footprints = []
    for kind in ('local_costmap', 'global_costmap'):
        values = params[kind][kind]['ros__parameters']
        polygon = yaml.safe_load(values['footprint'])
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise ValueError(f'{kind}: footprint 至少需要三个顶点')
        for point in polygon:
            if (not isinstance(point, list) or len(point) != 2 or
                    not all(isinstance(x, (float, int)) and math.isfinite(x)
                            for x in point)):
                raise ValueError(f'{kind}: footprint 顶点必须为有限二维坐标')
        area = sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1] -
                   polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
                   for i in range(len(polygon))) / 2
        if abs(area) < 1e-6:
            raise ValueError(f'{kind}: footprint 面积为零')
        footprints.append(polygon)
    if footprints[0] != footprints[1]:
        raise ValueError('局部和全局代价地图的 footprint 必须一致')
    radius = params['behavior_server']['ros__parameters']['robot_radius']
    if radius + 1e-6 < max(math.hypot(*p) for p in footprints[0]):
        raise ValueError('恢复行为 robot_radius 小于机器人轮廓外接圆')
    controller = params['controller_server']['ros__parameters']['FollowPath']
    if controller['plugin'] != 'nav2_mppi_controller::MPPIController':
        raise ValueError('三机器人统一入口要求使用公共 MPPI 控制器')
    smoother = params['velocity_smoother']['ros__parameters']
    for key in ('max_velocity', 'min_velocity', 'max_accel', 'max_decel'):
        vector = smoother[key]
        if (not isinstance(vector, list) or len(vector) != 3 or
                not all(isinstance(x, (float, int)) and math.isfinite(x)
                        for x in vector)):
            raise ValueError(f'{key} 必须包含三个有限数值')
    if not (controller['vx_min'] <= 0 <= controller['vx_max'] and
            controller['wz_max'] > 0):
        raise ValueError('MPPI 速度上下限不合法')
    for index, low, high in ((0, controller['vx_min'], controller['vx_max']),
                             (2, -controller['wz_max'], controller['wz_max'])):
        if (smoother['min_velocity'][index] > low or
                smoother['max_velocity'][index] < high):
            raise ValueError('velocity_smoother 的范围不能小于 MPPI 速度范围')


def sensor_transform(profile):
    """Return an explicitly calibrated mount; never infer an installation pose."""
    mount = profile.get('sensor_mount', {})
    for key in ('parent_frame', 'child_frame'):
        if not isinstance(mount.get(key), str) or not mount[key]:
            raise ValueError(f'sensor_mount.{key} 不能为空')
    for key in ('xyz', 'rpy'):
        vector = mount.get(key)
        if (not isinstance(vector, list) or len(vector) != 3 or
                not all(isinstance(x, (float, int)) and math.isfinite(x)
                        for x in vector)):
            raise ValueError(
                f'sensor_mount.{key} 尚未标定；请填写三个实测值后启用 publish_sensor_tf')
    if mount['parent_frame'] == mount['child_frame']:
        raise ValueError('传感器 TF 的父子坐标系不能相同')
    return mount


def prepare_description(package_share, relative_file, package_name, base, root_frame=''):
    """Resolve asset references and an explicit root alias without editing assets."""
    share = Path(package_share).resolve()
    urdf_path = share / relative_file
    tree = ET.fromstring(urdf_path.read_text(encoding='utf-8'))
    for mesh in tree.findall('.//mesh'):
        filename = mesh.get('filename', '')
        if filename and '://' not in filename and not Path(filename).is_absolute():
            target = (urdf_path.parent / filename).resolve()
            relative = target.relative_to(share)
            if not target.is_file():
                raise ValueError(f'URDF mesh 不存在：{target}')
            mesh.set('filename', f'package://{package_name}/{relative.as_posix()}')
    if root_frame and root_frame != base:
        links = {link.get('name') for link in tree.findall('link')}
        children = {child.get('link') for child in tree.findall('joint/child')}
        if root_frame not in links - children or base in links:
            raise ValueError('description_root_frame 必须是 URDF 根，base_frame 别名不能已存在')
        ET.SubElement(tree, 'link', name=base)
        alias = ET.SubElement(tree, 'joint', name='navigation_base_alias', type='fixed')
        ET.SubElement(alias, 'parent', link=base)
        ET.SubElement(alias, 'child', link=root_frame)
        ET.SubElement(alias, 'origin', xyz='0 0 0', rpy='0 0 0')
    return ET.tostring(tree, encoding='unicode')
