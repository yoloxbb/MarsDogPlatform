"""Durable task records for the waypoint navigation wire protocol."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any


TERMINAL_STATES = frozenset({'SUCCEEDED', 'FAILED', 'INTERRUPTED'})


class TaskStoreError(RuntimeError):
    pass


class DuplicateTaskId(TaskStoreError):
    pass


class RetiredTaskId(TaskStoreError):
    pass


class BusyTask(TaskStoreError):
    def __init__(self, task_id: str) -> None:
        super().__init__(task_id)
        self.task_id = task_id


class StateConflict(TaskStoreError):
    pass


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class TaskStore:
    """SQLite/WAL task store. Every public status is committed before publication."""

    def __init__(self, path: str, terminal_retention_sec: float) -> None:
        self.path = os.path.expanduser(path)
        self.terminal_retention_sec = float(terminal_retention_sec)
        if self.terminal_retention_sec < 86400:
            raise ValueError('terminal_retention_sec 不能小于 86400')
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            self.path, timeout=5.0, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('PRAGMA synchronous=FULL')
        self._db.execute('PRAGMA busy_timeout=5000')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                requested_place TEXT NOT NULL,
                pose_json TEXT NOT NULL,
                timeout_sec REAL NOT NULL,
                nav2_goal_uuid TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                cancel_reason TEXT NOT NULL DEFAULT '',
                status_json TEXT NOT NULL,
                state TEXT NOT NULL,
                code TEXT NOT NULL,
                terminal INTEGER NOT NULL,
                active_slot INTEGER UNIQUE,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                terminal_at_ms INTEGER
            );
            CREATE INDEX IF NOT EXISTS tasks_terminal_at
                ON tasks(terminal_at_ms);
            CREATE TABLE IF NOT EXISTS tombstones (
                task_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                retired_at_ms INTEGER NOT NULL
            );
        ''')

    @staticmethod
    def _record(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        record = dict(row)
        record['status'] = json.loads(record.pop('status_json'))
        return record

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._record(self._db.execute(
                'SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone())

    def is_retired(self, task_id: str) -> bool:
        with self._lock:
            return self._db.execute(
                'SELECT 1 FROM tombstones WHERE task_id=?', (task_id,)
            ).fetchone() is not None

    def active(self) -> dict[str, Any] | None:
        with self._lock:
            return self._record(self._db.execute(
                'SELECT * FROM tasks WHERE active_slot=1').fetchone())

    def create(
        self, *, task_id: str, client_id: str, request_fingerprint: str,
        requested_place: str, matched_id: str, place: str,
        pose: dict[str, Any], timeout_sec: float,
    ) -> dict[str, Any]:
        now = _now_ms()
        status = {
            'task_id': task_id,
            'task_type': 'goto_place',
            'state': 'RUNNING',
            'code': 'QUEUED',
            'matched_id': matched_id,
            'place': place,
            'message': '任务已持久化，等待下发',
            'safe_to_interrupt': True,
            'sequence': 1,
        }
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                if self._db.execute(
                    'SELECT 1 FROM tasks WHERE task_id=?', (task_id,)
                ).fetchone() is not None:
                    raise DuplicateTaskId(task_id)
                if self._db.execute(
                    'SELECT 1 FROM tombstones WHERE task_id=?', (task_id,)
                ).fetchone() is not None:
                    raise RetiredTaskId(task_id)
                active = self._db.execute(
                    'SELECT task_id FROM tasks WHERE active_slot=1'
                ).fetchone()
                if active is not None:
                    raise BusyTask(active['task_id'])
                self._db.execute('''
                    INSERT INTO tasks (
                        task_id, client_id, request_fingerprint, requested_place,
                        pose_json, timeout_sec, status_json, state, code,
                        terminal, active_slot, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING', 'QUEUED', 0, 1, ?, ?)
                ''', (
                    task_id, client_id, request_fingerprint, requested_place,
                    json.dumps(pose, sort_keys=True), timeout_sec,
                    json.dumps(status, ensure_ascii=False, sort_keys=True), now, now,
                ))
                self._db.execute('COMMIT')
            except Exception:
                self._db.execute('ROLLBACK')
                raise
        return status

    def transition(
        self, task_id: str, *, expected_codes: set[str], state: str,
        code: str, message: str, safe_to_interrupt: bool = False,
        nav2_goal_uuid: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                row = self._db.execute(
                    'SELECT * FROM tasks WHERE task_id=?', (task_id,)
                ).fetchone()
                if row is None or row['code'] not in expected_codes or row['terminal']:
                    raise StateConflict(f'{task_id}: 状态不允许转为 {state}/{code}')
                old = json.loads(row['status_json'])
                status = {
                    **old,
                    'state': state,
                    'code': code,
                    'message': message,
                    'safe_to_interrupt': bool(safe_to_interrupt),
                    'sequence': old['sequence'] + 1,
                }
                now = _now_ms()
                terminal = state in TERMINAL_STATES
                self._db.execute('''
                    UPDATE tasks SET status_json=?, state=?, code=?, terminal=?,
                        active_slot=?, nav2_goal_uuid=COALESCE(?, nav2_goal_uuid),
                        updated_at_ms=?, terminal_at_ms=?
                    WHERE task_id=?
                ''', (
                    json.dumps(status, ensure_ascii=False, sort_keys=True),
                    state, code, int(terminal), None if terminal else 1,
                    nav2_goal_uuid, now, now if terminal else None, task_id,
                ))
                self._db.execute('COMMIT')
            except Exception:
                self._db.execute('ROLLBACK')
                raise
        return status

    def request_cancel(self, task_id: str, reason: str) -> dict[str, Any]:
        """Persist cancellation intent before acknowledging the cancel service."""
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                row = self._db.execute(
                    'SELECT * FROM tasks WHERE task_id=?', (task_id,)
                ).fetchone()
                if row is None or row['terminal']:
                    raise StateConflict(f'{task_id}: 没有未决任务')
                if not row['cancel_requested']:
                    self._db.execute('''
                        UPDATE tasks SET cancel_requested=1, cancel_reason=?,
                            updated_at_ms=? WHERE task_id=?
                    ''', (reason, _now_ms(), task_id))
                self._db.execute('COMMIT')
            except Exception:
                self._db.execute('ROLLBACK')
                raise
        return self.get(task_id)

    def retire_expired(self) -> int:
        cutoff = _now_ms() - int(self.terminal_retention_sec * 1000)
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                rows = self._db.execute('''
                    SELECT task_id, client_id FROM tasks
                    WHERE terminal=1 AND terminal_at_ms<=?
                ''', (cutoff,)).fetchall()
                for row in rows:
                    self._db.execute('''
                        INSERT OR IGNORE INTO tombstones
                            (task_id, client_id, retired_at_ms) VALUES (?, ?, ?)
                    ''', (row['task_id'], row['client_id'], _now_ms()))
                self._db.execute('''
                    DELETE FROM tasks WHERE terminal=1 AND terminal_at_ms<=?
                ''', (cutoff,))
                self._db.execute('COMMIT')
            except Exception:
                self._db.execute('ROLLBACK')
                raise
        return len(rows)

    def close(self) -> None:
        with self._lock:
            self._db.close()
