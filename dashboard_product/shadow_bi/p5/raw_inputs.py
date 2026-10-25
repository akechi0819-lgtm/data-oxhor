"""Source-only deterministic delivery contract. No network listener or token access."""
from __future__ import annotations
import argparse
from datetime import date, timedelta
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile

SCHEMA = 'shadow_raw_inputs.v1'
BATCH = re.compile(r'raw-[A-Za-z0-9_-]{1,80}')
FILES = {key: 'inputs/'+key+'.xlsx' for key in ('orders', 'cash', 'tencent')}
MAX_ARCHIVE = 128 * 1024**2
MAX_FILE = 64 * 1024**2
MAX_EXPANDED = 1024 * 1024**2
MAX_XML = 512 * 1024**2
MAX_ENTRIES = 4096


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''): h.update(chunk)
    return h.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.'+path.name+'.tmp')
    with tmp.open('w') as out:
        json.dump(value, out, ensure_ascii=False, sort_keys=True, indent=2)
        out.write('\n'); out.flush(); os.fsync(out.fileno())
    tmp.replace(path)


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def safe_name(name):
    p = PurePosixPath(name)
    return (isinstance(name, str) and bool(name) and '\\' not in name and '\x00' not in name
            and not p.is_absolute() and p.as_posix() == name
            and not any(x in {'', '.', '..'} for x in p.parts))


def validate_manifest(m, *, company, day, minimum_cutoff):
    from data_acquisition.jobs.bi_window_merge import rolling_start_date
    if set(m) != {'schema_version','batch_id','company_id','as_of_date','data_through','bi_window','refresh_months','files'}:
        raise ValueError('unexpected manifest fields')
    if m['schema_version'] != SCHEMA or not BATCH.fullmatch(m['batch_id']): raise ValueError('invalid identity')
    asof = date.fromisoformat(m['as_of_date'])
    if m['as_of_date'] != day or m['company_id'] != company: raise ValueError('wrong date or company')
    cutoff = (asof-timedelta(days=1)).isoformat()
    if m['data_through'] != cutoff or cutoff < minimum_cutoff: raise ValueError('stale cutoff')
    if m['bi_window'] != {'start': rolling_start_date(asof), 'end': day}: raise ValueError('BI window changed')
    if m['refresh_months'] != [day[:7]]: raise ValueError('Tencent refresh months changed')
    if set(m['files']) != set(FILES): raise ValueError('both source systems required')
    for key, path in FILES.items():
        spec = m['files'][key]
        if (set(spec) != {'path','sha256','size_bytes','filename'} or spec['path'] != path
                or not safe_name(spec['filename']) or '/' in spec['filename'] or len(spec['filename']) > 200
                or not spec['filename'].endswith('.xlsx')
                or not re.fullmatch('[0-9a-f]{64}', str(spec['sha256']))
                or type(spec['size_bytes']) is not int or not 0 < spec['size_bytes'] <= MAX_FILE):
            raise ValueError('invalid file declaration')
    return m


def validate_xlsx(path):
    """XLSX is itself a ZIP: bound expansion before any workbook parser runs."""
    total = 0
    with zipfile.ZipFile(path) as book:
        entries = book.infolist(); names = set()
        if len(entries) > MAX_ENTRIES: raise ValueError('too many workbook entries')
        for item in entries:
            name = item.filename.rstrip('/') if item.is_dir() else item.filename
            if not safe_name(name) or name in names or item.flag_bits & 1: raise ValueError('unsafe workbook entry')
            names.add(name)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError('workbook links forbidden')
            if item.file_size > MAX_XML: raise ValueError('workbook entry too large')
            total += item.file_size
            if total > MAX_XML: raise ValueError('workbook expansion exceeds limit')
        if not {'[Content_Types].xml','xl/workbook.xml'} <= names: raise ValueError('not an XLSX workbook')
        # Read streamed to check CRC and actual decompression without retaining XML.
        for item in entries:
            if item.is_dir(): continue
            with book.open(item) as stream:
                count = 0
                for chunk in iter(lambda: stream.read(1024**2), b''):
                    count += len(chunk)
                    if count > item.file_size: raise ValueError('invalid workbook size')
    return total


