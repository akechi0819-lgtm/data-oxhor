"""Authenticated fixed notification HTTP endpoint."""
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re

from flask import Flask, jsonify, request
from dashboard_product.shadow_bi.p5 import notification_contract as nc

app = Flask(__name__)
ROOT = Path(os.environ.get('SHADOW_RECEIVER_ROOT', '/var/lib/shadow-bi/receiver'))
TOKEN_SHA256 = os.environ.get('SHADOW_RECEIVER_TOKEN_SHA256', '')


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
