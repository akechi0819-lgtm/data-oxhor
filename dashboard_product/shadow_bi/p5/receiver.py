import hashlib
import hmac
import json
import os
import re
import fcntl
import shutil
import tarfile
import tempfile
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, request
from dashboard_product.shadow_bi.p5 import notification_contract as nc

app = Flask(__name__)
ROOT = Path(os.environ.get('SHADOW_RECEIVER_ROOT', '/var/lib/shadow-bi/receiver'))
MAX_BYTES = int(os.environ.get('SHADOW_RECEIVER_MAX_BYTES', str(512 * 1024 * 1024)))
EXPANDED_MAX_BYTES = int(os.environ.get('SHADOW_RECEIVER_EXPANDED_MAX_BYTES', str(2 * 1024 * 1024 * 1024)))
MAX_MEMBER_BYTES = int(os.environ.get('SHADOW_RECEIVER_MAX_MEMBER_BYTES', str(256 * 1024 * 1024)))
MAX_FILES = int(os.environ.get('SHADOW_RECEIVER_MAX_FILES', '2048'))
TOKEN_SHA256 = os.environ.get('SHADOW_RECEIVER_TOKEN_SHA256', '')
RELEASE_RE = re.compile(r'^daily-[A-Za-z0-9_-]{1,96}$')
LOCK_PATH = ROOT / '.receiver.lock'


def _authorized():
    if not TOKEN_SHA256 or not re.fullmatch(r'[0-9a-f]{64}', TOKEN_SHA256):
        return False
    value = request.headers.get('Authorization', '')
    if not value.startswith('Bearer ') or value.count(' ') != 1:
        return False
    token = value[7:]
    if not token or len(token) > 256:
        return False
    candidate = hashlib.sha256(token.encode('utf-8')).hexdigest()
    return hmac.compare_digest(candidate, TOKEN_SHA256)


def _safe_members(tf):
    total = 0
    members = []
    names = set()
    for member in tf:
        name = Path(member.name)
        if member.name.startswith('/') or '..' in name.parts or name == Path('.'):
            raise ValueError('unsafe archive path')
        if member.name in names:
            raise ValueError('duplicate archive path')
        if not member.isfile() or member.issym() or member.islnk():
            raise ValueError('archive contains non-regular file')
        if member.size > MAX_MEMBER_BYTES:
            raise ValueError('archive member exceeds limit')
        total += member.size
        if total > EXPANDED_MAX_BYTES or len(members) + 1 > MAX_FILES:
            raise ValueError('archive exceeds limits')
        names.add(member.name)
        members.append(member)
    if 'library_manifest.json' not in {m.name for m in members}:
        raise ValueError('library_manifest.json required')
    return members


def validate_archive(path):
    with tarfile.open(path, 'r:gz') as tf:
        members = _safe_members(tf)
        manifest_member = tf.extractfile('library_manifest.json')
        manifest = json.load(manifest_member)
        if manifest.get('schema_version') != 'business_query_library.v1':
            raise ValueError('unsupported manifest schema')
        if not isinstance(manifest.get('batch_id'), str) or not manifest['batch_id']:
            raise ValueError('manifest batch_id required')
        coverage = manifest.get('coverage') or {}
        through = coverage.get('data_through')
        if not isinstance(through, str):
            raise ValueError('manifest cutoff required')
        incoming_date = date.fromisoformat(through)
        active_manifest = ROOT.parent / 'current' / 'library' / 'library_manifest.json'
        if active_manifest.is_file():
            current = json.loads(active_manifest.read_text())
            current_through = (current.get('coverage') or {}).get('data_through')
            if isinstance(current_through, str) and incoming_date < date.fromisoformat(current_through):
                raise ValueError('cutoff would move backwards')
        tables = manifest.get('tables')
        if not isinstance(tables, dict) or not tables:
            raise ValueError('manifest tables required')
        expected = {'library_manifest.json'}
        for spec in tables.values():
            data = spec.get('data') if isinstance(spec, dict) else None
            rel = data.get('path') if isinstance(data, dict) else None
            digest = data.get('sha256') if isinstance(data, dict) else None
            size = data.get('size_bytes') if isinstance(data, dict) else None
            rel_path = Path(rel) if isinstance(rel, str) else Path('.')
            if rel_path.is_absolute() or '..' in rel_path.parts or not rel_path.as_posix().startswith('tables/'):
                raise ValueError('manifest table path invalid')
            if not re.fullmatch(r'[0-9a-f]{64}', str(digest)) or not isinstance(size, int) or size < 0:
                raise ValueError('manifest table hash invalid')
            expected.add(rel_path.as_posix())
        actual = {member.name for member in members}
        if actual != expected:
            raise ValueError('archive does not exactly match manifest')
        for rel in sorted(expected - {'library_manifest.json'}):
            member = next(item for item in members if item.name == rel)
            stream = tf.extractfile(member)
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            spec = next(spec for spec in tables.values() if spec['data']['path'] == rel)
            if size != spec['data']['size_bytes'] or digest.hexdigest() != spec['data']['sha256']:
                raise ValueError('manifest file hash mismatch')
    return manifest


