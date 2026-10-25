"""Fixed server entry: preview by default; no scheduler or credential import."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo
from monitoring_product import release_notifications as n
from data_platform.business_library import load_library


def run(mode, *, warehouse=Path('/var/lib/shadow-bi'), home=Path('/var/lib/shadow-bi-notify'),
        env_file=Path('/etc/shadow-bi-notify.env'), asset_root=Path('/var/www/dashboard/notify'), now=None):
    now=now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is None:
        raise ValueError('timezone-aware server clock required')
    now=now.astimezone(ZoneInfo('Asia/Shanghai'))
    current=warehouse/'current'
    release=current.resolve(strict=True)
    manifest=json.loads((release/'library/library_manifest.json').read_bytes())
    state=home/'state'
    ready=False
    try:
        n.require_imported_state(state);ready=True
    except (ValueError,OSError,KeyError,json.JSONDecodeError):
        pass
    if mode=='status':
        return {'status':'ready' if ready else 'blocked','release_id':release.name,
                'batch_id':manifest['batch_id'],'as_of_date':manifest['as_of_date'],
                'data_through':manifest['coverage']['data_through'],'imported_state_ready':ready,
                'credential_file_exists':env_file.is_file(),'scheduler_installed':False}
    if mode not in {'preview','send-scheduled'}:
        raise ValueError('unsupported notification operation')
    sending=mode=='send-scheduled'
    if sending:
        # The authorized daily trigger is 10:00 Shanghai. No catch-up outside
        # that hour, temporary test sends, or earlier delivery is enabled here.
        if now.hour!=10:
            raise ValueError('scheduled sending only allowed in the Shanghai 10:00 hour')
        if manifest['as_of_date']!=now.date().isoformat():
            raise ValueError('scheduled sending requires today formal release')
        n.require_imported_state(state)
    if not home.is_dir():
        raise ValueError('provisioned notification home required')
    started=time.monotonic()
    with (home/'.run.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest,_,_=load_library(release/'library',manifest['batch_id'])
        rules=n.rule_binding()
        version=hashlib.sha256(n.canonical(rules)).hexdigest()[:16]
        bundle=home/'bundles'/(release.name+'-'+version)
        if not bundle.exists():
            n.build_bundle(library=release/'library',batch_id=manifest['batch_id'],release_id=release.name,output_dir=bundle)
        output=home/'runs'/(now.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
        result=n.deliver_bundle(bundle_path=bundle/'bundle.json',current_release=current,
                output_dir=output,state_dir=state,env_file=env_file if sending else None,
                asset_root=asset_root,dry_run=not sending)
    counts=Counter(row['status'] if 'status' in row else 'preview' for row in result['messages'])
    return {'status':result['status'],'release_id':release.name,'batch_id':manifest['batch_id'],
            'snapshots':manifest['snapshots'],'as_of_date':manifest['as_of_date'],
            'data_through':manifest['coverage']['data_through'],'message_count':len(result['messages']),
            'message_status_counts':dict(counts),'deduplicated':sum(bool(row.get('deduplicated')) for row in result['messages']),
            'imported_state_ready':ready,'output_dir':str(output),'bundle_dir':str(bundle),
            'elapsed_seconds':round(time.monotonic()-started,3),'network_send_attempted':sending}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['status','preview','send-scheduled'],nargs='?',default='preview')
    args=parser.parse_args()
    try:
        result=run(args.mode)
    except Exception as error:
        # Fixed messages only; do not serialize credential-bearing exceptions.
        result={'status':'blocked','error_type':type(error).__name__,
                'reason':'inspect private server job evidence; no automatic retry or state reset'}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status'] in {'ready','dry_run','sent'} else 2


if __name__=='__main__':
    raise SystemExit(main())
