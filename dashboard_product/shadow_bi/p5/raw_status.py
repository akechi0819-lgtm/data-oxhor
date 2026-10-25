"""Sanitized receiver-visible projection; private compute state is never exposed."""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import tempfile
from dashboard_product.shadow_bi.p5.raw_inputs import BATCH, _json

SCHEMA = 'shadow_raw_status.v1'
STATUSES = frozenset({'queued', 'running', 'prepared', 'failed', 'timed_out', 'interrupted', 'rejected'})
ERRORS = frozenset({'invalid_queue_item', 'batch_conflict', 'input_rejected', 'compute_failed', 'invalid_compute_result'})
MAX_STATUS_BYTES = 2048


def read_regular(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= limit:
            raise ValueError('regular bounded file required')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('file exceeds limit')
        return raw
    finally:
        os.close(fd)


def validate(value: dict, batch: str) -> dict:
    required = {'schema_version', 'batch_id', 'status', 'published'}
    if not isinstance(value, dict) or set(value) not in (required, required | {'error_code'}):
        raise ValueError('status contains unapproved fields')
    if (value['schema_version'] != SCHEMA or not BATCH.fullmatch(batch)
            or value['batch_id'] != batch or not isinstance(value['status'],str) or value['status'] not in STATUSES
            or value['published'] is not False):
        raise ValueError('status identity invalid')
    if 'error_code' in value and value['error_code'] not in ERRORS:
        raise ValueError('unknown status error')
    return value


def read(root: Path, batch: str, owner_uid: int | None = None) -> dict:
    if not BATCH.fullmatch(batch) or root.is_symlink():
        raise ValueError('unsafe status path')
    if owner_uid is not None and (root.stat().st_uid!=owner_uid or root.stat().st_mode & 0o022):
        raise ValueError('status projection ownership invalid')
    return validate(_json(read_regular(root / (batch + '.json'), MAX_STATUS_BYTES)), batch)


def publish(root: Path, batch: str, status: str, error_code: str | None = None) -> dict:
    value = {'schema_version': SCHEMA, 'batch_id': batch, 'status': status, 'published': False}
    if error_code:
        value['error_code'] = error_code
    validate(value, batch)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('status root must be provisioned separately')
    # Deployment provisions this directory as worker:shadowbi 2750. Only the
    # small sanitized file overrides the worker's private umask; no raw paths.
    atomic_json(root, batch + '.json', value)
    return value


def atomic_json(root: Path, filename: str, value: dict, mode: int = 0o640):
    fd, name = tempfile.mkstemp(prefix='.' + filename + '-', dir=root)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(root / filename)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)
