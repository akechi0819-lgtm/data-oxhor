"""Local pipeline ledger; delivery decisions remain with the delivery service."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pid_is_dead(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


class RunActiveError(RuntimeError):
    """Another run owns the same pipeline and business day."""


class OpsState:
    def __init__(self, runtime_root: Path):
        self.path = Path(runtime_root) / 'ops_state.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY, pipeline TEXT NOT NULL, biz_day TEXT NOT NULL,
                    status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
                    summary_json TEXT, error_code TEXT, pid INTEGER NOT NULL, heartbeat_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stage_events (
                    event_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES pipeline_runs(run_id),
                    stage TEXT NOT NULL, status TEXT NOT NULL, artifact_sha256 TEXT,
                    data_through TEXT, row_count INTEGER, detail_json TEXT, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS live_pointers (
                    domain TEXT PRIMARY KEY, release_id TEXT, data_through TEXT,
                    updated_at TEXT NOT NULL, verified_bool INTEGER NOT NULL
                );
            ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def acquire(self, run_id, pipeline, biz_day, *, pid=None, stale_after_seconds=300):
        pid = os.getpid() if pid is None else pid
        now = _now()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute(
                "SELECT * FROM pipeline_runs WHERE pipeline = ? AND biz_day = ? AND status = 'running'",
                (pipeline, biz_day),
            ).fetchall()
            for run in active:
                heartbeat = datetime.fromisoformat(run['heartbeat_at'])
                if heartbeat > now - timedelta(seconds=stale_after_seconds) or not _pid_is_dead(run['pid']):
                    raise RunActiveError(f"pipeline already running: {run['run_id']}")
                db.execute(
                    "UPDATE pipeline_runs SET status = 'interrupted', finished_at = ?, error_code = 'STALE_PROCESS' WHERE run_id = ?",
                    (now.isoformat(), run['run_id']),
                )
            db.execute(
                "INSERT INTO pipeline_runs (run_id, pipeline, biz_day, status, started_at, pid, heartbeat_at) VALUES (?, ?, ?, 'running', ?, ?, ?)",
                (run_id, pipeline, biz_day, now.isoformat(), pid, now.isoformat()),
            )

    def heartbeat(self, run_id):
        with self._connect() as db:
            cursor = db.execute("UPDATE pipeline_runs SET heartbeat_at = ? WHERE run_id = ? AND status = 'running'", (_now().isoformat(), run_id))
            if cursor.rowcount != 1:
                raise ValueError('run is not active')

    def record_stage(self, run_id, stage, status, *, artifact_sha256=None, data_through=None, row_count=None, detail=None):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM pipeline_runs WHERE run_id = ? AND status = 'running'", (run_id,)).fetchone() is None:
                raise ValueError('run is not active')
            db.execute(
                'INSERT INTO stage_events (run_id, stage, status, artifact_sha256, data_through, row_count, detail_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (run_id, stage, status, artifact_sha256, data_through, row_count, json.dumps(detail, ensure_ascii=False) if detail is not None else None, _now().isoformat()),
            )

    def end(self, run_id, status, *, summary=None, error_code=None):
        if status == 'running':
            raise ValueError('end status cannot be running')
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE pipeline_runs SET status = ?, finished_at = ?, summary_json = ?, error_code = ? WHERE run_id = ? AND status = 'running'",
                (status, _now().isoformat(), json.dumps(summary, ensure_ascii=False) if summary is not None else None, error_code, run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError('run is not active')

    def observe_pointer(self, domain, release_id, data_through, *, verified):
        with self._connect() as db:
            db.execute('''INSERT INTO live_pointers (domain, release_id, data_through, updated_at, verified_bool)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(domain) DO UPDATE SET
                release_id=excluded.release_id, data_through=excluded.data_through,
                updated_at=excluded.updated_at, verified_bool=excluded.verified_bool''',
                (domain, release_id, data_through, _now().isoformat(), int(verified)))

    def status(self, day=None):
        with self._connect() as db:
            where = ' WHERE biz_day = ?' if day is not None else ''
            args = (day,) if day is not None else ()
            runs = [dict(row) for row in db.execute('SELECT * FROM pipeline_runs' + where + ' ORDER BY started_at', args)]
            stages = [dict(row) for row in db.execute(
                'SELECT stage_events.* FROM stage_events JOIN pipeline_runs USING (run_id)' + where + ' ORDER BY event_id', args)]
            pointers = [dict(row) for row in db.execute('SELECT * FROM live_pointers ORDER BY domain')]
        stale = _now() - timedelta(minutes=5)
        for run in runs:
            if (run['status'] == 'running' and datetime.fromisoformat(run['heartbeat_at']) <= stale
                    and _pid_is_dead(run['pid'])):
                run.update(status='interrupted', error_code='STALE_PROCESS')
        return {'runs': runs, 'stage_events': stages, 'live_pointers': pointers}
