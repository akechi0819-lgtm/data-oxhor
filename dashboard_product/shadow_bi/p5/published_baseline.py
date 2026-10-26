"""Seal only the accepted current Snapshot pair for the next server computation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from dashboard_product.shadow_bi.library import initialize,source_files,sha


def compact(workspace):
    cfg=json.loads((workspace/'Work/workspace.json').read_bytes())
    study=json.loads((workspace/'Work/StudyAbroad/current.json').read_bytes())
    for root,pointer,prefix in [
        (workspace/'Work/Runs',cfg['current_warehouse_path'],('Work','Runs')),
        (workspace/'Work/StudyAbroad/Runs',study['warehouse'],('Work','StudyAbroad','Runs'))]:
        parts=Path(pointer).parts
        if parts[:len(prefix)]!=prefix or '..' in parts:raise ValueError('Snapshot escaped fixed runs')
        keep=parts[len(prefix)]
        if not (root/keep).is_dir():raise ValueError('current Snapshot run missing')
        for p in root.iterdir():
            if p.name!=keep:
                if p.is_symlink() or p.is_file():p.unlink()
                else:shutil.rmtree(p)
    downloads=workspace/'Work/StudyAbroad/Downloads'
    if downloads.exists():shutil.rmtree(downloads)
    lineage=json.loads((workspace/study['source_lineage']).read_bytes())
    keep=set(lineage.get('normalized_history',{}).get('query_run_ids',{}).values())
    history=workspace/'Output/StudyAbroad/历史查询回执'
    if history.is_dir():
        for p in history.iterdir():
            if p.name not in keep:shutil.rmtree(p)


def prepare(base,workspace,release,day,group_gid):
    target=base/'raw-control/baselines'/release
    for name in ('Work','Input'):
        if any(p.is_symlink() for p in (workspace/name).rglob('*')):raise ValueError('baseline symlink rejected')
    original=source_files(workspace);size=sum(p.stat().st_size for p in original)
    if shutil.disk_usage(target.parent).free<size+1024**3:raise ValueError('insufficient baseline space')
    if target.exists():raise ValueError('baseline already exists')
    try:
        initialize(workspace,target);compact(target)
        expected={p.relative_to(workspace).as_posix():sha(p) for p in original}
        if any(expected.get(p.relative_to(target).as_posix())!=sha(p) for p in source_files(target)):
            raise ValueError('baseline copy changed')
        from data_acquisition.jobs.daily_warehouses import assert_daily_ready
        assert_daily_ready(target,day)
        guide=json.loads(subprocess.check_output([sys.executable,'-B','-m','interfaces.casebook','guide','--workspace',str(target)],text=True))
        if guide['next_step']!='analyze':raise ValueError('published baseline not ready')
        for p in [target,*target.rglob('*')]:
            if p.is_symlink():raise ValueError('baseline symlink rejected')
            os.chown(p,0,group_gid);p.chmod(0o750 if p.is_dir() else 0o640)
        return target
    except Exception:
        if target.exists():shutil.rmtree(target)
        raise


def set_policy(base,policy,group_gid):
    parent=base/'raw-control';fd,name=tempfile.mkstemp(prefix='.publish-policy-',dir=parent)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(policy,out,sort_keys=True);out.write('\n');os.fchown(out.fileno(),0,group_gid);os.fchmod(out.fileno(),0o640);out.flush();os.fsync(out.fileno())
        Path(name).replace(parent/'policy.json')
    finally:Path(name).unlink(missing_ok=True)
