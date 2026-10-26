"""Opt-in raw route adapter, deliberately NOT registered by the production receiver.

Host owns authentication, trusted company/cutoff and fixed queue/producer roots.
No caller-supplied command, filesystem target, Snapshot ID, token or publish flag.
"""
from datetime import datetime
import fcntl
import hashlib
import json
import os
import pwd
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
from flask import jsonify,request
from dashboard_product.shadow_bi.p5.raw_inputs import BATCH,MAX_ARCHIVE,stage,write,CapacityError
from dashboard_product.shadow_bi.p5 import raw_status, publish_status
from dashboard_product.shadow_bi.p5.raw_consumer import lock_file, enqueue


def register(app, *, authorized, context, received_root, queue_root, status_root, status_owner_uid=None,
             publish_pending_root=None, publish_status_root=None, publication_context=None, publish_owner_uid=0):
    """Call only after approval to expand the existing receiver capability."""
    @app.post('/v1/raw-batches')
    def raw_receive():
        if not authorized():return jsonify(error='unauthorized'),401
        length=request.content_length
        if type(length) is not int or not 0<length<=MAX_ARCHIVE:return jsonify(error='invalid content length'),413
        received_root.mkdir(parents=True,exist_ok=True,mode=0o700)
        queue_root.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            # Context is a server callable, never parsed from request headers/body.
            company,minimum_cutoff=context()
            day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
            with lock_file(queue_root/'.queue.lock', nonblocking=True, shared=True):
                full=len([p for p in queue_root.iterdir() if BATCH.fullmatch(p.name)])>=4
                with tempfile.TemporaryDirectory(prefix='.upload-',dir=received_root) as tmp:
                    archive=Path(tmp)/'upload.tar'
                    with archive.open('xb') as out:
                        remaining=length
                        while remaining:
                            data=request.stream.read(min(1024**2,remaining))
                            if not data:raise ValueError('truncated upload')
                            out.write(data);remaining-=len(data)
                    result=stage(archive,received_root,company=company,day=day,minimum_cutoff=minimum_cutoff,allow_new=not full)
                batch=result['batch_id'];state=status_root/(batch+'.json')
                if publish_status_root is not None and (publish_status_root/(batch+'.json')).is_file():
                    return jsonify(publish_status.read(publish_status_root,batch,publish_owner_uid)),200
                if state.is_file():
                    value=raw_status.read(status_root,batch,owner_uid=status_owner_uid)
                    return jsonify(value),200
                marker=queue_root/batch
                if not marker.exists() and full:return jsonify(error='queue full'),429
                if not marker.exists():enqueue(queue_root,batch,result['archive_sha256'])
                return jsonify(batch_id=batch,status='queued',published=False),202
        except CapacityError:return jsonify(error='queue full'),429
        except BlockingIOError:return jsonify(error='receiver busy'),429
        except (OSError,ValueError,KeyError,TypeError):return jsonify(error='raw batch rejected'),400

    @app.get('/v1/raw-batches/<batch>')
    def raw_batch_status(batch):
        if not authorized():return jsonify(error='unauthorized'),401
        if not BATCH.fullmatch(batch):return jsonify(error='invalid batch'),400
        state=status_root/(batch+'.json')
        try:
            if publish_status_root is not None and (publish_status_root/(batch+'.json')).is_file():
                return jsonify(publish_status.read(publish_status_root,batch,publish_owner_uid)),200
            if state.is_file():
                value=raw_status.read(status_root,batch,owner_uid=status_owner_uid)
                return jsonify(value),200
            if (queue_root/batch).is_file():return jsonify(batch_id=batch,status='queued',published=False),200
            if (received_root/batch/'received.json').is_file():return jsonify(batch_id=batch,status='received',published=False),200
            return jsonify(error='not found'),404
        except (OSError,ValueError,KeyError):return jsonify(error='status unavailable'),503

    if publish_pending_root is not None:
        @app.post('/v1/raw-batches/<batch>/publish-prepared')
        def raw_publish_prepared(batch):
            if not authorized():return jsonify(error='unauthorized'),401
            if not BATCH.fullmatch(batch):return jsonify(error='invalid batch'),400
            if type(request.content_length) is not int or not 0<request.content_length<=1024:
                return jsonify(error='invalid request size'),413
            if request.get_json(silent=True)!={}:return jsonify(error='fixed empty object required'),400
            try:
                if (publish_status_root/(batch+'.json')).is_file():
                    return jsonify(publish_status.read(publish_status_root,batch,publish_owner_uid)),200
                value=raw_status.read(status_root,batch,owner_uid=status_owner_uid)
                if value['status']!='prepared':return jsonify(error='batch not prepared'),409
                with lock_file(publish_pending_root/'.queue.lock',nonblocking=True,shared=True):
                    marker=publish_pending_root/batch
                    if not marker.exists():
                        if len(list(publish_pending_root.glob('raw-*')))>=4:return jsonify(error='queue full'),429
                        raw_status.atomic_json(publish_pending_root,batch,{
                            'batch_id':batch,'as_of_date':datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),
                            'expected_current_sha256':publication_context()})
                return jsonify(batch_id=batch,status='publish_queued',published=False),202
            except FileNotFoundError:return jsonify(error='batch not prepared'),409
            except BlockingIOError:return jsonify(error='publisher busy'),429
            except (OSError,ValueError,KeyError,TypeError):return jsonify(error='publication unavailable'),503


RECEIVER_POLICY = Path('/var/lib/shadow-bi/raw-control/receiver-policy.json')

def deployment_context():
    meta=RECEIVER_POLICY.stat(follow_symlinks=False)
    if meta.st_uid!=0 or meta.st_mode & 0o022 or RECEIVER_POLICY.is_symlink():
        raise ValueError('untrusted receiver policy')
    policy=json.loads(raw_status.read_regular(RECEIVER_POLICY,4096))
    if set(policy)!={'schema_version','company_id','current_manifest'} or policy['schema_version']!='shadow_raw_receiver.v1':
        raise ValueError('invalid receiver policy')
    manifest=Path(policy['current_manifest'])
    if str(manifest)!='/var/lib/shadow-bi/current/library/library_manifest.json':
        raise ValueError('formal manifest path changed')
    current=json.loads(raw_status.read_regular(manifest,8*1024**2))
    return policy['company_id'],current['coverage']['data_through']

def configure(app,authorized):
    # Off by default. Deployment authorization must precede this root-owned flag.
    if os.environ.get('SHADOW_RECEIVER_RAW_ENABLED')!='1':
        return
    publication = {}
    if os.environ.get('SHADOW_RECEIVER_RAW_PUBLISH_ENABLED')=='1':
        publication = dict(publish_pending_root=Path('/var/lib/shadow-bi/raw-publish-pending'),
                           publish_status_root=Path('/var/lib/shadow-bi/raw-publish-status'),
                           publication_context=lambda:hashlib.sha256(raw_status.read_regular(Path('/var/lib/shadow-bi/current/library/library_manifest.json'),8*1024**2)).hexdigest())
    register(app,authorized=authorized,context=deployment_context,
             received_root=Path('/var/lib/shadow-bi/raw-inputs'),
             queue_root=Path('/var/lib/shadow-bi/raw-pending'),
             status_root=Path('/var/lib/shadow-bi/raw-status'),
             status_owner_uid=pwd.getpwnam('shadowraw').pw_uid,**publication)