def unpack(archive, destination, *, company, day, minimum_cutoff):
    if archive.is_symlink() or not 0 < archive.stat().st_size <= MAX_ARCHIVE: raise ValueError('archive size invalid')
    # Plain TAR avoids another unbounded compression layer; only three XLSX payloads.
    with tarfile.open(archive, 'r:') as tf:
        members = []; total = 0; names = set()
        for item in tf:
            if (not item.isfile() or not safe_name(item.name) or item.name in names
                    or item.size > MAX_FILE or item.size < 0): raise ValueError('unsafe archive member')
            names.add(item.name); total += item.size; members.append(item)
            if len(members) > 4 or total > MAX_ARCHIVE: raise ValueError('archive expansion exceeds limit')
        if names != {'manifest.json', *FILES.values()}: raise ValueError('archive contents mismatch')
        item = tf.getmember('manifest.json')
        if item.size > 16384: raise ValueError('manifest too large')
        m = validate_manifest(_json(tf.extractfile(item).read()), company=company, day=day, minimum_cutoff=minimum_cutoff)
        expanded = 0
        for key, rel in FILES.items():
            item = tf.getmember(rel); spec = m['files'][key]
            if item.size != spec['size_bytes']: raise ValueError('file size mismatch')
            target = destination/rel; target.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(item) as source, target.open('xb') as out: shutil.copyfileobj(source,out,1024**2)
            if sha(target) != spec['sha256']: raise ValueError('file hash mismatch')
            expanded += validate_xlsx(target)
            if expanded > MAX_EXPANDED: raise ValueError('combined workbook expansion exceeds limit')
        write(destination/'manifest.json', m)
    return m


def pack(paths, archive, *, batch, company, day):
    from data_acquisition.jobs.bi_window_merge import rolling_start_date
    asof = date.fromisoformat(day)
    if set(paths) != set(FILES): raise ValueError('three workbooks required')
    m = {'schema_version': SCHEMA,'batch_id':batch,'company_id':company,'as_of_date':day,
         'data_through':(asof-timedelta(days=1)).isoformat(),
         'bi_window':{'start':rolling_start_date(asof),'end':day},'refresh_months':[day[:7]],
         'files':{key:{'path':FILES[key],'sha256':sha(p),'size_bytes':p.stat().st_size,'filename':p.name} for key,p in paths.items()}}
    validate_manifest(m, company=company, day=day, minimum_cutoff=m['data_through'])
    with archive.open('xb') as output, tarfile.open(fileobj=output, mode='w:') as tf:
        for name, payload in [('manifest.json',json.dumps(m,sort_keys=True,ensure_ascii=False).encode())]:
            info=tarfile.TarInfo(name); info.size=len(payload); info.mode=0o440; tf.addfile(info,io.BytesIO(payload))
        for key,path in paths.items():
            validate_xlsx(path)
            info=tarfile.TarInfo(FILES[key]); info.size=path.stat().st_size; info.mode=0o440
            with path.open('rb') as content: tf.addfile(info, content)
    return m


def stage(archive, root, *, company, day, minimum_cutoff):
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (root/'.receive.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        # Copy first; never validate caller-controlled files then consume different bytes.
        if archive.is_symlink() or not 0 < archive.stat().st_size <= MAX_ARCHIVE: raise ValueError('archive size invalid')
        if shutil.disk_usage(root).free < 1024**3 + 2*MAX_ARCHIVE: raise ValueError('insufficient disk reserve')
        with tempfile.TemporaryDirectory(prefix='.receive-',dir=root) as tmp:
            tmp=Path(tmp); frozen=tmp/'payload.tar'
            with archive.open('rb') as src, frozen.open('xb') as out:
                count=0
                for chunk in iter(lambda:src.read(1024**2),b''):
                    count+=len(chunk)
                    if count>MAX_ARCHIVE: raise ValueError('archive size invalid')
                    out.write(chunk)
            digest=sha(frozen)
            m=unpack(frozen,tmp,company=company,day=day,minimum_cutoff=minimum_cutoff)
            target=root/m['batch_id']
            if target.exists():
                receipt=_json((target/'received.json').read_bytes())
                if receipt['archive_sha256']!=digest: raise ValueError('batch already exists with different hash')
                if sha(target/'payload.tar')!=digest: raise ValueError('stored archive changed')
                for key,rel in FILES.items():
                    if sha(target/rel)!=m['files'][key]['sha256']: raise ValueError('stored input changed')
                return receipt
            receipt={'status':'received','batch_id':m['batch_id'],'archive_sha256':digest,'published':False}
            write(tmp/'received.json',receipt)
            # rename a complete immutable input directory; state is written separately.
            final=tmp/'sealed'; final.mkdir()
            for child in list(tmp.iterdir()):
                if child!=final: child.rename(final/child.name)
            for child in final.rglob('*'):
                child.chmod(0o550 if child.is_dir() else 0o440)
            final.rename(target); target.chmod(0o550)
            return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('pack'); a.add_argument('--orders',type=Path,required=True);a.add_argument('--cash',type=Path,required=True);a.add_argument('--tencent',type=Path,required=True);a.add_argument('--archive',type=Path,required=True);a.add_argument('--batch',required=True)
    b=sub.add_parser('stage');b.add_argument('--archive',type=Path,required=True);b.add_argument('--root',type=Path,required=True);b.add_argument('--minimum-cutoff',required=True)
    for parser in (a,b): parser.add_argument('--company',required=True);parser.add_argument('--day',required=True)
    args=vars(p.parse_args());command=args.pop('command')
    if command=='pack':
        paths={key:args.pop(key) for key in FILES}; result=pack(paths,**args)
    else: result=stage(**args)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
