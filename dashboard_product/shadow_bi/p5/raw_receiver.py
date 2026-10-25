"""Opt-in raw route adapter, deliberately NOT registered by the production receiver.

Host owns authentication, trusted company/cutoff and fixed queue/producer roots.
No caller-supplied command, filesystem target, Snapshot ID, token or publish flag.
"""
from datetime import datetime
import fcntl
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
from flask import jsonify,request
from dashboard_product.shadow_bi.p5.raw_inputs import BATCH,MAX_ARCHIVE,stage,write


def register(app, *, authorized, context, received_root, queue_root, compute_root):
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
            with (queue_root/'.queue.lock').open('a+b') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                if len([p for p in queue_root.iterdir() if BATCH.fullmatch(p.name)])>=4:return jsonify(error='queue full'),429
                with tempfile.TemporaryDirectory(prefix='.upload-',dir=received_root) as tmp:
                    archive=Path(tmp)/'upload.tar'
                    with archive.open('xb') as out:
                        remaining=length
                        while remaining:
                            data=request.stream.read(min(1024**2,remaining))
                            if not data:raise ValueError('truncated upload')
                            out.write(data);remaining-=len(data)
                    result=stage(archive,received_root,company=company,day=day,minimum_cutoff=minimum_cutoff)
                batch=result['batch_id'];state=compute_root/batch/'state.json'
                if state.is_file():
                    status=json.loads(state.read_bytes())['status']
                    return jsonify(batch_id=batch,status=status,published=False),200
                marker=queue_root/batch
                if not marker.exists():write(marker,{'batch_id':batch,'archive_sha256':result['archive_sha256']})
                return jsonify(batch_id=batch,status='queued',published=False),202
        except BlockingIOError:return jsonify(error='receiver busy'),429
        except (OSError,ValueError,KeyError,TypeError):return jsonify(error='raw batch rejected'),400

    @app.get('/v1/raw-batches/<batch>')
    def raw_status(batch):
        if not authorized():return jsonify(error='unauthorized'),401
        if not BATCH.fullmatch(batch):return jsonify(error='invalid batch'),400
        state=compute_root/batch/'state.json'
        try:
            if state.is_file():
                value=json.loads(state.read_bytes())
                return jsonify(batch_id=batch,status=value['status'],published=False),200
            if (queue_root/batch).is_file():return jsonify(batch_id=batch,status='queued',published=False),200
            if (received_root/batch/'received.json').is_file():return jsonify(batch_id=batch,status='received',published=False),200
            return jsonify(error='not found'),404
        except (OSError,ValueError,KeyError):return jsonify(error='status unavailable'),503
