"""Transactional task/event persistence with one local service owner."""

import hashlib
import json
import os
import sqlite3


class TaskStore:
    def __init__(self, root):
        self.lock = (root / '.owner.lock').open('a+b')
        try:
            self.lock.seek(0, 2)
            if not self.lock.tell():
                self.lock.write(b'0')
                self.lock.flush()
            self.lock.seek(0)
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            raise RuntimeError('This service data directory already has an owner') from exc
        try:
            self.db = sqlite3.connect(root / 'tasks.sqlite3')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, state TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(task_id, seq));
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, task_id TEXT NOT NULL);
            ''')
        except Exception:
            if hasattr(self, 'db'):
                self.db.close()
            self.lock.close()
            raise

    def close(self):
        self.db.close()
        self.lock.close()

    @staticmethod
    def request_hash(request):
        return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def replay(self, key, request):
        row = self.db.execute('SELECT request_hash, task_id FROM idempotency WHERE key=?', (key,)).fetchone()
        if row is None:
            return None
        if row[0] != self.request_hash(request):
            raise ValueError('Idempotency key was already used with another request')
        if self.db.execute('SELECT 1 FROM tasks WHERE id=?', (row[1],)).fetchone() is None:
            raise LookupError('The original task has expired from retained history')
        return row[1]

    def insert(self, job, key=None):
        with self.db:
            self.db.execute('INSERT INTO tasks VALUES (?, ?, ?)', (job.id, job.state, json.dumps(job.record())))
            if key:
                self.db.execute('INSERT INTO idempotency VALUES (?, ?, ?)',
                                (key, self.request_hash(job.request), job.id))
            self._event(job)

    def _event(self, job):
        event = job.events[-1]
        self.db.execute('INSERT INTO events VALUES (?, ?, ?)', (job.id, event['id'], json.dumps(event)))

    def save(self, job):
        with self.db:
            self.db.execute('UPDATE tasks SET state=?, data=? WHERE id=?', (job.state, json.dumps(job.record()), job.id))
            self._event(job)

    def checkpoint(self, job):
        with self.db:
            self.db.execute('UPDATE tasks SET state=?, data=? WHERE id=?',
                            (job.state, json.dumps(job.record()), job.id))

    def load(self):
        rows = []
        for (data,) in self.db.execute('SELECT data FROM tasks ORDER BY rowid'):
            row = json.loads(data)
            row['events'] = [json.loads(e[0]) for e in self.db.execute(
                'SELECT data FROM events WHERE task_id=? ORDER BY seq', (row['id'],))]
            rows.append(row)
        return rows

    def prune(self, terminal, keep):
        marks = ','.join('?' for _ in terminal)
        rows = self.db.execute(f'SELECT id FROM tasks WHERE state IN ({marks}) ORDER BY rowid DESC',
                               tuple(terminal)).fetchall()
        removed = [r[0] for r in rows[keep:]]
        with self.db:
            self.db.executemany('DELETE FROM tasks WHERE id=?', [(task_id,) for task_id in removed])
        return removed
