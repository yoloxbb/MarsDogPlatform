"""Exercise the v1 service against an isolated fake Nav2 action server."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

try:
    import rclpy
    from nav_msgs.msg import OccupancyGrid
    from nav2_msgs.action import NavigateToPose
    from marsdog_voice_interaction.srv import VoiceTask
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
    from waypoint_nav.matcher import Waypoint, WaypointsFile
    from waypoint_nav.task_store import TaskStore
    from waypoint_nav.waypoint_nav_dispatcher import WaypointNavDispatcher
except ImportError:
    rclpy = None


@unittest.skipIf(rclpy is None, '需要板端 ROS 2 Humble 环境')
class WireIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store_path = str(Path(self.temp.name) / 'tasks.sqlite3')
        rclpy.init(args=[
            '--ros-args',
            '-p', f'task_store_file:={self.store_path}',
            '-p', 'nav_action_name:=/waypoint_nav_test_navigate_to_pose',
        ])
        self.fake = rclpy.create_node('waypoint_nav_test_nav2')
        self.goal_count = 0
        self.goal_started = threading.Event()
        self.accept_delay = 0.0
        self.action = ActionServer(
            self.fake, NavigateToPose,
            '/waypoint_nav_test_navigate_to_pose',
            self._execute_goal,
            goal_callback=self._accept_goal,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=ReentrantCallbackGroup(),
            result_timeout=30)
        self.dispatcher = WaypointNavDispatcher()
        self.waypoints_file = WaypointsFile(
            version=1, frame_id='map', map='test.pgm', resolution=0.05,
            origin=(0.0, 0.0, 0.0), size=(10, 10),
            waypoints=[
                Waypoint(
                    id='C', name='food',
                    position={'x': 1.0, 'y': 2.0, 'z': 0.0},
                    orientation={'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                ),
                Waypoint(
                    id='A', name='客厅',
                    position={'x': 3.0, 'y': 4.0, 'z': 0.0},
                    orientation={'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0},
                ),
            ],
        )
        self.dispatcher._waypoints_file = self.waypoints_file
        self.dispatcher._binding_error = ''
        self.client_node = rclpy.create_node('waypoint_nav_test_client')
        self.client = self.client_node.create_client(
            VoiceTask, '/waypoint_nav/task')
        self.executor = MultiThreadedExecutor(num_threads=4)
        for node in (self.fake, self.client_node):
            self.executor.add_node(node)
        self.spin_thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.spin_thread.start()
        self._start_dispatcher()
        self.assertTrue(self.client.wait_for_service(timeout_sec=5))
        self.assertTrue(self.dispatcher._nav_action.wait_for_server(timeout_sec=5))

    def _start_dispatcher(self):
        # Own executor permits safe destruction without stopping a running fake Nav2.
        self.dispatcher_executor = SingleThreadedExecutor()
        self.dispatcher_executor.add_node(self.dispatcher)
        self.dispatcher_thread = threading.Thread(
            target=self.dispatcher_executor.spin, daemon=True)
        self.dispatcher_thread.start()

    def _stop_dispatcher(self):
        self.dispatcher_executor.shutdown(timeout_sec=5)
        self.dispatcher_thread.join(timeout=5)
        self.assertFalse(self.dispatcher_thread.is_alive())
        self.dispatcher_executor.remove_node(self.dispatcher)

    def tearDown(self):
        self._stop_dispatcher()
        self.executor.shutdown(timeout_sec=5)
        self.spin_thread.join(timeout=5)
        self.action.destroy()
        for node in (self.client_node, self.dispatcher, self.fake):
            node.destroy_node()
        rclpy.shutdown()
        self.temp.cleanup()

    def _execute_goal(self, goal_handle):
        self.goal_count += 1
        self.goal_started.set()
        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                return NavigateToPose.Result()
            time.sleep(0.01)
        goal_handle.abort()
        return NavigateToPose.Result()

    def _accept_goal(self, _):
        time.sleep(self.accept_delay)
        return GoalResponse.ACCEPT

    def _call(self, task_id, task_type, extra):
        request = VoiceTask.Request()
        request.task_id = task_id
        request.task_type = task_type
        request.params_json = json.dumps({
            'protocol_version': '1.0',
            'client_id': 'marsdog_action_executor',
            **extra,
        })
        future = self.client.call_async(request)
        deadline = time.monotonic() + 5
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(future.done(), task_type)
        result = future.result()
        return result, json.loads(result.result_json)

    def _query(self):
        return self._call(
            f'query:wire:{time.time_ns()}', 'query',
            {'target_task_id': 'action:wire:1'})

    def _replace_dispatcher(self):
        self._stop_dispatcher()
        self.dispatcher.destroy_node()
        self.dispatcher = WaypointNavDispatcher()
        self._start_dispatcher()

    def test_random_target_uses_live_map_without_waypoint_binding(self):
        grid = OccupancyGrid()
        grid.header.frame_id = 'map'
        grid.info.width = 40
        grid.info.height = 40
        grid.info.resolution = 0.05
        grid.info.origin.orientation.w = 1.0
        grid.data = [0] * (40 * 40)
        self.dispatcher._live_map = grid
        self.dispatcher._binding_error = '地点文件与地图不匹配'

        response, body = self._call(
            'action:wire:1', 'goto_place', {
                'place': ' 11 ', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertTrue(response.success)
        self.assertEqual(body['matched_id'], '11')
        self.assertEqual(body['place'], '随机点位')
        record = self.dispatcher._store.get('action:wire:1')
        pose = json.loads(record['pose_json'])
        self.assertEqual(record['requested_place'], '11')
        self.assertEqual(pose['frame_id'], 'map')
        self.assertGreaterEqual(pose['position']['x'], 0.5)
        self.assertLess(pose['position']['x'], 1.5)
        self.assertTrue(self.goal_started.wait(timeout=5))

        duplicate, body = self._call(
            'action:wire:1', 'goto_place', {
                'place': '11', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertFalse(duplicate.success)
        self.assertEqual(body['code'], 'DUPLICATE_TASK_ID')
        self.assertEqual(self.goal_count, 1)

    def test_random_target_accepts_k_alias_and_normalizes_status(self):
        grid = OccupancyGrid()
        grid.header.frame_id = 'map'
        grid.info.width = 40
        grid.info.height = 40
        grid.info.resolution = 0.05
        grid.info.origin.orientation.w = 1.0
        grid.data = [0] * (40 * 40)
        self.dispatcher._live_map = grid
        self.dispatcher._binding_error = '地点文件与地图不匹配'

        response, body = self._call(
            'action:wire:1', 'goto_place', {
                'place': ' K ', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertTrue(response.success)
        self.assertEqual(body['matched_id'], '11')
        self.assertEqual(body['place'], '随机点位')
        record = self.dispatcher._store.get('action:wire:1')
        self.assertEqual(record['requested_place'], '11')
        self.assertTrue(self.goal_started.wait(timeout=5))

    def test_targeted_cancel_and_duplicate_do_not_start_second_goal(self):
        response, body = self._call(
            'action:wire:1', 'goto_place', {
                'place': '客厅', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertTrue(response.success)
        self.assertEqual(body['matched_id'], 'A')
        self.assertEqual(body['place'], '客厅')
        self.assertTrue(self.goal_started.wait(timeout=5))
        _, current = self._query()
        self.assertEqual(current['status']['matched_id'], 'A')
        self.assertEqual(current['status']['place'], '客厅')

        duplicate, body = self._call(
            'action:wire:1', 'goto_place', {
                'place': '客厅', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertFalse(duplicate.success)
        self.assertEqual(body['code'], 'DUPLICATE_TASK_ID')
        wrong, body = self._call(
            'cancel:wire:wrong', 'cancel',
            {'target_task_id': 'action:other:1'})
        self.assertFalse(wrong.success)
        self.assertEqual(body['code'], 'TARGET_NOT_FOUND')

        cancel, body = self._call(
            'cancel:wire:right', 'cancel',
            {'target_task_id': 'action:wire:1'})
        self.assertTrue(cancel.success)
        self.assertEqual(body['target_task_id'], 'action:wire:1')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            query, body = self._query()
            self.assertTrue(query.success)
            if body['status']['state'] == 'INTERRUPTED':
                self.assertEqual(body['status']['code'], 'CLIENT_CANCELLED')
                self.assertEqual(self.goal_count, 1)
                return
            time.sleep(0.05)
        self.fail('未在 5 秒内获得 Nav2 真实取消终态')

    def test_restart_uses_persisted_uuid_to_cancel_original_goal(self):
        response, _ = self._call(
            'action:wire:1', 'goto_place', {
                'place': 'C', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertTrue(response.success)
        self.assertTrue(self.goal_started.wait(timeout=5))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, body = self._query()
            if body['status']['code'] == 'NAV2_ACCEPTED':
                break
            time.sleep(0.05)
        else:
            self.fail('Nav2 没有接受测试目标')

        # 仅替换导航节点；假 Nav2 的原 Goal 继续执行，模拟客户端重启。
        self._replace_dispatcher()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, body = self._query()
            status = body['status']
            if status['state'] == 'INTERRUPTED':
                self.assertEqual(status['code'], 'NAV2_CANCELED')
                self.assertEqual(self.goal_count, 1)
                return
            self.assertEqual(status['code'], 'RECOVERY_REQUIRED')
            time.sleep(0.05)
        self.fail('重启后没有按持久化 UUID 得到真实终态')

    def test_unknown_uuid_remains_blocked(self):
        self._stop_dispatcher()
        self.dispatcher.destroy_node()
        store = TaskStore(self.store_path, 86400)
        store.create(
            task_id='action:wire:1', client_id='marsdog_action_executor',
            request_fingerprint='fingerprint', requested_place='C',
            matched_id='C', place='food', pose={'frame_id': 'map'},
            timeout_sec=30.0)
        store.transition(
            'action:wire:1', expected_codes={'QUEUED'},
            state='RUNNING', code='DISPATCHED',
            message='发送意图已落盘', nav2_goal_uuid='a' * 32)
        store.close()
        self.dispatcher = WaypointNavDispatcher()
        self._start_dispatcher()
        time.sleep(0.3)
        _, body = self._query()
        self.assertEqual(body['status']['code'], 'RECOVERY_REQUIRED')
        response, body = self._call(
            'action:wire:2', 'goto_place', {
                'place': 'C', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertFalse(response.success)
        self.assertEqual(body['code'], 'RECOVERY_BLOCKED')
        self.assertEqual(self.goal_count, 0)

    def test_only_explicit_operator_release_unlocks_stale_recovery(self):
        """Automatic cancellation cannot stand in for operator stop confirmation."""
        self._stop_dispatcher()
        self.dispatcher.destroy_node()
        store = TaskStore(self.store_path, 86400)
        store.create(
            task_id='action:wire:1', client_id='marsdog_action_executor',
            request_fingerprint='fingerprint', requested_place='C',
            matched_id='C', place='food', pose={'frame_id': 'map'},
            timeout_sec=30.0)
        store.transition(
            'action:wire:1', expected_codes={'QUEUED'},
            state='RUNNING', code='DISPATCHED',
            message='发送意图已落盘', nav2_goal_uuid='a' * 32)
        store.close()
        self.dispatcher = WaypointNavDispatcher()
        self.dispatcher._waypoints_file = self.waypoints_file
        self.dispatcher._binding_error = ''
        self._start_dispatcher()

        # 先等恢复通道真的发过一次 UUID 查询：要证明的是「查询无果之后操作员
        # 仍能解除」，而不是「锁还没建好时的运气」。
        deadline = time.monotonic() + 5
        while (not self.dispatcher._recovery_query_sent
               and time.monotonic() < deadline):
            time.sleep(0.02)
        self.assertTrue(self.dispatcher._recovery_query_sent)
        self.assertTrue(self.dispatcher._recovery_blocked)

        blocked, body = self._call(
            'action:wire:2', 'goto_place', {
                'place': 'C', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertFalse(blocked.success)
        self.assertEqual(body['code'], 'RECOVERY_BLOCKED')

        automatic, body = self._call(
            'cancel:wire:auto', 'cancel', {'target_task_id': 'action:wire:1'})
        self.assertTrue(automatic.success)
        self.assertTrue(self.dispatcher._recovery_blocked)
        self.assertFalse(self.dispatcher._store.get('action:wire:1')['terminal'])
        for confirmation in (None, False, 'true', 1):
            denied, body = self._call(
                'release:wire:denied', 'release_recovery', {
                    'target_task_id': 'action:wire:1',
                    'operator_confirmed_stopped': confirmation})
            self.assertFalse(denied.success)
            self.assertEqual(body['code'], 'OPERATOR_CONFIRMATION_REQUIRED')
            self.assertTrue(self.dispatcher._recovery_blocked)

        released, body = self._call(
            'release:wire:confirmed', 'release_recovery', {
                'target_task_id': 'action:wire:1',
                'operator_confirmed_stopped': True})
        self.assertTrue(released.success)
        self.assertEqual(body['target_task_id'], 'action:wire:1')
        self.assertFalse(self.dispatcher._recovery_blocked)
        record = self.dispatcher._store.get('action:wire:1')
        self.assertTrue(record['terminal'])
        self.assertEqual(record['status']['state'], 'INTERRUPTED')
        self.assertEqual(record['status']['code'], 'RECOVERY_RELEASED')
        self.assertIsNone(self.dispatcher._store.active())

        allowed, body = self._call(
            'action:wire:2', 'goto_place', {
                'place': 'C', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertTrue(allowed.success, body)
        self.assertEqual(body['matched_id'], 'C')
        self.assertTrue(self.goal_started.wait(timeout=5))

        # 释放是终态：重复 cancel 不再受理，避免二次改动已经放行的锁。
        again, body = self._call(
            'cancel:wire:release-2', 'cancel',
            {'target_task_id': 'action:wire:1'})
        self.assertFalse(again.success)
        self.assertEqual(body['code'], 'ALREADY_TERMINAL')

    def test_queued_restart_confirms_goal_was_not_sent(self):
        self._stop_dispatcher()
        self.dispatcher.destroy_node()
        store = TaskStore(self.store_path, 86400)
        store.create(
            task_id='action:wire:1', client_id='marsdog_action_executor',
            request_fingerprint='fingerprint', requested_place='C',
            matched_id='C', place='food', pose={'frame_id': 'map'},
            timeout_sec=30.0)
        store.close()
        self.dispatcher = WaypointNavDispatcher()
        self._start_dispatcher()
        _, body = self._query()
        self.assertEqual(body['status']['state'], 'FAILED')
        self.assertEqual(body['status']['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.goal_count, 0)

    def test_cancel_during_dispatched_waits_for_nav2_result(self):
        self.accept_delay = 0.4
        response, _ = self._call(
            'action:wire:1', 'goto_place', {
                'place': 'C', 'timeout_sec': 30.0,
                'preempt': False, 'terminal_retention_sec': 86400,
            })
        self.assertTrue(response.success)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, body = self._query()
            if body['status']['code'] == 'DISPATCHED':
                break
            time.sleep(0.02)
        else:
            self.fail('没有观察到 DISPATCHED 状态')
        cancel, _ = self._call(
            'cancel:wire:dispatch', 'cancel',
            {'target_task_id': 'action:wire:1'})
        self.assertTrue(cancel.success)
        _, body = self._query()
        self.assertNotIn(body['status']['state'], {'SUCCEEDED', 'FAILED', 'INTERRUPTED'})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, body = self._query()
            if body['status']['state'] == 'INTERRUPTED':
                self.assertEqual(body['status']['code'], 'CLIENT_CANCELLED')
                self.assertEqual(self.goal_count, 1)
                return
            time.sleep(0.05)
        self.fail('DISPATCHED 取消后没有得到真实终态')


if __name__ == '__main__':
    unittest.main()
