"""Read an operator-reviewed upstream watermark from a protected, fixed directory.

An upload declaration, export completion time, ETL refresh timestamp, or maximum
transaction date is not a completion attestation. No HTTP route installs evidence.
Root approval is the trust boundary: the reviewer must inspect the upstream
completion-day evidence and its connection to this exact export/window. Merely
placing arbitrary capture bytes here is not independent source authentication.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime
import hashlib
import os
from pathlib import Path
import stat
from zoneinfo import ZoneInfo
from dashboard_product.management.cutoff import VerifiedCompletion
from dashboard_product.shadow_bi.p5.raw_inputs import BATCH, _json, sha
from dashboard_product.shadow_bi.p5.raw_status import read_regular

ROOT = Path('/var/lib/shadow-bi/raw-control/source-completion')
SCHEMA = 'shadow_source_completion.v1'


def binding(received):
    m = _json((received/'manifest.json').read_bytes())
    receipt = _json((received/'received.json').read_bytes())
    digest = sha(received/'payload.tar')
    if receipt['archive_sha256'] != digest or received.name != m['batch_id']:
        raise ValueError('received completion binding changed')
    files = {key: sha(received/'inputs'/(key+'.xlsx')) for key in ('orders', 'cash', 'tencent')}
    if any(files[key] != m['files'][key]['sha256'] for key in files):
        raise ValueError('completion input changed')
    return {key: m[key] for key in ('batch_id', 'company_id', 'as_of_date', 'data_through',
                                  'bi_window', 'refresh_months')} | {
        'archive_sha256': digest, 'files': files}


def _trusted(meta, owner_uid, directory=False):
    required = stat.S_ISDIR if directory else stat.S_ISREG
    if not required(meta.st_mode) or meta.st_uid != owner_uid or meta.st_mode & 0o022:
        raise ValueError('completion evidence is not protected')


@contextmanager
def _directory(name, *, parent=None, owner_uid=0):
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        _trusted(os.fstat(fd), owner_uid, directory=True)
        yield fd
    finally:
        os.close(fd)


def _read(fd, name, limit, owner_uid):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        meta = os.fstat(handle); _trusted(meta, owner_uid)
        if not 0 < meta.st_size <= limit:
            raise ValueError('completion evidence exceeds bound')
        with os.fdopen(handle, 'rb', closefd=False) as stream:
            data = stream.read(limit+1)
        if len(data) != meta.st_size:
            raise ValueError('completion evidence changed while reading')
        return data
    finally:
        os.close(handle)


def _load(root, expected, *, owner_uid=0, now=None):
    """Private parser seam; production always uses fixed ROOT and owner UID 0."""
    batch = expected['batch_id']
    if not BATCH.fullmatch(batch):
        raise ValueError('invalid completion batch')
    with _directory(root.parent, owner_uid=owner_uid) as control:
        with _directory(root.name, parent=control, owner_uid=owner_uid) as evidence:
            with _directory(batch, parent=evidence, owner_uid=owner_uid) as folder:
                raw = _read(folder, 'approval.json', 16384, owner_uid)
                value = _json(raw)
                if (set(value) != {'schema_version', 'binding', 'reviewed_at', 'sources'}
                        or value['schema_version'] != SCHEMA or value['binding'] != expected
                        or set(value['sources']) != {'orders', 'cash'}):
                    raise ValueError('completion approval binding differs')
                reviewed = datetime.fromisoformat(value['reviewed_at'])
                current = now or datetime.now(ZoneInfo('Asia/Shanghai'))
                if (reviewed.tzinfo is None or reviewed > current or reviewed.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
                        != expected['as_of_date']):
                    raise ValueError('completion approval date differs')
                for key in ('orders', 'cash'):
                    source = value['sources'][key]
                    if (set(source) != {'kind', 'source_id', 'complete_through', 'evidence_sha256'}
                            or source['kind'] != 'upstream_completion_watermark'
                            or source['source_id'] != {'orders':'br_work_orders', 'cash':'br_cash'}[key]
                            or source['complete_through'] != expected['data_through']):
                        raise ValueError('source completion watermark required')
                    capture = _read(folder, key+'.evidence', 2*1024**2, owner_uid)
                    if hashlib.sha256(capture).hexdigest() != source['evidence_sha256']:
                        raise ValueError('completion evidence digest differs')
    return VerifiedCompletion(expected['as_of_date'], expected['data_through'], batch,
                              expected['archive_sha256'], hashlib.sha256(raw).hexdigest())


def resolve(received):
    """Missing/invalid evidence holds computation; it never invents complete days."""
    expected = binding(received)
    try:
        completion = _load(ROOT, expected)
    except FileNotFoundError:
        return {'status': 'unverified', 'reason': 'evidence_missing'}, None
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'unverified', 'reason': 'evidence_invalid'}, None
    return completion.metadata(), completion


def require_unchanged(received, decision_path):
    """Revalidate approval against the decision sealed before this batch's build."""
    decision, completion = resolve(received)
    try:
        sealed = _json(read_regular(decision_path, 16384))
    except (OSError, ValueError):
        raise ValueError('source completion decision missing or invalid') from None
    if completion is None or decision != sealed:
        raise ValueError('source completion evidence changed')
    return completion