@app.get('/health')
def health():
    return jsonify({'status': 'ok', 'receiver': 'shadow-bi', 'auth': 'fail-closed'}), 200


@app.post('/v1/batches')
def receive():
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401
    if _sql_current_active():
        return jsonify({'error': 'legacy business upload retired for SQL current'}), 410
    release = request.headers.get('X-Shadow-BI-Release', '')
    if not RELEASE_RE.fullmatch(release):
        return jsonify({'error': 'invalid release'}), 400
    length = request.content_length
    if length is None or length <= 0 or length > MAX_BYTES:
        return jsonify({'error': 'invalid content length'}), 413
    ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    (ROOT / 'pending').mkdir(mode=0o750, exist_ok=True)
    with LOCK_PATH.open('a+') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        incoming = ROOT / release
        request_file = incoming / 'request.json'
        archive_file = incoming / 'tables.tar.gz'
        temp = Path(tempfile.mkdtemp(prefix='.incoming-', dir=str(ROOT)))
        temp_archive = temp / 'tables.tar.gz'
        try:
            with temp_archive.open('wb') as out:
                remaining = length
                digest_hash = hashlib.sha256()
                while remaining:
                    chunk = request.stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError('truncated request')
                    out.write(chunk)
                    digest_hash.update(chunk)
                    remaining -= len(chunk)
            digest = digest_hash.hexdigest()
            if incoming.exists():
                if not request_file.is_file() or not archive_file.is_file():
                    raise ValueError('release exists but is incomplete')
                old_digest = request_file.read_text().strip()
                if digest != old_digest:
                    return jsonify({'error': 'release already exists with different content'}), 409
                published = ((ROOT / 'last_published').is_file()
                             and (ROOT / 'last_published').read_text().strip() == release
                             and (ROOT / 'last_published_hash').is_file()
                             and (ROOT / 'last_published_hash').read_text().strip() == digest)
                if published:
                    return jsonify({'status': 'duplicate', 'release': release}), 200
                marker = ROOT / 'pending' / release
                marker_tmp = ROOT / 'pending' / f'.{release}.{os.getpid()}.tmp'
                marker_tmp.write_text(release + '\n')
                marker_tmp.replace(marker)
                if (ROOT / 'last_failed').is_file() and (ROOT / 'last_failed').read_text().strip().startswith(release + '\t'):
                    (ROOT / 'last_failed').unlink()
                return jsonify({'status': 'staged', 'release': release}), 202
            validate_archive(temp_archive)
            (temp / 'request.json').write_text(digest + '\n')
            os.chmod(temp / 'request.json', 0o640)
            os.chmod(temp_archive, 0o640)
            temp.rename(incoming)
            marker = ROOT / 'pending' / release
            marker_tmp = ROOT / 'pending' / f'.{release}.{os.getpid()}.tmp'
            marker_tmp.write_text(release + '\n')
            marker_tmp.replace(marker)
            if (ROOT / 'last_failed').is_file() and (ROOT / 'last_failed').read_text().strip().startswith(release + '\t'):
                (ROOT / 'last_failed').unlink()
            return jsonify({'status': 'staged', 'release': release}), 202
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            return jsonify({'error': 'invalid archive'}), 400
        finally:
            # Early duplicate/409 responses must not leave request-sized temp files.
            shutil.rmtree(temp, ignore_errors=True)
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _sql_current_active():
    root = ROOT.parent
    try:
        formal_root = root.resolve(strict=True)
        current = (root / 'current').resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if current.parent != formal_root / 'releases':
        return False
    return (current / 'library' / 'candidate.json').is_file()


@app.get('/v1/batches/<release>')
def status(release):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401
    if not RELEASE_RE.fullmatch(release):
        return jsonify({'error': 'invalid release'}), 400
    if (ROOT / 'last_published').is_file() and (ROOT / 'last_published').read_text().strip() == release:
        return jsonify({'status': 'published', 'release': release}), 200
    if ((ROOT / 'last_failed').is_file()
            and (ROOT / 'last_failed').read_text().strip().startswith(release + '\t')):
        return jsonify({'status': 'failed', 'release': release}), 502
    if (ROOT / release / 'tables.tar.gz').is_file():
        return jsonify({'status': 'staged', 'release': release}), 200
    return jsonify({'error': 'not found'}), 404


