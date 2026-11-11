"""Root event worker: fixed enum/identity only, never shell or caller paths."""
from datetime import datetime
import fcntl
import hashlib
import re
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from zoneinfo import ZoneInfo
from dashboard_product.shadow_bi.p5 import notification_contract as nc

ROOT=Path('/var/lib/shadow-bi/receiver')
CONTROL=Path('/var/lib/shadow-bi/notify-control')
ENTRY='/usr/local/sbin/shadow-bi-notify'


def read_request(folder, name):
    directory=os.open(folder,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=2048:
                raise ValueError('invalid request file')
            return json.loads(stream.read(2049))
    finally:os.close(directory)


def write_result(control, identifier, result):
    folder=control/'results'
    fd,name=tempfile.mkstemp(prefix='.result-',dir=folder)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(result,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        # Trusted result bytes are never writable by the HTTP identity.
        import grp
        os.chown(name,0,grp.getgrnam('shadowbi').gr_gid)
        os.chmod(name,0o640)
        os.replace(name,folder/(identifier+'.json'))
    finally:
        if os.path.exists(name):os.unlink(name)


def executor_evidence(output=None, error=None):
    stdout = getattr(output,'stdout','') or ''
    stderr = getattr(output,'stderr','') or ''
    if isinstance(stdout,bytes):stdout=stdout.decode('utf-8',errors='replace')
    if isinstance(stderr,bytes):stderr=stderr.decode('utf-8',errors='replace')
    summary={}
    try:
        value=json.loads(stdout.strip().splitlines()[-1])
        for key in ('status','error_type','release_id','as_of_date','message_count','message_status_counts','deduplicated','network_send_attempted'):
            if key in value:summary[key]=value[key]
    except (ValueError,IndexError,TypeError):pass
    return {'schema_version':'notification_executor_evidence.v1',
            'returncode':getattr(output,'returncode',None),'exception_type':type(error).__name__ if error else None,
            'stdout_sha256':hashlib.sha256(stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(stderr.encode()).hexdigest(),
            'summary':summary,'stderr_error_classes':re.findall(r'\b[A-Za-z]+(?:Error|Exception)\b',stderr)[:10]}


def save_executor(control, identifier, attempt, evidence):
    folder=control/'executor-evidence';folder.mkdir(mode=0o700,exist_ok=True)
    path=folder/(identifier+'-'+str(attempt)+'.json')
    # Exact immutable attempt evidence; never replace a prior attempt record.
    with path.open('x') as stream:json.dump(evidence,stream,sort_keys=True)


def process(identifier, *, root=ROOT, control=CONTROL, execute=subprocess.run, now=None, save=write_result):
    root=root.resolve();control=control.resolve()
    if not nc.JOB.fullmatch(identifier):raise ValueError('invalid job id')
    pending=root/'notify-pending'/identifier
    path=control/'results'/(identifier+'.json')
    prior=json.loads(path.read_bytes()) if path.is_file() else None
    if prior and prior['status']=='running':
        # A crashed worker may already have reached DingTalk: never replay.
        save(control,identifier,{**prior,'status':'unknown','retryable':False})
        pending.unlink(missing_ok=True);return
    if prior and (prior['status'] in {'sent','dry_run','unknown'} or not prior.get('retryable') or prior.get('attempt',0)>=3):
        pending.unlink(missing_ok=True);return
    invoked=False
    result={'job_id':identifier,'attempt':(prior or {}).get('attempt',0)+1,
            'status':'blocked','retryable':False,'network_send_attempted':False,
            'updated_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
    try:
        raw=read_request(root/'notify-requests',identifier+'.json')
        if nc.job_id(raw)!=identifier:raise ValueError('request identity mismatch')
        if prior and raw.get('retry') is not True:
            pending.unlink(missing_ok=True);return
        release=(root.parent/'current').resolve(strict=True)
        if release.parent!=root.parent/'releases':raise ValueError('invalid current path')
        manifest=nc.current_manifest(release/'library')
        policy=json.loads((control/'policy.json').read_bytes())
        item=nc.validate(raw,release.name,manifest,policy,now)
        result.update(item,status='running')
        save(control,identifier,result)
        invoked=True
        try:
            output=execute([ENTRY,item['operation'],item['expected_release'],item['as_of_date']],
                           capture_output=True,text=True,timeout=660,check=False)
        except Exception as error:
            evidence=executor_evidence(error=error)
            save_executor(control,identifier,result['attempt'],evidence)
            result['executor_error_type']=evidence['exception_type']
            raise
        evidence=executor_evidence(output)
        save_executor(control,identifier,result['attempt'],evidence)
        result['executor_returncode']=output.returncode
        if evidence['summary'].get('error_type'):
            result['executor_error_type']=evidence['summary']['error_type']
        if output.returncode==75:
            # The fixed shell uses 75 only for the pre-execution entry lock.
            result.update(status='blocked',retryable=True,network_send_attempted=False,reason='notification executor busy; no send started')
            save(control,identifier,result);pending.unlink(missing_ok=True);return
        # Fixed entry prints one sanitized JSON summary; stderr remains private.
        report=json.loads(output.stdout.strip().splitlines()[-1])
        if report.get('release_id') != item['expected_release'] or report.get('as_of_date') != item['as_of_date']:
            raise ValueError('executor receipt identity mismatch')
        allowed={'status','release_id','batch_id','snapshots','as_of_date','data_through','message_count',
                 'message_status_counts','deduplicated','imported_state_ready','elapsed_seconds','network_send_attempted'}
        result.update({key:value for key,value in report.items() if key in allowed})
        if result['status'] not in {'dry_run','sent','partial','blocked'}:raise ValueError('invalid executor status')
        counts=report.get('message_status_counts',{})
        result['retryable']=(result['status']=='partial' and counts.get('pending',0)>0
                             and not counts.get('unknown') and not counts.get('sending'))
        if report.get('reason')=='notification_executor_busy' and report.get('network_send_attempted') is False:
            result.update(retryable=True,network_send_attempted=False,reason='notification executor busy; no send started')
        if output.returncode not in (0,2):raise ValueError('executor did not finish normally')
    except Exception:
        result['status']='unknown' if invoked and result.get('operation')=='send-scheduled' else 'blocked'
        result['retryable']=not (invoked and result.get('operation')=='send-scheduled')
        result['network_send_attempted']=bool(invoked and result.get('operation')=='send-scheduled')
        result['reason']='fixed executor failed or rejected; inspect private evidence, no automatic replay'
    save(control,identifier,result)
    pending.unlink(missing_ok=True)


def main():
    if os.getuid()!=0:raise SystemExit('root fixed worker required')
    with open('/run/shadow-bi-notify-dispatch.lock','a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Bounded draining; the .path unit reactivates while more markers exist.
        for marker in sorted((ROOT/'notify-pending').iterdir())[:8]:
            if nc.JOB.fullmatch(marker.name):process(marker.name)


if __name__=='__main__':main()
