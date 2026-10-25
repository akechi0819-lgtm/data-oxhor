"""Root pre-step: project ONLY formal cutoff metadata for the unprivileged worker.

No queue arguments, shell, secret configuration, publication or notification.
"""
from datetime import date
import grp
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from dashboard_product.shadow_bi.p5.raw_status import read_regular
from dashboard_product.shadow_bi.p5.raw_inputs import _json

BASE = Path('/var/lib/shadow-bi')


def refresh(base: Path, group_gid: int):
    current = (base/'current').resolve(strict=True)
    if current.parent != (base/'releases').resolve(strict=True):
        raise ValueError('formal current escaped releases')
    raw = read_regular(current/'library/library_manifest.json', 8*1024**2)
    manifest = _json(raw)
    cutoff = manifest['coverage']['data_through']
    if date.fromisoformat(cutoff).isoformat() != cutoff:
        raise ValueError('invalid formal cutoff')
    value = {'schema_version':'shadow_raw_context.v1', 'coverage':{'data_through':cutoff},
             'formal_manifest_sha256':hashlib.sha256(raw).hexdigest()}
    folder = base/'raw-control'
    if folder.is_symlink():
        raise ValueError('unsafe context directory')
    directory=os.open(folder,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    name='.formal-context-'+secrets.token_hex(8)
    try:
        info=os.fstat(directory)
        if info.st_uid!=0 or info.st_mode & 0o022:
            raise ValueError('context directory must be root-controlled')
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o640,dir_fd=directory)
        with os.fdopen(fd,'w') as out:
            json.dump(value,out,sort_keys=True);out.write('\n')
            os.fchown(out.fileno(),0,group_gid);os.fchmod(out.fileno(),0o640)
            out.flush();os.fsync(out.fileno())
        os.replace(name,'formal-context.json',src_dir_fd=directory,dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:os.unlink(name,dir_fd=directory)
        except FileNotFoundError:pass
        os.close(directory)
    return value


def main():
    if os.geteuid()!=0:
        raise PermissionError('fixed context pre-step requires root')
    refresh(BASE,grp.getgrnam('shadowraw').gr_gid)
    print('{"status":"context_ready"}')

if __name__=='__main__':
    main()