# Reuse this listener and bearer credential. No command/path/recipient inputs.
NOTIFY_CONTROL = Path('/var/lib/shadow-bi/notify-control')
NOTIFY_ENABLED = os.environ.get('SHADOW_RECEIVER_NOTIFY_ENABLED') == '1'


def _notify_context():
    if not NOTIFY_ENABLED:
        raise nc.Rejected('notification capability disabled', 503)
    current = (ROOT.parent/'current').resolve(strict=True)
    if current.parent != ROOT.parent.resolve()/'releases':
        raise nc.Rejected('formal current path invalid', 503)
    manifest = nc.current_manifest(current/'library')
    policy = json.loads((NOTIFY_CONTROL/'policy.json').read_bytes())
    return current.name, manifest, policy


def _notify_error(error):
    return jsonify({'error':str(error) if isinstance(error,nc.Rejected) else 'notification control unavailable'}), (error.status if isinstance(error,nc.Rejected) else 503)


@app.get('/v1/notifications/status')
def notification_status():
    if not _authorized():
        return jsonify({'error':'unauthorized'}),401
    try:
        release, manifest, policy = _notify_context()
        return jsonify({'status':'available','release_id':release,'as_of_date':manifest['as_of_date'],
            'data_through':manifest['coverage']['data_through'],'policy':policy,
            'operations':['preview','send-scheduled'],'timezone':'Asia/Shanghai','scheduled_hour':10}),200
    except (nc.Rejected,OSError,ValueError,KeyError) as error:
        return _notify_error(error)


@app.post('/v1/notifications/jobs')
def notification_enqueue():
    if not _authorized():
        return jsonify({'error':'unauthorized'}),401
    if request.content_length is None or not 0 < request.content_length <= 2048:
        return jsonify({'error':'invalid content length'}),413
    try:
        try:payload = json.loads(request.get_data())
        except ValueError:raise nc.Rejected('invalid JSON') from None
        release, manifest, policy = _notify_context()
        item = nc.validate(payload,release,manifest,policy)
        identifier = nc.job_id(item)
        ROOT.mkdir(parents=True,exist_ok=True)
        with (ROOT/'.notify.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            requests = ROOT/'notify-requests'; pending = ROOT/'notify-pending'
            for folder in (requests,pending):folder.mkdir(mode=0o750,exist_ok=True)
            marker = pending/identifier
            result_path = NOTIFY_CONTROL/'results'/(identifier+'.json')
            result = json.loads(result_path.read_bytes()) if result_path.is_file() else None
            if marker.exists() or (result and result['status'] in {'running','sent','dry_run','unknown'}):
                return jsonify({'job_id':identifier,'status':result['status'] if result else 'queued','deduplicated':True}),200
            if result and not (payload.get('retry') is True and result.get('retryable') is True and result.get('attempt',0)<3):
                return jsonify({'job_id':identifier,'status':result['status'],'retryable':result.get('retryable',False)}),409
            if len(list(pending.iterdir())) >= 8:
                return jsonify({'error':'notification queue full'}),429
            # Worker copies and independently validates these untrusted bytes.
            target=requests/(identifier+'.json')
            temp=requests/('.'+identifier+'.tmp')
            with temp.open('w') as out:json.dump({**item,'retry':payload.get('retry',False)},out)
            os.chmod(temp,0o640);temp.replace(target)
            with marker.open('x') as out:out.write(identifier+'\n')
            return jsonify({'job_id':identifier,'status':'queued','deduplicated':False}),202
    except (nc.Rejected,OSError,ValueError,KeyError,TypeError) as error:
        return _notify_error(error)


@app.get('/v1/notifications/jobs/<identifier>')
def notification_job(identifier):
    if not _authorized():
        return jsonify({'error':'unauthorized'}),401
    if not nc.JOB.fullmatch(identifier):return jsonify({'error':'invalid job id'}),400
    try:
        if not NOTIFY_ENABLED:raise nc.Rejected('notification capability disabled',503)
        path=NOTIFY_CONTROL/'results'/(identifier+'.json')
        if path.is_file():
            raw=path.read_bytes();value=json.loads(raw)
            if (NOTIFY_CONTROL/'reconciliations'/(identifier+'.json')).is_file():
                from monitoring_product.notification_job_reconcile import read_receipt
                value['delivery_reconciliation']=read_receipt(NOTIFY_CONTROL,identifier,raw)
            return jsonify(value),200
        if (ROOT/'notify-pending'/identifier).is_file():return jsonify({'job_id':identifier,'status':'queued'}),200
        return jsonify({'error':'not found'}),404
    except (OSError,ValueError,nc.Rejected) as error:return _notify_error(error)


# Fixed raw capability remains disabled unless explicitly deployed by the host.
from dashboard_product.shadow_bi.p5.raw_receiver import configure as configure_raw
configure_raw(app, _authorized)


if __name__ == '__main__':
    app.run('127.0.0.1', 18091)
