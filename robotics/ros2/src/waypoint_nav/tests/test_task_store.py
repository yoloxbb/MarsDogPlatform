"""Durable navigation invariants that do not require a running ROS graph."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from waypoint_nav.task_store import (
    BusyTask, DuplicateTaskId, RetiredTaskId, StateConflict, TaskStore,
)


class TaskStoreTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'tasks.sqlite3')
        self.store = TaskStore(self.path, 86400)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def create(self, task_id='action:one:waypoint'):
        return self.store.create(
            task_id=task_id,
            client_id='marsdog_action_executor',
            request_fingerprint='fingerprint',
            requested_place='C', matched_id='C', place='food',
            pose={'frame_id': 'map'}, timeout_sec=120.0,
        )

    def test_single_active_and_durable_sequence(self):
        queued = self.create()
        self.assertEqual(queued['sequence'], 1)
        with self.assertRaises(BusyTask):
            self.create('action:two:waypoint')
        with self.assertRaises(DuplicateTaskId):
            self.create()

        dispatched = self.store.transition(
            'action:one:waypoint', expected_codes={'QUEUED'},
            state='RUNNING', code='DISPATCHED', message='发送意图已落盘',
            nav2_goal_uuid='a' * 32)
        self.assertEqual(dispatched['sequence'], 2)
        self.assertEqual(self.store.active()['nav2_goal_uuid'], 'a' * 32)
        self.store.close()
        self.store = TaskStore(self.path, 86400)
        self.assertEqual(self.store.active()['status']['code'], 'DISPATCHED')

        accepted = self.store.transition(
            'action:one:waypoint', expected_codes={'DISPATCHED'},
            state='RUNNING', code='NAV2_ACCEPTED', message='已接受',
            safe_to_interrupt=True)
        self.assertEqual(accepted['sequence'], 3)
        self.store.request_cancel('action:one:waypoint', 'client')
        terminal = self.store.transition(
            'action:one:waypoint', expected_codes={'NAV2_ACCEPTED'},
            state='INTERRUPTED', code='CLIENT_CANCELLED',
            message='已确认取消')
        self.assertEqual(terminal['sequence'], 4)
        self.assertIsNone(self.store.active())
        self.create('action:two:waypoint')

    def test_retired_id_never_starts_again(self):
        self.create()
        self.store.transition(
            'action:one:waypoint', expected_codes={'QUEUED'},
            state='FAILED', code='TIMEOUT', message='未下发即超时')
        with sqlite3.connect(self.path) as db:
            db.execute(
                'UPDATE tasks SET terminal_at_ms=0 WHERE task_id=?',
                ('action:one:waypoint',))
        self.assertEqual(self.store.retire_expired(), 1)
        self.assertIsNone(self.store.get('action:one:waypoint'))
        self.assertTrue(self.store.is_retired('action:one:waypoint'))
        with self.assertRaises(RetiredTaskId):
            self.create()

    def test_illegal_transition_keeps_original_status(self):
        self.create()
        with self.assertRaises(StateConflict):
            self.store.transition(
                'action:one:waypoint', expected_codes={'NAV2_ACCEPTED'},
                state='SUCCEEDED', code='NAV2_SUCCEEDED', message='错误终态')
        self.assertEqual(self.store.active()['status']['code'], 'QUEUED')


if __name__ == '__main__':
    unittest.main()
