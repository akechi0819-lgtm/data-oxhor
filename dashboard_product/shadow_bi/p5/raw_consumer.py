"""Fixed source-only queue consumer. No caller-selected command, path or publication."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from zoneinfo import ZoneInfo
from dashboard_product.shadow_bi.p5.raw_inputs import BATCH, MAX_ARCHIVE, _json, sha, stage, write
from dashboard_product.shadow_bi.p5 import raw_status

SCHEMA = 'shadow_raw_consumer.v1'
TERMINAL = frozenset({'coverage_unverified', 'prepared', 'failed', 'timed_out', 'interrupted', 'rejected'})
POLICY_FIELDS = frozenset({'schema_version', 'company_id', 'received_root', 'queue_root', 'work_root', 'status_root', 'baseline', 'current_manifest'})


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


@dataclass(frozen=True)
class Policy:
    company_id: str
    received_root: Path
    queue_root: Path
    work_root: Path
    status_root: Path
    baseline: Path
    current_manifest: Path

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, dict) or set(value) != POLICY_FIELDS or value['schema_version'] != SCHEMA:
            raise ValueError('invalid fixed consumer policy')
        if not isinstance(value['company_id'], str) or not re.fullmatch('[a-z][a-z0-9_-]{2,90}', value['company_id']):
            raise ValueError('invalid fixed company')
        paths = {}
        for key in POLICY_FIELDS - {'schema_version', 'company_id'}:
            p = Path(value[key])
            if not p.is_absolute() or '..' in p.parts or p.is_symlink():
                raise ValueError('unsafe policy path')
            paths[key] = p
        roots = [paths[k].resolve() for k in ('received_root', 'queue_root', 'work_root', 'status_root')]
        if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(roots) for b in roots[i+1:]):
            raise ValueError('private and public roots must be disjoint')
        for key in ('baseline', 'current_manifest'):
            if any(paths[key].resolve().is_relative_to(root) for root in roots):
                raise ValueError('trusted inputs cannot live in writable roots')
        return cls(company_id=value['company_id'], **paths)

    @classmethod
    def load(cls, path):
        parent=path.parent.stat(follow_symlinks=False)
        if path.parent.is_symlink() or parent.st_uid!=0 or parent.st_mode & 0o022:
            raise ValueError('policy directory must be root-controlled')
        raw = raw_status.read_regular(path, 16384)
        meta = path.stat(follow_symlinks=False)
        if meta.st_uid != 0 or meta.st_mode & 0o022:
            raise ValueError('policy must be root-owned and not group/world writable')
        return cls.from_mapping(_json(raw))

    def cutoff(self):
        value = _json(raw_status.read_regular(self.current_manifest, 8 * 1024**2))
        cutoff = value['coverage']['data_through']
        if date.fromisoformat(cutoff).isoformat() != cutoff:
            raise ValueError('invalid formal cutoff')
        return cutoff

    def verify_roots(self):
        for p in (self.received_root, self.queue_root, self.work_root, self.status_root, self.baseline):
            if p.is_symlink() or not p.is_dir():
                raise ValueError('provisioned directory required')
        for p in (self.work_root,self.status_root):
            meta=p.stat(follow_symlinks=False)
            if meta.st_uid!=os.geteuid() or meta.st_mode & 0o022:
                raise ValueError('worker-owned roots required')
        if self.work_root.stat().st_mode & 0o077:
            raise ValueError('private work root permissions too broad')
        company = _json(raw_status.read_regular(self.baseline/'Work/workspace.json', 65536))['company_id']
        if company != self.company_id:
            raise ValueError('baseline company differs')


@contextmanager
def lock_file(path, nonblocking=False, shared=False):
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660 if shared else 0o600)
        if shared:
            os.fchmod(fd, 0o660)
    except FileExistsError:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or (shared and (meta.st_mode & 0o007 or meta.st_mode & 0o060 != 0o060)):
            raise ValueError('lock permissions invalid')
        fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        yield
    finally:
        os.close(fd)


def enqueue(root, batch, digest):
    if not BATCH.fullmatch(batch) or not re.fullmatch('[0-9a-f]{64}', str(digest)):
        raise ValueError('invalid queue identity')
    raw_status.atomic_json(root, batch, {'batch_id': batch, 'archive_sha256': digest})


def marker(path):
    raw = raw_status.read_regular(path, 2048)
    value = _json(raw)
    if (not isinstance(value, dict) or set(value) != {'batch_id', 'archive_sha256'}
            or not BATCH.fullmatch(path.name) or value['batch_id'] != path.name
            or not re.fullmatch('[0-9a-f]{64}', str(value['archive_sha256']))):
        raise ValueError('invalid queue identity')
    return value, hashlib.sha256(raw).hexdigest()


def remove_marker(policy, name, digest):
    # Cooperative receiver lock plus inode-independent byte identity: never
    # remove a replacement request with other bytes after a long computation.
    with lock_file(policy.queue_root/'.queue.lock', shared=True):
        path = policy.queue_root/name
        try:
            raw = raw_status.read_regular(path, 2048)
        except FileNotFoundError:
            return
        if hashlib.sha256(raw).hexdigest() == digest:
            path.unlink()


def audit(policy, name, reason):
    folder = policy.work_root/'rejected'; folder.mkdir(mode=0o700, exist_ok=True)
    identifier = hashlib.sha256(name.encode()).hexdigest()
    write(folder/(identifier+'.json'), {'error_code': reason, 'entry_name_sha256': identifier})


def freeze(policy, batch, digest, day):
    # Anchor each untrusted directory/file with O_NOFOLLOW. Never hand a
    # receiver-owned path to the computation worker.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(policy.received_root, flags)
    batch_fd = archive_fd = None
    try:
        batch_fd = os.open(batch, flags, dir_fd=root_fd)
        archive_fd = os.open('payload.tar', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=batch_fd)
        meta = os.fstat(archive_fd)
        if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= MAX_ARCHIVE:
            raise ValueError('archive must be bounded regular file')
        temporary = policy.work_root/'incoming'; temporary.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='freeze-', dir=temporary) as tmp:
            copy = Path(tmp)/'payload.tar'
            with os.fdopen(archive_fd, 'rb', closefd=False) as source, copy.open('xb') as output:
                count = 0
                while chunk := source.read(1024**2):
                    count += len(chunk)
                    if count > MAX_ARCHIVE:
                        raise ValueError('archive grew beyond limit')
                    output.write(chunk)
                output.flush(); os.fsync(output.fileno())
            if sha(copy) != digest:
                raise ValueError('queued archive hash differs')
            result = stage(copy, policy.work_root/'inputs', company=policy.company_id,
                           day=day, minimum_cutoff=policy.cutoff())
            if result['batch_id'] != batch or result['archive_sha256'] != digest:
                raise ValueError('archive batch differs from marker')
        return policy.work_root/'inputs'/batch
    finally:
        for fd in (archive_fd, batch_fd, root_fd):
            if fd is not None:
                os.close(fd)


def validate_source_structure(received):
    import openpyxl
    expected = {'orders':('工单明细导出用表',{'ID','分配时间'}),
                'cash':('现金明细表',{'业务日期','现金收入','报入现金收入'})}
    for key,(title,columns) in expected.items():
        book=openpyxl.load_workbook(received/'inputs'/(key+'.xlsx'),read_only=True,data_only=True)
        try:
            if not book.sheetnames or book.sheetnames[0]!=title:
                raise ValueError('BI source sheet differs from fixed Bridge')
            first=next(book[title].iter_rows(max_row=1,values_only=True),())
            if not columns <= {str(v).strip() for v in first if v is not None}:
                raise ValueError('BI required columns missing')
        finally:
            book.close()
    from workspace_modeling.operations.study_abroad_source import _load_workbook_read_only,_resolve_sheet_name
    book=_load_workbook_read_only(received/'inputs/tencent.xlsx')
    try:
        for key in ('resources','contracts','languages'):_resolve_sheet_name(book,key)
    finally:
        book.close()


def policy_identity(policy):
    values=[policy.company_id,str(policy.baseline),sha(policy.baseline/'Work/workspace.json'),
            sha(policy.baseline/'Work/StudyAbroad/current.json')]
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def compute(policy, received, day):
    validate_source_structure(received)
    from dashboard_product.shadow_bi.p5.raw_compute import run
    return run(received=received, baseline=policy.baseline, root=policy.work_root/'runs',
               day=day, company=policy.company_id, minimum_cutoff=policy.cutoff())


def consume_one(policy, name, *, processor=compute, day=None, after_compute=None):
    day = day or today()
    request, request_digest = marker(policy.queue_root/name)
    jobs = policy.work_root/'jobs'; jobs.mkdir(mode=0o700, exist_ok=True)
    job_path = jobs/(name+'.json')
    if job_path.exists():
        job = _json(raw_status.read_regular(job_path, 65536))
        if job['archive_sha256'] != request['archive_sha256']:
            audit(policy, name, 'batch_conflict')
            remove_marker(policy, name, request_digest)
            return 'rejected'
        if job['status'] in TERMINAL:
            raw_status.publish(policy.status_root, name, job['status'], job.get('error_code'))
            remove_marker(policy, name, request_digest)
            return job['status']
        if job['day'] != day or job.get('policy_identity')!=policy_identity(policy):
            job.update(status='rejected', error_code='input_rejected')
            write(job_path, job); raw_status.publish(policy.status_root, name, 'rejected', 'input_rejected')
            remove_marker(policy, name, request_digest)
            return 'rejected'
    else:
        job = {'schema_version': SCHEMA, **request, 'day': day, 'status': 'claimed', 'policy_identity':policy_identity(policy)}
        write(job_path, job)
    try:
        received = freeze(policy, name, request['archive_sha256'], day)
    except (OSError, ValueError, KeyError, TypeError):
        job.update(status='rejected', error_code='input_rejected')
        write(job_path, job); raw_status.publish(policy.status_root, name, 'rejected', 'input_rejected')
        remove_marker(policy, name, request_digest)
        return 'rejected'
    job['status'] = 'running'; write(job_path, job)
    raw_status.publish(policy.status_root, name, 'running')
    try:
        result = processor(policy, received, day)
        if after_compute:
            after_compute()  # Test crash boundary; CLI never supplies a hook.
        status = result['status']
        if status not in TERMINAL - {'rejected'} or result.get('published') is not False:
            raise ValueError('invalid compute outcome')
        job.update(status=status)
    except BlockingIOError:
        return 'busy'  # Existing child still holds producer lock. No second build.
    except Exception:
        job.update(status='failed', error_code='compute_failed')
    write(job_path, job)
    raw_status.publish(policy.status_root, name, job['status'], job.get('error_code'))
    remove_marker(policy, name, request_digest)
    return job['status']


def run_once(policy, *, processor=compute, day=None, after_compute=None):
    policy.verify_roots()
    try:
        with lock_file(policy.work_root/'.consumer.lock', nonblocking=True):
            # Recover accepted private claims even if a receiver marker vanished.
            jobs = policy.work_root/'jobs'
            if jobs.exists():
                for p in jobs.iterdir():
                    if p.is_symlink() or not p.is_file() or not p.name.endswith('.json'):
                        raise ValueError('invalid private journal')
                    job = _json(raw_status.read_regular(p, 65536))
                    name = job['batch_id']
                    if not BATCH.fullmatch(name) or p.name != name+'.json':
                        raise ValueError('invalid private job identity')
                    if job['status'] in TERMINAL:
                        raw_status.publish(policy.status_root, name, job['status'], job.get('error_code'))
                    elif not (policy.queue_root/name).exists():
                        # Recreate only a minimal queue marker from the worker-owned journal.
                        with lock_file(policy.queue_root/'.queue.lock', shared=True):
                            if not (policy.queue_root/name).exists():
                                enqueue(policy.queue_root, name, job['archive_sha256'])
            entries = []
            for entry in policy.queue_root.iterdir():
                if entry.name.startswith('.'):
                    continue
                entries.append(entry)
                if len(entries) > 64:
                    raise ValueError('queue inventory exceeds limit')
            results = {}
            for entry in sorted(entries)[:4]:
                original=entry.lstat()
                try:
                    marker(entry)
                except (OSError, ValueError, KeyError, TypeError):
                    audit(policy, entry.name, 'invalid_queue_item')
                    # unlink never follows a symlink; directories are left for operator review.
                    try:
                        current=entry.lstat()
                        if (current.st_dev,current.st_ino)==(original.st_dev,original.st_ino):
                            if stat.S_ISDIR(current.st_mode):
                                # Same-parent rename needs no write access inside a foreign-owned directory.
                                # It also stays within the queue's systemd bind mount. Never traverse contents.
                                target=policy.queue_root/('.rejected-directory-'+hashlib.sha256(entry.name.encode()).hexdigest()+'-'+str(time.time_ns()))
                                entry.rename(target)
                            else:entry.unlink(missing_ok=True)
                    except FileNotFoundError:pass
                    results[hashlib.sha256(entry.name.encode()).hexdigest()] = 'rejected'
                    continue
                outcome = consume_one(policy, entry.name, processor=processor, day=day,
                                      after_compute=after_compute)
                results[entry.name] = outcome
                if outcome == 'busy':
                    return {'status': 'busy', 'batches': results, 'published': False}
                # One expensive batch per service lifetime; the path unit retriggers
                # remaining markers with a fresh resource/deadline budget.
                break
            return {'status': 'drained', 'batches': results, 'published': False}
    except BlockingIOError:
        return {'status': 'busy', 'batches': {}, 'published': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, default=Path('/var/lib/shadow-bi/raw-control/policy.json'))
    args = parser.parse_args()
    result = run_once(Policy.load(args.policy))
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(75 if result['status'] == 'busy' else 0)

if __name__ == '__main__':
    main()
