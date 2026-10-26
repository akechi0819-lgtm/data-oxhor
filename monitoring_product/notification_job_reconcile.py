"""No-send reconciliation of an unknown control job against eight confirmed deliveries."""
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dashboard_product.shadow_bi.p5 import notification_contract as nc

MESSAGES={'prep.training':'offline_youth','high.training':'offline_high_school','high.abroad':'offline_high_school',
          'university.training':'offline_university','university.abroad':'offline_university','virtual.mixed':'online_private',
          'online.training':'online_platform','online.abroad':'online_platform'}


def reconcile(identifier,*,control=Path('/var/lib/shadow-bi/notify-control'),home=Path('/var/lib/shadow-bi-notify'),warehouse=Path('/var/lib/shadow-bi')):
    if not nc.JOB.fullmatch(identifier):raise ValueError('invalid job')
    original_path=control/'results'/(identifier+'.json');original=original_path.read_bytes();job=json.loads(original)
    if job['status']!='unknown' or job['operation']!='send-scheduled':raise ValueError('unknown send job required')
    release=job['expected_release']
    if not nc.RELEASE.fullmatch(release):raise ValueError('invalid release')
    target=warehouse/'releases'/release
    manifest_path=target/'library/library_manifest.json';manifest=json.loads(manifest_path.read_bytes())
    if (warehouse/'current').resolve()!=target.resolve() or manifest['as_of_date']!=job['as_of_date']:
        raise ValueError('formal identity changed')
    state_path=home/'state/shared_delivery_state.json'
    with (home/'state/shared_delivery.lock').open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        raw=state_path.read_bytes();state=json.loads(raw)
        if state['schema_version']!='management_shared_delivery_state.v1':raise ValueError('invalid delivery state')
        for mid,channel in MESSAGES.items():
            row=state['deliveries'][job['as_of_date']+'|'+channel+'|'+mid]
            if (row['status']!='sent' or row['run_id']!=manifest['batch_id']
                    or row['snapshot_id']!=manifest['snapshots']['training']
                    or row['data_through']!=manifest['coverage']['data_through']
                    or row['delivery']['status']!='sent' or row['delivery']['message_sha256']!=row['message_sha256']
                    or row['delivery']['asset_sha256']!=row['asset_sha256']):raise ValueError('delivery not confirmed for this source')
        receipt={'schema_version':'notification_job_reconciliation.v1','job_id':identifier,
                 'original_status':'unknown','original_result_sha256':hashlib.sha256(original).hexdigest(),
                 'delivery_status':'sent','message_count':8,'message_status_counts':{'sent':8},
                 'release_id':release,'as_of_date':job['as_of_date'],'batch_id':manifest['batch_id'],
                 'delivery_state_sha256':hashlib.sha256(raw).hexdigest(),'no_send_performed':True,
                 'reconciled_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
        if original_path.read_bytes()!=original or state_path.read_bytes()!=raw:raise ValueError('audit input changed')
    return receipt


def store(control,receipt):
    directory=control/'reconciliations';directory.mkdir(mode=0o750,exist_ok=True)
    import grp
    group=grp.getgrnam('shadowbi').gr_gid;os.chown(directory,0,group);directory.chmod(0o750)
    path=directory/(receipt['job_id']+'.json')
    if path.exists():
        prior=json.loads(path.read_bytes())
        if any(prior[k]!=receipt[k] for k in ('original_result_sha256','delivery_state_sha256','release_id','delivery_status')):
            raise ValueError('reconciliation identity changed')
        return prior
    with path.open('x') as stream:
        json.dump(receipt,stream,sort_keys=True);stream.write('\n');os.fchown(stream.fileno(),0,group);os.fchmod(stream.fileno(),0o640);stream.flush();os.fsync(stream.fileno())
    return receipt


def read_receipt(control,identifier,original,owner_uid=0):
    directory=control/'reconciliations';path=directory/(identifier+'.json')
    for p in (directory,path):
        meta=p.stat(follow_symlinks=False)
        if p.is_symlink() or meta.st_uid!=owner_uid or meta.st_mode & 0o022:
            raise ValueError('untrusted reconciliation receipt')
    from dashboard_product.shadow_bi.p5.raw_status import read_regular
    value=json.loads(read_regular(path,8192))
    if (not isinstance(value,dict) or value.get('schema_version')!='notification_job_reconciliation.v1'
            or value.get('job_id')!=identifier or value.get('original_status')!='unknown'
            or value.get('original_result_sha256')!=hashlib.sha256(original).hexdigest()
            or value.get('delivery_status')!='sent' or value.get('message_count')!=8
            or value.get('message_status_counts')!={'sent':8} or value.get('no_send_performed') is not True):
        raise ValueError('reconciliation identity differs')
    return value


def main():
    import argparse
    if os.geteuid()!=0:raise PermissionError('root reconciliation required')
    parser=argparse.ArgumentParser();parser.add_argument('job_id');args=parser.parse_args()
    value=store(Path('/var/lib/shadow-bi/notify-control'),reconcile(args.job_id))
    print(json.dumps(value))

if __name__=='__main__':main()
