"""Small root-owned publication status; input compute status remains worker-owned."""
import re
from dashboard_product.shadow_bi.p5.raw_inputs import BATCH, _json
from dashboard_product.shadow_bi.p5.raw_status import atomic_json, read_regular

STATES={'publish_queued','publishing','published','publish_failed'}
ERRORS={'input_rejected','formal_changed','publication_failed','interrupted'}
RELEASE=re.compile(r'daily-[A-Za-z0-9_-]{1,96}')


def validate(value,batch):
    required={'schema_version','batch_id','status','published'}
    if (not isinstance(value,dict) or not required<=set(value) or set(value)-required-{'release','error_code'}
            or value['schema_version']!='shadow_raw_publish_status.v1' or not BATCH.fullmatch(batch)
            or value['batch_id']!=batch or value['status'] not in STATES
            or value['published'] is not (value['status']=='published')):
        raise ValueError('invalid fixed publication status')
    if 'release' in value and not RELEASE.fullmatch(value['release']):raise ValueError('invalid release')
    if 'error_code' in value and value['error_code'] not in ERRORS:raise ValueError('invalid publication error')
    return value


def read(root,batch,owner_uid=0):
    meta=root.stat(follow_symlinks=False)
    if root.is_symlink() or meta.st_uid!=owner_uid or meta.st_mode & 0o022:raise ValueError('untrusted publication status')
    path=root/(batch+'.json');info=path.stat(follow_symlinks=False)
    if info.st_uid!=owner_uid or info.st_mode & 0o022:raise ValueError('untrusted publication projection')
    return validate(_json(read_regular(path,2048)),batch)


def publish(root,batch,status,release=None,error_code=None):
    value={'schema_version':'shadow_raw_publish_status.v1','batch_id':batch,'status':status,'published':status=='published'}
    if release:value['release']=release
    if error_code:value['error_code']=error_code
    validate(value,batch);atomic_json(root,batch+'.json',value)
    return value
