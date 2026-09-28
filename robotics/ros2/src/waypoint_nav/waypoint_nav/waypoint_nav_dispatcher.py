"""持久化点位导航节点；VoiceTask 只负责请求受理和状态查询。"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
import uuid

import rclpy
from action_msgs.msg import GoalStatus
from action_msgs.srv import CancelGoal
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.qos import QoSDurabilityPolicy, QoSProfile
from std_msgs.msg import String
from unique_identifier_msgs.msg import UUID
from visualization_msgs.msg import Marker, MarkerArray
from marsdog_voice_interaction.srv import VoiceTask

from .matcher import (
    RANDOM_PLACE_ALIASES,
    RANDOM_PLACE_ID,
    WaypointsError,
    load_waypoints,
    match_place,
)
from .random_goal import RandomGoalError, select_random_goal
from .task_store import (
    BusyTask, DuplicateTaskId, RetiredTaskId, StateConflict, TaskStore,
    TERMINAL_STATES,
)


TASK_GOTO_PLACE = 'goto_place'
TASK_CANCEL = 'cancel'
TASK_QUERY = 'query'
TASK_RELEASE_RECOVERY = 'release_recovery'
RANDOM_PLACE_NAME = '随机点位'
SUPPORTED_TASKS = (TASK_GOTO_PLACE, TASK_CANCEL, TASK_QUERY, TASK_RELEASE_RECOVERY)
STATUS_RUNNING = 'RUNNING'
STATUS_SUCCEEDED = 'SUCCEEDED'
STATUS_FAILED = 'FAILED'
STATUS_INTERRUPTED = 'INTERRUPTED'
EPS = 1e-6  # /map 的 resolution 是 float32，容差不能按 double 设
TASK_ID_RE = re.compile(r'[A-Za-z0-9._:-]{1,128}\Z')

# 点位箭头颜色按序号循环。
MARKER_PALETTE = (
    (0.0, 0.7, 1.0),
    (1.0, 0.55, 0.0),
    (0.4, 0.8, 0.2),
    (0.9, 0.3, 0.6),
    (0.7, 0.4, 1.0),
)
MARKER_ARROW_LENGTH = 0.76
MARKER_TEXT_HEIGHT = 0.35

# 终端日志配色：绿 = 成功里程碑，黄 = 等待/拒绝，红 = 错误。
GREEN = '\033[32m'
YELLOW = '\033[33m'
RED = '\033[31m'
RESET = '\033[0m'


class WaypointNavDispatcher(Node):

    def _ok(self, message: str) -> None:
        self.get_logger().info(f'{GREEN}{message}{RESET}')

    def _warn(self, message: str) -> None:
        self.get_logger().warn(f'{YELLOW}{message}{RESET}')

    def _fail(self, message: str) -> None:
        self.get_logger().error(f'{RED}{message}{RESET}')

    def __init__(self) -> None:
        super().__init__('waypoint_nav_dispatcher')

        # ---- 参数 ----
        self.declare_parameter('waypoints_file', os.path.expanduser('~/.ros/waypoints.yaml'))
        self.declare_parameter('frame_id', 'map')
        self.declare_parameter('task_store_file', os.path.expanduser('~/.ros/waypoint_nav.sqlite3'))
        self.declare_parameter('terminal_retention_sec', 86400.0)
        self.declare_parameter('cancel_confirmation_timeout_sec', 5.0)
        self.declare_parameter('nav_action_name', '/navigate_to_pose')
        self.declare_parameter('client_id', 'marsdog_action_executor')
        self.declare_parameter('random_clearance_m', 0.35)

        self._waypoints_path = str(self.get_parameter('waypoints_file').value)
        self._frame_id = str(self.get_parameter('frame_id').value)
        self._retention_sec = float(self.get_parameter('terminal_retention_sec').value)
        self._cancel_timeout = float(
            self.get_parameter('cancel_confirmation_timeout_sec').value)
        if not math.isfinite(self._cancel_timeout) or self._cancel_timeout <= 0:
            raise ValueError('cancel_confirmation_timeout_sec 必须是有限正数')
        self._client_id = str(self.get_parameter('client_id').value)
        self._random_clearance_m = float(self.get_parameter('random_clearance_m').value)
        if not math.isfinite(self._random_clearance_m) or self._random_clearance_m < 0:
            raise ValueError('random_clearance_m 必须是非负有限数')
        self._store = TaskStore(
            str(self.get_parameter('task_store_file').value), self._retention_sec)

        # ---- 地点数据 ----
        self._waypoints_file = None
        self._live_map = None
        self._binding_error = '尚未收到 /map，点位未校验'
        self._reload_waypoints()
        self.create_subscription(
            OccupancyGrid, 'map', self._on_map,
            QoSProfile(depth=1, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL))

        # ---- Nav2 客户端与持久化恢复 ----
        action_name = str(self.get_parameter('nav_action_name').value).rstrip('/')
        self._nav_action = ActionClient(self, NavigateToPose, action_name)
        self._result_client = self.create_client(
            NavigateToPose.Impl.GetResultService,
            f'{action_name}/_action/get_result')
        self._cancel_client = self.create_client(
            CancelGoal, f'{action_name}/_action/cancel_goal')
        self._goal_handle = None
        self._goal_task_id = ''
        self._cancel_sent = False
        self._cancel_deadline = None
        self._recovery_blocked = False
        self._recovery_query_sent = False
        self._last_cleanup = 0.0
        self._status_publisher = self.create_publisher(
            String, 'waypoint_nav/status', 10)
        # latched：RViz 晚于发布订阅也能显示点位。
        self._marker_publisher = self.create_publisher(
            MarkerArray, 'waypoint_nav/markers',
            QoSProfile(depth=1, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL))
        # ---- Service ----
        self.create_service(VoiceTask, 'waypoint_nav/task', self._handle_task)
        self._recover_startup()
        self.create_timer(0.1, self._tick)
        self._ok(
            f'VoiceTask 服务已就绪: waypoint_nav/task，支持 task_type: '
            f'{"、".join(SUPPORTED_TASKS)}')

        self.get_logger().info(
            f'waypoint_nav_dispatcher 启动，地点文件: {self._waypoints_path}')

    # ---------- RViz 点位标记 ----------

    def _publish_markers(self) -> None:
        """发布点位箭头与 id 文本到 waypoint_nav/markers；仅校验通过后调用。"""
        if self._waypoints_file is None:
            return
        array = MarkerArray()
        wipe = Marker()
        wipe.action = Marker.DELETEALL
        array.markers.append(wipe)
        stamp = self.get_clock().now().to_msg()
        for index, wp in enumerate(self._waypoints_file.waypoints):
            color = MARKER_PALETTE[index % len(MARKER_PALETTE)]
            arrow = Marker()
            arrow.header.frame_id = self._frame_id
            arrow.header.stamp = stamp
            arrow.ns = 'waypoint_nav'
            arrow.id = index * 2
            arrow.type = Marker.ARROW
            arrow.action = Marker.ADD
            arrow.pose.position.x = float(wp.position.get('x', 0.0))
            arrow.pose.position.y = float(wp.position.get('y', 0.0))
            arrow.pose.position.z = float(wp.position.get('z', 0.0)) + 0.05
            arrow.pose.orientation.x = float(wp.orientation.get('x', 0.0))
            arrow.pose.orientation.y = float(wp.orientation.get('y', 0.0))
            arrow.pose.orientation.z = float(wp.orientation.get('z', 0.0))
            arrow.pose.orientation.w = float(wp.orientation.get('w', 1.0))
            arrow.scale.x = MARKER_ARROW_LENGTH
            arrow.scale.y = 0.06
            arrow.scale.z = 0.06
            arrow.color.r, arrow.color.g, arrow.color.b = color
            arrow.color.a = 1.0
            array.markers.append(arrow)

            text = Marker()
            text.header.frame_id = self._frame_id
            text.header.stamp = stamp
            text.ns = 'waypoint_nav'
            text.id = index * 2 + 1
            text.type = Marker.TEXT_VIEW_FACING
            text.action = Marker.ADD
            text.pose.position.x = arrow.pose.position.x
            text.pose.position.y = arrow.pose.position.y
            text.pose.position.z = arrow.pose.position.z + MARKER_TEXT_HEIGHT
            text.scale.z = 0.25
            text.color.r, text.color.g, text.color.b = color
            text.color.a = 1.0
            text.text = wp.id
            array.markers.append(text)
        self._marker_publisher.publish(array)
        self.get_logger().info(
            f'点位标记已发布到 waypoint_nav/markers（{len(self._waypoints_file.waypoints)} 个地点）')

    # ---------- 地点文件 ----------

    def _reload_waypoints(self) -> None:
        try:
            self._waypoints_file = load_waypoints(self._waypoints_path)
        except WaypointsError as exc:
            self._waypoints_file = None
            self._binding_error = str(exc)
            self._fail(f'地点文件加载失败: {exc}')
            return
        self._frame_id = self._waypoints_file.frame_id or self._frame_id
        names = '、'.join(wp.name for wp in self._waypoints_file.waypoints)
        self._ok(
            f'地点文件已加载（{len(self._waypoints_file.waypoints)} 个）: {names}')

    def _on_map(self, msg: OccupancyGrid) -> None:
        """对着活地图校验点位，结论变化时才打日志。"""
        self._live_map = msg
        if self._waypoints_file is None:
            return
        error = self._check_grid(msg)
        if error == self._binding_error:
            return
        self._binding_error = error
        if error:
            self._fail(f'点位与当前地图不匹配: {error}')
        else:
            self._ok('点位已对当前 /map 校验通过')
            self._publish_markers()

    def _check_grid(self, msg: OccupancyGrid) -> str:
        """只确认点位文件与当前地图是同一次标注：分辨率、原点、尺寸。"""
        wf = self._waypoints_file
        info = msg.info
        origin_x = info.origin.position.x
        origin_y = info.origin.position.y
        orientation = info.origin.orientation
        origin_yaw = math.atan2(
            2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
            1.0 - 2.0 * (orientation.y ** 2 + orientation.z ** 2),
        )
        yaw_delta = math.atan2(
            math.sin(origin_yaw - wf.origin[2]),
            math.cos(origin_yaw - wf.origin[2]),
        )
        if abs(info.resolution - wf.resolution) > EPS:
            return f'分辨率 {info.resolution} ≠ 点位文件 {wf.resolution}'
        # 地图 YAML 的 origin 是两位小数舍入值，活地图是全精度，
        # 半栅格容差可覆盖舍入误差，也足以挡住重建地图的漂移。
        origin_eps = info.resolution / 2.0
        if (abs(origin_x - wf.origin[0]) > origin_eps
                or abs(origin_y - wf.origin[1]) > origin_eps
                or abs(yaw_delta) > EPS):
            return (f'原点 ({origin_x}, {origin_y}, {origin_yaw}) ≠ 点位文件 '
                    f'({wf.origin[0]}, {wf.origin[1]}, {wf.origin[2]})')
        if (info.width, info.height) != wf.size:
            return (f'尺寸 {info.width}×{info.height} ≠ 点位文件 '
                    f'{wf.size[0]}×{wf.size[1]}')
        return ''

    # ---------- Service 和协议 ----------

    def _handle_task(self, request, response):
        started = time.monotonic()
        response.task_id = request.task_id
        response.task_type = request.task_type
        response.success = False
        response.result_json = '{}'
        response.error_message = ''
        try:
            if not TASK_ID_RE.fullmatch(request.task_id):
                raise ValueError('task_id 必须为 1～128 位字母、数字或 ._:-')
            params = self._parse_params_json(request.params_json)
            if params.get('protocol_version') != '1.0':
                raise ValueError('protocol_version 必须为 1.0')
            if params.get('client_id') != self._client_id:
                raise ValueError('client_id 不在允许列表')
            if request.task_type == TASK_GOTO_PLACE:
                self._fill_goto(request, response, params)
            elif request.task_type in (TASK_CANCEL, TASK_RELEASE_RECOVERY):
                self._fill_cancel(request, response, params)
            elif request.task_type == TASK_QUERY:
                self._fill_query(response, params)
            else:
                self._reject(response, 'UNSUPPORTED_TASK_TYPE', '不支持的 task_type')
        except (ValueError, TypeError) as exc:
            self._reject(response, 'INVALID_REQUEST', str(exc))
        except Exception as exc:  # noqa: BLE001 - 不能让 Service 回调静默失败
            self._fail(f'task 处理异常: {exc}')
            self._recovery_blocked = True
            self._reject(response, 'INTERNAL_ERROR', f'内部错误: {exc}')
        response.latency_ms = (time.monotonic() - started) * 1000.0
        return response

    @staticmethod
    def _parse_params_json(raw: str) -> dict:
        try:
            params = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f'params_json 不是合法 JSON: {exc}') from exc
        if not isinstance(params, dict):
            raise ValueError('params_json 必须是 JSON object')
        return params

    @staticmethod
    def _require_target(params: dict) -> str:
        target = params.get('target_task_id')
        if not isinstance(target, str) or not TASK_ID_RE.fullmatch(target):
            raise ValueError('target_task_id 无效')
        return target

    def _reject(self, response, code: str, message: str, **fields) -> None:
        response.success = False
        response.error_message = message
        response.result_json = json.dumps({
            'accepted': False, 'code': code, 'message': message, **fields,
        }, ensure_ascii=False)
        self._warn(f'{code}: {message}')

    def _fill_goto(self, request, response, params: dict) -> None:
        place = params.get('place')
        if not isinstance(place, str) or not place.strip():
            raise ValueError('place 必须是非空点位 ID 或地点名称')
        if params.get('preempt', False) is not False:
            raise ValueError('v1 不支持 preempt=true')
        timeout_sec = params.get('timeout_sec')
        if isinstance(timeout_sec, bool) or not isinstance(timeout_sec, (int, float)):
            raise ValueError('timeout_sec 必须是有限正数')
        timeout_sec = float(timeout_sec)
        if not math.isfinite(timeout_sec) or timeout_sec <= 0:
            raise ValueError('timeout_sec 必须是有限正数')
        requested_retention = params.get('terminal_retention_sec', self._retention_sec)
        if (isinstance(requested_retention, bool)
                or not isinstance(requested_retention, (int, float))
                or not math.isfinite(float(requested_retention))
                or float(requested_retention) < 86400):
            raise ValueError('terminal_retention_sec 不能小于 86400')
        if float(requested_retention) > self._retention_sec:
            self._reject(
                response, 'RETENTION_UNAVAILABLE',
                '服务端不能满足请求的终态保留时间')
            return
        if self._store.get(request.task_id) is not None:
            self._reject(
                response, 'DUPLICATE_TASK_ID',
                '该 task_id 已存在，请用 query 恢复状态',
                target_task_id=request.task_id)
            return
        if self._store.is_retired(request.task_id):
            self._reject(
                response, 'TASK_ID_RETIRED', '该 task_id 已过期，不能重新导航',
                target_task_id=request.task_id)
            return
        if self._recovery_blocked:
            self._reject(response, 'RECOVERY_BLOCKED', '导航恢复未确认，拒绝新任务')
            return
        is_random = place.strip() in RANDOM_PLACE_ALIASES
        if not is_random and self._binding_error:
            self._reject(response, 'WAYPOINTS_UNAVAILABLE', self._binding_error)
            return
        if not self._nav_action.server_is_ready():
            self._reject(response, 'NAV2_UNAVAILABLE', 'Nav2 尚未就绪')
            return

        if is_random:
            if self._live_map is None or not self._live_map.header.frame_id:
                self._reject(response, 'RANDOM_MAP_UNAVAILABLE', '尚未收到有效 /map')
                return
            try:
                goal_pose = self._build_random_goal_pose()
            except RandomGoalError as exc:
                self._reject(response, 'RANDOM_TARGET_UNAVAILABLE', str(exc))
                return
            matched_id, resolved_place = RANDOM_PLACE_ID, RANDOM_PLACE_NAME
        else:
            match = match_place(place, self._waypoints_file)
            if not match.matched:
                self._reject(response, 'PLACE_NOT_FOUND', match.reason)
                return
            waypoint = match.waypoint
            goal_pose = self._build_goal_pose(waypoint)
            matched_id, resolved_place = waypoint.id, waypoint.name
        pose = self._pose_to_dict(goal_pose)
        fingerprint = hashlib.sha256(json.dumps(
            {
                'task_type': request.task_type,
                'client_id': self._client_id,
                'params_json': params,
            }, ensure_ascii=False, sort_keys=True, separators=(',', ':')
        ).encode('utf-8')).hexdigest()
        try:
            status = self._store.create(
                task_id=request.task_id,
                client_id=self._client_id,
                request_fingerprint=fingerprint,
                requested_place=RANDOM_PLACE_ID if is_random else place,
                matched_id=matched_id,
                place=resolved_place,
                pose=pose,
                timeout_sec=timeout_sec,
            )
        except DuplicateTaskId:
            self._reject(
                response, 'DUPLICATE_TASK_ID',
                '该 task_id 已存在，请用 query 恢复状态',
                target_task_id=request.task_id)
            return
        except RetiredTaskId:
            self._reject(
                response, 'TASK_ID_RETIRED', '该 task_id 已过期，不能重新导航',
                target_task_id=request.task_id)
            return
        except BusyTask as exc:
            self._reject(
                response, 'BUSY', '已有未决导航任务',
                active_task_id=exc.task_id)
            return
        self._publish_status(status)
        response.success = True
        response.result_json = json.dumps({
            'accepted': True,
            'matched_id': matched_id,
            'place': resolved_place,
            'message': 'accepted',
        }, ensure_ascii=False)
        self._ok(f'导航任务已持久化: {request.task_id} -> {matched_id}')

    def _fill_cancel(self, request, response, params: dict) -> None:
        target = self._require_target(params)
        record = self._store.get(target)
        if record is None:
            code = 'TASK_ID_RETIRED' if self._store.is_retired(target) else 'TARGET_NOT_FOUND'
            self._reject(response, code, '目标任务不存在', target_task_id=target)
            return
        if record['client_id'] != self._client_id:
            self._reject(
                response, 'TARGET_OWNERSHIP_MISMATCH', '目标任务调用方不匹配',
                target_task_id=target)
            return
        if record['terminal']:
            self._reject(
                response, 'ALREADY_TERMINAL', '目标任务已经结束',
                target_task_id=target)
            return
        active = self._store.active()
        if active is None or active['task_id'] != target:
            self._reject(
                response, 'TARGET_NOT_ACTIVE', '目标不是当前活动导航',
                target_task_id=target,
                active_task_id=active['task_id'] if active else '')
            return

        if request.task_type == TASK_RELEASE_RECOVERY:
            if record['code'] != 'RECOVERY_REQUIRED':
                self._reject(response, 'NOT_IN_RECOVERY', 'Task is not in recovery')
                return
            if params.get('operator_confirmed_stopped') is not True:
                self._reject(response, 'OPERATOR_CONFIRMATION_REQUIRED',
                             'Explicit operator confirmation of stopped robot required')
                return
            # Operator attestation, not a Nav2-confirmed stop. Never auto-generated.
            status = self._transition(
                target, {'RECOVERY_REQUIRED'}, STATUS_INTERRUPTED,
                'RECOVERY_RELEASED',
                '操作员解除恢复锁定；Nav2 未能确认该目标状态')
            if status is None:
                self._reject(response, 'INTERNAL_ERROR', '解除状态落盘失败')
                return
            response.success = True
            response.result_json = json.dumps({
                'accepted': True,
                'target_task_id': target,
                'message': '已按操作员确认解除恢复锁定，导航锁已释放',
            }, ensure_ascii=False)
            self._warn(
                f'RECOVERY_RELEASED: {target}: 导航锁已按操作员确认释放；'
                'Nav2 未能确认该目标已停止，下发新目标前请自行确认机器人已停稳')
            return

        if record['code'] == 'RECOVERY_REQUIRED':
            self._store.request_cancel(target, 'client')
            self._start_recovery(self._store.get(target))
            response.success = True
            response.result_json = json.dumps({
                'accepted': True, 'target_task_id': target,
                'message': 'Recovery remains locked until Nav2 confirms a terminal result',
            })
            return

        if record['code'] == 'QUEUED':
            # QUEUED 在发送前被持久化；单线程 executor 保证撤回与下发互斥。
            status = self._transition(
                target, {'QUEUED'}, STATUS_INTERRUPTED, 'CLIENT_CANCELLED',
                '任务在下发 Nav2 前已取消')
            if status is None:
                self._reject(response, 'INTERNAL_ERROR', '取消状态落盘失败')
                return
        else:
            record = self._store.request_cancel(target, 'client')
            if record['code'] == 'NAV2_ACCEPTED':
                status = self._transition(
                    target, {'NAV2_ACCEPTED'}, STATUS_RUNNING, 'NAV2_ACCEPTED',
                    '已受理取消，等待 Nav2 真实结果', safe=False)
                if status is None:
                    self._reject(response, 'INTERNAL_ERROR', '取消状态落盘失败')
                    return
            if self._cancel_deadline is None:
                self._cancel_deadline = time.monotonic() + self._cancel_timeout
            self._request_nav2_cancel(target)
        response.success = True
        response.result_json = json.dumps({
            'accepted': True,
            'target_task_id': target,
            'message': '已受理取消请求，等待真实终态',
        }, ensure_ascii=False)

    def _fill_query(self, response, params: dict) -> None:
        target = self._require_target(params)
        record = self._store.get(target)
        response.success = True
        if record is not None:
            payload = {
                'found': True,
                'target_task_id': target,
                'status': record['status'],
            }
        elif self._store.is_retired(target):
            payload = {
                'found': False,
                'expired': True,
                'code': 'TASK_ID_RETIRED',
                'target_task_id': target,
            }
        else:
            payload = {
                'found': False,
                'expired': False,
                'target_task_id': target,
            }
        response.result_json = json.dumps(payload, ensure_ascii=False)

    # ---------- Nav2 状态机 ----------

    @staticmethod
    def _uuid_message(hex_value: str) -> UUID:
        return UUID(uuid=list(bytes.fromhex(hex_value)))

    @staticmethod
    def _pose_to_dict(pose: PoseStamped) -> dict:
        p = pose.pose.position
        q = pose.pose.orientation
        return {
            'frame_id': pose.header.frame_id,
            'position': {'x': p.x, 'y': p.y, 'z': p.z},
            'orientation': {'x': q.x, 'y': q.y, 'z': q.z, 'w': q.w},
        }

    def _pose_from_record(self, record: dict) -> PoseStamped:
        data = json.loads(record['pose_json'])
        pose = PoseStamped()
        pose.header.frame_id = data['frame_id']
        pose.header.stamp = self.get_clock().now().to_msg()
        for key, value in data['position'].items():
            setattr(pose.pose.position, key, float(value))
        for key, value in data['orientation'].items():
            setattr(pose.pose.orientation, key, float(value))
        return pose

    def _publish_status(self, status: dict) -> None:
        message = String()
        message.data = json.dumps(status, ensure_ascii=False, sort_keys=True)
        self._status_publisher.publish(message)

    def _transition(
        self, task_id: str, expected_codes: set[str], state: str,
        code: str, message: str, safe: bool = False,
        goal_uuid: str | None = None,
    ) -> dict | None:
        try:
            status = self._store.transition(
                task_id, expected_codes=expected_codes, state=state,
                code=code, message=message, safe_to_interrupt=safe,
                nav2_goal_uuid=goal_uuid)
        except StateConflict as exc:
            self._fail(f'任务状态冲突: {exc}')
            self._recovery_blocked = True
            return None
        except Exception as exc:  # noqa: BLE001 - 落盘失败不能发布终态
            self._fail(f'任务状态落盘失败: {exc}')
            self._recovery_blocked = True
            return None
        self._publish_status(status)
        if state in TERMINAL_STATES:
            self._goal_handle = None
            self._goal_task_id = ''
            self._cancel_sent = False
            self._cancel_deadline = None
            self._recovery_blocked = False
            self._recovery_query_sent = False
        return status

    def _recover_startup(self) -> None:
        record = self._store.active()
        if record is None:
            return
        task_id = record['task_id']
        if record['code'] == 'QUEUED':
            # DISPATCHED 必须先落盘再发送，因此 QUEUED 可证明尚未下发。
            self._transition(
                task_id, {'QUEUED'}, STATUS_FAILED, 'INTERNAL_ERROR',
                '导航节点在下发目标前重启，原目标未发送')
            return
        self._recovery_blocked = True
        self._goal_task_id = task_id
        if record['code'] != 'RECOVERY_REQUIRED':
            self._transition(
                task_id, {record['code']}, STATUS_RUNNING, 'RECOVERY_REQUIRED',
                '节点重启，正在核对 Nav2 目标')
        self._warn(f'进入 RECOVERY_BLOCKED: {task_id}')

    def _tick(self) -> None:
        try:
            self._tick_inner()
        except Exception as exc:  # noqa: BLE001 - 定时器不能悄悄失效
            self._recovery_blocked = True
            self._fail(f'导航状态机异常，已阻止新任务: {exc}')

    def _tick_inner(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup >= 60.0:
            self._last_cleanup = now
            try:
                self._store.retire_expired()
            except Exception as exc:  # noqa: BLE001 - 存储故障时拒绝新导航
                self._fail(f'终态清理失败: {exc}')
                self._recovery_blocked = True
        record = self._store.active()
        if record is None:
            return
        task_id = record['task_id']
        code = record['code']
        elapsed = (time.time_ns() // 1_000_000 - record['created_at_ms']) / 1000
        if code == 'QUEUED':
            if self._recovery_blocked:
                return
            if elapsed >= record['timeout_sec']:
                self._transition(
                    task_id, {'QUEUED'}, STATUS_FAILED, 'TIMEOUT',
                    '点位导航在下发前超时')
            elif record['requested_place'] != RANDOM_PLACE_ID and self._binding_error:
                self._transition(
                    task_id, {'QUEUED'}, STATUS_FAILED, 'INTERNAL_ERROR',
                    '下发前地图或地点文件校验失效')
            elif self._nav_action.server_is_ready():
                self._dispatch(record)
            return
        if code == 'RECOVERY_REQUIRED':
            self._recovery_blocked = True
            self._start_recovery(record)
            return
        if code not in {'DISPATCHED', 'NAV2_ACCEPTED'}:
            self._recovery_blocked = True
            self._fail(f'未知的活动状态: {code}')
            return
        if elapsed >= record['timeout_sec'] and not record['cancel_requested']:
            record = self._store.request_cancel(task_id, 'timeout')
            if code == 'NAV2_ACCEPTED':
                self._transition(
                    task_id, {'NAV2_ACCEPTED'}, STATUS_RUNNING, 'NAV2_ACCEPTED',
                    '导航超时，等待 Nav2 确认停止', safe=False)
            self._cancel_deadline = now + self._cancel_timeout
        if record['cancel_requested']:
            if self._cancel_deadline is None:
                self._cancel_deadline = now + self._cancel_timeout
            self._request_nav2_cancel(task_id)
            if now >= self._cancel_deadline:
                self._enter_recovery(
                    task_id,
                    f'取消等待 {self._cancel_timeout:g} 秒后仍未确认 Nav2 停止')

    def _dispatch(self, record: dict) -> None:
        task_id = record['task_id']
        goal_uuid = uuid.uuid4().hex
        status = self._transition(
            task_id, {'QUEUED'}, STATUS_RUNNING, 'DISPATCHED',
            'UUID 和发送意图已持久化，Nav2 是否收到尚未确定',
            goal_uuid=goal_uuid)
        if status is None:
            return
        goal = NavigateToPose.Goal()
        goal.pose = self._pose_from_record(record)
        self._goal_task_id = task_id
        try:
            future = self._nav_action.send_goal_async(
                goal, goal_uuid=self._uuid_message(goal_uuid))
            future.add_done_callback(
                lambda done: self._on_goal_response(task_id, goal_uuid, done))
        except Exception as exc:  # noqa: BLE001 - 发送意图已落盘，结果未知
            self._enter_recovery(task_id, f'Nav2 发送结果未知: {exc}')

    def _on_goal_response(self, task_id: str, goal_uuid: str, future) -> None:
        record = self._store.get(task_id)
        if record is None or record['terminal']:
            return
        try:
            handle = future.result()
        except Exception as exc:  # noqa: BLE001
            self._enter_recovery(task_id, f'Nav2 Goal 响应异常: {exc}')
            return
        if not handle.accepted:
            self._transition(
                task_id, {'DISPATCHED', 'RECOVERY_REQUIRED'},
                STATUS_FAILED, 'GOAL_REJECTED', 'Nav2 拒绝导航目标')
            return
        self._goal_handle = handle
        self._goal_task_id = task_id
        if record['code'] == 'DISPATCHED':
            self._transition(
                task_id, {'DISPATCHED'}, STATUS_RUNNING, 'NAV2_ACCEPTED',
                'Nav2 已接受导航目标',
                safe=not bool(record['cancel_requested']))
        try:
            result_future = handle.get_result_async()
            result_future.add_done_callback(
                lambda done: self._on_goal_result(task_id, done))
        except Exception as exc:  # noqa: BLE001
            self._enter_recovery(task_id, f'Nav2 结果订阅异常: {exc}')
        if record['cancel_requested']:
            self._request_nav2_cancel(task_id)

    def _request_nav2_cancel(self, task_id: str) -> None:
        if self._cancel_sent:
            return
        record = self._store.get(task_id)
        if record is None or record['terminal']:
            return
        if self._goal_handle is None or self._goal_task_id != task_id:
            return  # DISPATCHED 期间等待 Goal 接受结果；恢复流程另用 UUID 服务。
        try:
            future = self._goal_handle.cancel_goal_async()
            self._cancel_sent = True
            future.add_done_callback(
                lambda done: self._on_cancel_ack(task_id, done))
        except Exception as exc:  # noqa: BLE001
            self._enter_recovery(task_id, f'Nav2 取消请求结果未知: {exc}')

    def _on_cancel_ack(self, task_id: str, future) -> None:
        try:
            response = future.result()
            if response.return_code != CancelGoal.Response.ERROR_NONE:
                self._warn(
                    f'取消受理未确认: {task_id}, Nav2 code={response.return_code}')
        except Exception as exc:  # noqa: BLE001
            self._warn(f'取消响应异常，继续等待真实结果: {task_id}: {exc}')

    def _on_goal_result(self, task_id: str, future) -> None:
        try:
            result = future.result()
            self._finish_nav2(task_id, result.status)
        except Exception as exc:  # noqa: BLE001
            self._enter_recovery(task_id, f'Nav2 结果异常: {exc}')

    def _finish_nav2(self, task_id: str, nav_status: int) -> None:
        record = self._store.get(task_id)
        if record is None or record['terminal']:
            return
        expected = {'DISPATCHED', 'NAV2_ACCEPTED', 'RECOVERY_REQUIRED'}
        if nav_status == GoalStatus.STATUS_SUCCEEDED:
            self._transition(
                task_id, expected, STATUS_SUCCEEDED, 'NAV2_SUCCEEDED',
                '已到达目标地点')
        elif nav_status == GoalStatus.STATUS_CANCELED:
            if record['cancel_reason'] == 'client':
                self._transition(
                    task_id, expected, STATUS_INTERRUPTED, 'CLIENT_CANCELLED',
                    'Nav2 已确认目标取消')
            elif record['cancel_reason'] == 'timeout':
                self._transition(
                    task_id, expected, STATUS_FAILED, 'TIMEOUT',
                    '导航超时且 Nav2 已确认停止')
            else:
                self._transition(
                    task_id, expected, STATUS_INTERRUPTED, 'NAV2_CANCELED',
                    'Nav2 已确认目标取消')
        elif nav_status == GoalStatus.STATUS_ABORTED:
            self._transition(
                task_id, expected, STATUS_FAILED, 'NAV2_FAILED',
                'Nav2 返回失败终态')
        else:
            self._enter_recovery(
                task_id, f'Nav2 结果状态无法确认: {nav_status}')

    def _enter_recovery(self, task_id: str, message: str) -> None:
        record = self._store.get(task_id)
        if record is None or record['terminal']:
            return
        self._recovery_blocked = True
        self._goal_task_id = task_id
        if record['code'] != 'RECOVERY_REQUIRED':
            self._transition(
                task_id, {record['code']}, STATUS_RUNNING,
                'RECOVERY_REQUIRED', message, safe=False)
        self._warn(f'RECOVERY_BLOCKED: {task_id}: {message}')

    def _start_recovery(self, record: dict) -> None:
        now = time.monotonic()
        if self._recovery_query_sent or now - getattr(
                self, '_last_recovery_attempt', 0.0) < 2.0:
            return
        self._last_recovery_attempt = now
        goal_uuid = record['nav2_goal_uuid']
        if not goal_uuid:
            self._fail('RECOVERY_REQUIRED 没有 Nav2 UUID，需人工安全处置')
            return
        if (not self._result_client.service_is_ready()
                or not self._cancel_client.service_is_ready()):
            return
        goal_id = self._uuid_message(goal_uuid)
        try:
            result_request = NavigateToPose.Impl.GetResultService.Request()
            result_request.goal_id = goal_id
            result_future = self._result_client.call_async(result_request)
            result_future.add_done_callback(
                lambda done: self._on_recovery_result(record['task_id'], done))
            cancel_request = CancelGoal.Request()
            cancel_request.goal_info.goal_id = goal_id
            cancel_future = self._cancel_client.call_async(cancel_request)
            cancel_future.add_done_callback(
                lambda done: self._on_cancel_ack(record['task_id'], done))
            self._recovery_query_sent = True
            self._ok(f'已按 Nav2 UUID 查询并请求定向取消: {record["task_id"]}')
        except Exception as exc:  # noqa: BLE001
            self._fail(f'UUID 恢复请求失败: {exc}')

    def _on_recovery_result(self, task_id: str, future) -> None:
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001
            self._recovery_query_sent = False
            self._fail(f'UUID 结果查询异常: {task_id}: {exc}')
            return
        if result.status == GoalStatus.STATUS_UNKNOWN:
            # Nav2 是在其服务就绪之后才被问到的（服务没起来 _start_recovery
            # 直接返回，连请求都不发），所以 UNKNOWN 是"Nav2 明确表示不认这个
            # UUID"，不是"暂时问不到"——重复查询不会有不同答案，因此这里保持
            # _recovery_query_sent=True 不再重试，等操作员处置即可。
            self._warn(
                f'Nav2 不知道该 UUID，不能推断目标已停止，导航锁保持: {task_id}；'
                '确认机器人已停稳后，对该 task_id 显式发送 release_recovery 并确认停稳可解除')
            return
        self._finish_nav2(task_id, result.status)

    def _build_goal_pose(self, waypoint) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = self._frame_id
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = float(waypoint.position['x'])
        pose.pose.position.y = float(waypoint.position['y'])
        pose.pose.position.z = float(waypoint.position.get('z', 0.0))
        orientation = waypoint.orientation
        pose.pose.orientation.x = float(orientation['x'])
        pose.pose.orientation.y = float(orientation['y'])
        pose.pose.orientation.z = float(orientation['z'])
        pose.pose.orientation.w = float(orientation['w'])
        return pose

    def _build_random_goal_pose(self) -> PoseStamped:
        x, y = select_random_goal(self._live_map, self._random_clearance_m)
        pose = PoseStamped()
        pose.header.frame_id = self._live_map.header.frame_id
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.w = 1.0
        return pose

    def destroy_node(self):
        self._store.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WaypointNavDispatcher()
    # ActionClient 和 Service 回调由同一个 executor 驱动；回调不做阻塞等待。
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
