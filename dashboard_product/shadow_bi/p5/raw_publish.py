"""Fixed root publisher for an explicitly requested prepared raw batch. No arbitrary arguments."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import time
from zoneinfo import ZoneInfo
from dashboard_product.shadow_bi.p5.raw_inputs import BATCH, FILES, _json, sha, validate_manifest, write
from dashboard_product.shadow_bi.p5.raw_status import read_regular
from dashboard_product.shadow_bi.p5 import publish_status

BASE=Path('/var/lib/shadow-bi')
PUBLISH_LOCK=Path('/run/shadow-bi-receiver.lock')


@contextmanager
def publication_locks(base):
    # Reuse the existing publisher mutex, and serialize with the existing raw rebuild.
    with PUBLISH_LOCK.open('a+b') as publish:
        fcntl.flock(publish,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fd=os.open(base/'raw-compute/runs/.producer.lock',os.O_RDONLY|os.O_NOFOLLOW)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
        finally:os.close(fd)


def current(base):
    target=(base/'current').resolve(strict=True)
    if target.parent!=(base/'releases').resolve():raise ValueError('current escaped releases')
    return target,sha(target/'library/library_manifest.json')


def request(base,batch):
    if not BATCH.fullmatch(batch):raise ValueError('invalid fixed batch')
    path=base/'raw-publish-pending'/batch
    raw=read_regular(path,2048);value=_json(raw)
    if (set(value)!={'batch_id','as_of_date','expected_current_sha256'} or value['batch_id']!=batch
            or not isinstance(value['expected_current_sha256'],str) or len(value['expected_current_sha256'])!=64):
        raise ValueError('invalid fixed publication request')
    if value['as_of_date']!=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat():
        raise ValueError('today publication required')
    return value,hashlib.sha256(raw).hexdigest()


def digest_regular(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=limit:raise ValueError('invalid fixed input file')
        h=hashlib.sha256();count=0
        with os.fdopen(fd,'rb',closefd=False) as source:
            while chunk:=source.read(1024**2):
                h.update(chunk);count+=len(chunk)
                if count>limit:raise ValueError('input grew beyond bound')
        if count!=info.st_size:raise ValueError('input size changed')
        return h.hexdigest()
    finally:os.close(fd)


def prepared(base,batch,day):
    work=base/'raw-compute/runs'/batch;received=base/'raw-inputs'/batch
    state=_json(read_regular(work/'state.json',65536));receipt=_json(read_regular(work/'prepared.json',65536))
    if state['status']!='prepared' or state['published'] is not False or sha(work/'prepared.json')!=state['prepared_sha256']:
        raise ValueError('batch is not prepared')
    archive=digest_regular(received/'payload.tar',128*1024**2)
    if state['identity']['archive_sha256']!=archive or _json(read_regular(received/'received.json',65536))['archive_sha256']!=archive:
        raise ValueError('raw archive changed')
    company=_json(read_regular(base/'raw-control/receiver-policy.json',4096))['company_id']
    _,_=current(base)
    formal=_json(read_regular(base/'current/library/library_manifest.json',8*1024**2))
    raw=validate_manifest(_json(read_regular(received/'manifest.json',65536)),company=company,day=day,minimum_cutoff=formal['coverage']['data_through'])
    for key,rel in FILES.items():
        if digest_regular(received/rel,64*1024**2)!=raw['files'][key]['sha256']:raise ValueError('raw input changed')
    from dashboard_product.shadow_bi.p5.raw_compute import run_names
    suffix,_,business=run_names(day,archive)
    library=work/'workspace/Output/ShadowBI'/business/'library'
    if (work.is_symlink() or not library.resolve().is_relative_to(work.resolve())
            or Path(receipt['library']).resolve()!=library.resolve() or library.is_symlink() or receipt['batch_id']!=business):
        raise ValueError('prepared library binding differs')
    manifest=_json(read_regular(library/'library_manifest.json',8*1024**2))
    if (receipt['gates']['tables']!=39 or receipt['gates']['physical_counts_verified'] is not True
            or receipt['gates']['manifest_sha256']!=sha(library/'library_manifest.json')
            or len(manifest['tables'])!=39 or manifest['as_of_date']!=day
            or manifest['coverage']['data_through']!=raw['data_through']):raise ValueError('prepared gates differ')
    pair=_json(read_regular(work/'pair.json',65536))
    from data_acquisition.jobs.daily_warehouses import _canonical_sha256
    if (pair['status']!='passed' or pair['as_of_date']!=day
            or pair['sources']['bi']['value_sha256']!=_canonical_sha256({k:raw['files'][k]['sha256'] for k in ('orders','cash')})
            or pair['sources']['study_abroad']['value_sha256']!=raw['files']['tencent']['sha256']):raise ValueError('dual source binding differs')
    expected={'training':'snapshot_bi_operations_'+suffix,'abroad':'snapshot_study_abroad_'+suffix}
    if manifest['snapshots']!=expected:raise ValueError('snapshot pair differs')
    for key,snapshot in [('bi',expected['training']),('study',expected['abroad'])]:
        quality=_json(read_regular(work/('quality-'+key+'.json'),65536))
        if quality['status']!='passed' or quality['snapshot_id']!=snapshot or quality['errors'] or quality['result']['rows']:
            raise ValueError('snapshot quality requires review')
    return library,manifest,archive


def freeze(library,manifest,destination):
    total=sum(spec['data']['size_bytes'] for spec in manifest['tables'].values())
    if total>2*1024**3 or shutil.disk_usage(destination.parent).free<total+manifest['database']['size_bytes']+1024**3:
        raise ValueError('insufficient publication space')
    destination.mkdir(mode=0o700)
    root=os.open(library,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        tables=os.open('tables',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        try:
            (destination/'tables').mkdir(mode=0o700)
            names=set()
            for spec in manifest['tables'].values():
                data=spec['data'];rel=Path(data['path'])
                if (len(rel.parts)!=2 or rel.parts[0]!='tables' or rel.name in names
                        or rel.name in ('.','..') or not rel.name.endswith('.jsonl')
                        or type(data['size_bytes']) is not int or not 0<=data['size_bytes']<=512*1024**2):
                    raise ValueError('invalid sealed table path or size')
                names.add(rel.name)
                fd=os.open(rel.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=tables)
                try:
                    info=os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size!=data['size_bytes']:raise ValueError('table changed')
                    digest=hashlib.sha256();size=0
                    with os.fdopen(fd,'rb',closefd=False) as source,(destination/rel).open('xb') as out:
                        while chunk:=source.read(1024**2):
                            digest.update(chunk);out.write(chunk);size+=len(chunk)
                            if size>data['size_bytes']:raise ValueError('table grew')
                    if size!=data['size_bytes'] or digest.hexdigest()!=data['sha256']:raise ValueError('table digest differs')
                finally:os.close(fd)
        finally:os.close(tables)
    finally:os.close(root)
    write(destination/'library_manifest.json',manifest)


def seal_release(target):
    import grp
    group=grp.getgrnam('shadowbi').gr_gid
    for path in [target,*target.rglob('*')]:
        os.chown(path,0,group);path.chmod(0o750 if path.is_dir() else 0o640)


def activate(target):
    from dashboard_product.shadow_bi.p4.activate import activate as existing_activate
    existing_activate(target)


def verify_daily(output):
    # Existing native verification: 18 numbers, all three acquisition scopes.
    subprocess.run([__import__('sys').executable,'-B','-m','dashboard_product.shadow_bi.p5.verify_daily','--output',str(output)],check=True)


def live_reference(path):
    for entry in Path('/proc').glob('[0-9]*/fd/*'):
        try:target=os.readlink(entry)
        except OSError:continue
        if target==str(path) or target.startswith(str(path)+'/'):return True
    return False


def cleanup_old(base,old,target):
    if old==target or old.parent!=(base/'releases').resolve() or current(base)[0]!=target:return []
    # Known current consumer is restarted by activate before cleanup. Preserve active file readers.
    if live_reference(old):return []
    # Preserve static Nginx targets.
    for config in (Path('/etc/nginx/sites-available/shadow-bi'),Path('/etc/nginx/sites-enabled/shadow-bi')):
        if config.is_file() and str(old) in config.read_text():return []
    previous=base/'previous'
    if previous.is_symlink() and previous.resolve()==old:previous.unlink()
    # Never clear data inputs, historical warehouses, notification state or logs.
    removed=[]
    for path in (old,base/'incoming'/old.name):
        if path.exists() and not path.is_symlink():shutil.rmtree(path);removed.append(str(path))
    return removed


def discard_failed_products(base,target,incoming=None):
    actual=(base/'current').resolve()
    previous=base/'previous'
    if previous.is_symlink() and previous.resolve()==target and target!=actual:previous.unlink()
    for path in (target,incoming):
        if path is not None and path.exists() and not path.is_symlink() and path!=actual:shutil.rmtree(path)


def remove_marker(base,batch,expected=None):
    marker=base/'raw-publish-pending'/batch
    try:
        info=marker.lstat()
        if stat.S_ISDIR(info.st_mode):
            marker.rename(marker.with_name('.rejected-'+batch+'-'+str(time.time_ns())))
        elif expected is None or hashlib.sha256(read_regular(marker,2048)).hexdigest()==expected:
            marker.unlink()
    except (ValueError,OSError):
        if marker.is_symlink():marker.unlink()


def prepare_baseline(base,library,release,day):
    import grp
    from dashboard_product.shadow_bi.p5.published_baseline import prepare
    return prepare(base,library.parents[3],release,day,grp.getgrnam('shadowraw').gr_gid)


def set_baseline(base,path):
    import grp
    from dashboard_product.shadow_bi.p5.published_baseline import set_policy
    policy=_json(read_regular(base/'raw-control/policy.json',16384))
    policy['baseline']=str(path)
    set_policy(base,policy,grp.getgrnam('shadowraw').gr_gid)


def publish_one(base,batch):
    if not BATCH.fullmatch(batch):raise ValueError('invalid fixed batch')
    public=base/'raw-publish-status';private=base/'raw-publish';journal=private/(batch+'.json')
    if journal.exists():
        previous=_json(read_regular(journal,65536))
        if previous['status'] in ('published','publish_failed'):
            publish_status.publish(public,batch,previous['status'],previous.get('release'),previous.get('error_code'))
            remove_marker(base,batch)
            return previous
        # Restore the current that existed when this fixed operation began; never rebuild twice.
        old=base/'releases'/previous['old_release']
        if not publish_status.RELEASE.fullmatch(old.name) or not publish_status.RELEASE.fullmatch(previous['release']):raise ValueError('invalid release identity')
        actual=(base/'current').resolve()
        if actual==base/'releases'/previous['release']:
            activate(old)
        elif actual!=old:
            previous.update(status='publish_failed',published=False,error_code='formal_changed')
            write(journal,previous);publish_status.publish(public,batch,'publish_failed',previous.get('release'),'formal_changed')
            remove_marker(base,batch,previous['request_sha256']);return previous
        if previous.get('old_baseline'):set_baseline(base,previous['old_baseline'])
        discard_failed_products(base,base/'releases'/previous['release'],base/'incoming'/previous['release'])
        previous.update(status='publish_failed',published=False,error_code='interrupted')
        write(journal,previous)
        publish_status.publish(public,batch,'publish_failed',previous.get('release'),'interrupted')
        remove_marker(base,batch,previous['request_sha256'])
        return previous
    try:value,digest=request(base,batch)
    except (OSError,ValueError,KeyError,TypeError):
        value={'batch_id':batch,'status':'publish_failed','published':False,'error_code':'input_rejected'}
        write(journal,value);publish_status.publish(public,batch,'publish_failed',error_code='input_rejected')
        remove_marker(base,batch);return value
    old,old_sha=current(base)
    old_policy=_json(read_regular(base/'raw-control/policy.json',16384))
    baseline_changed=False
    owns_destinations=False
    incoming=target=next_baseline=None
    state={'old_baseline':old_policy['baseline'],'batch_id':batch,'status':'publishing','published':False,'old_release':old.name,'expected_current_sha256':old_sha,'request_sha256':digest}
    try:
        if value['expected_current_sha256']!=old_sha:
            state['error_code']='formal_changed';raise ValueError('formal current changed')
        state['error_code']='input_rejected'
        library,manifest,archive=prepared(base,batch,value['as_of_date'])
        state.pop('error_code')
        release='daily-raw-'+value['as_of_date'].replace('-','')+'_'+archive[:12]
        state.update(release=release,prepared_manifest_sha256=sha(library/'library_manifest.json'))
        write(journal,state);publish_status.publish(public,batch,'publishing',release)
        incoming=base/'incoming'/release;target=base/'releases'/release
        if incoming.exists() or target.exists():raise ValueError('publication destination already exists')
        owns_destinations=True
        freeze(library,manifest,incoming)
        from dashboard_product.shadow_bi.p4.rebuild import rebuild
        rebuild(incoming,target/'library')
        seal_release(target)
        next_baseline=prepare_baseline(base,library,release,value['as_of_date'])
        activate(target)
        verify_daily(private/(batch+'-native.json'))
        set_baseline(base,next_baseline);baseline_changed=True
        state['baseline']=str(next_baseline)
        # Commit success before any latest-only deletion. Failed verification still has old intact.
        state.update(status='published',published=True)
        write(journal,state)
    except Exception:
        # P4 itself restores on a failed activation; the post-activation check also restores.
        if (base/'current').resolve()!=old:
            activate(old)
        if baseline_changed:set_baseline(base,old_policy['baseline'])
        if next_baseline is not None and Path(next_baseline).exists():shutil.rmtree(next_baseline)
        state.update(status='publish_failed',published=False,error_code=state.get('error_code','publication_failed'))
        if owns_destinations:discard_failed_products(base,target,incoming)
    write(journal,state)
    publish_status.publish(public,batch,state['status'],state.get('release'),state.get('error_code'))
    if state['status']=='published':
        try:
            state['removed_old_products']=cleanup_old(base,old,target)
            old_baseline=Path(old_policy['baseline'])
            if (old_baseline.parent==(base/'raw-control/baselines').resolve() and old_baseline.name.startswith('daily-raw-')
                    and old_baseline!=next_baseline and old_baseline.is_dir() and not old_baseline.is_symlink()):
                shutil.rmtree(old_baseline);state['removed_old_baseline']=str(old_baseline)
            if old.exists() and old!=target:state['cleanup_pending']=True
        except OSError:state['cleanup_pending']=True
    write(journal,state)
    remove_marker(base,batch,digest)
    return state


def main():
    if os.geteuid()!=0:raise PermissionError('fixed publisher requires root')
    # SIGTERM must unwind activation to its existing failure restore path.
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(TimeoutError('publication stopped')))
    pending=BASE/'raw-publish-pending'
    try:
        with publication_locks(BASE):
            entries=sorted(p for p in pending.iterdir() if BATCH.fullmatch(p.name))
            if entries:
                result=publish_one(BASE,entries[0].name)
                print(json.dumps({k:result[k] for k in ('batch_id','status','published')}))
    except BlockingIOError:raise SystemExit(75)

if __name__=='__main__':main()
