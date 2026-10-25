#!/usr/bin/env bash
set -euo pipefail
case "$-" in *x*) echo "refuse to run with xtrace" >&2; exit 2 ;; esac
set +x

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
RELEASE_DIR="${RELEASE_DIR:-}"
MANIFEST_SHA="${MANIFEST_SHA:-}"
ENV_FILE="${ENV_FILE:-}"
REMOTE_RELEASE_DIR="${REMOTE_RELEASE_DIR:-}"
REMOTE_NGINX_CONF="${REMOTE_NGINX_CONF:-}"
REMOTE_CURRENT_LINK="/var/www/dashboard/current"
REMOTE_STAGING_DIR="${REMOTE_STAGING_DIR:-/tmp}"

usage() {
  echo "usage: RELEASE_DIR=/local/package MANIFEST_SHA=<sha256> ENV_FILE=/path/to/.env.server $0 [--dry-run]" >&2
}
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--dry-run" ) ]]; then usage; exit 2; fi
dry_run=false
if [[ $# -eq 1 ]]; then dry_run=true; fi
for name in RELEASE_DIR MANIFEST_SHA ENV_FILE; do
  test -n "${!name}" || { usage; echo "$name is required" >&2; exit 2; }
done
NGINX_CONFIG="${SCRIPT_DIR}/nginx-management-dashboard.conf"
test -s "$NGINX_CONFIG" || { echo "missing Nginx configuration: $NGINX_CONFIG" >&2; exit 2; }

# This validation is local and credential-free. It runs before the dry-run
# return and does not import the SSH/pexpect transport.
validated="$(python3 - "$RELEASE_DIR" "$MANIFEST_SHA" "$NGINX_CONFIG" <<'PY'
import hashlib, json, re, sys
from datetime import date
from pathlib import Path

release=Path(sys.argv[1])
expected_manifest_sha=sys.argv[2]
config_path=Path(sys.argv[3])
allow={'index.html','prep_high.html','university.html','online.html','styles.css','app.js','boards.css','boards.js','data.json','university.data.json','prep_high.data.json',*(f'prep_high.{i}.data.json' for i in range(1,8))}
if not re.fullmatch(r'[0-9a-f]{64}', expected_manifest_sha): raise ValueError('MANIFEST_SHA must be lowercase SHA-256')
if release.is_symlink() or not release.is_dir(): raise ValueError('RELEASE_DIR must be a local, non-symlink package directory')
manifest_path=release/'manifest.json'
if manifest_path.is_symlink() or not manifest_path.is_file(): raise ValueError('release manifest is missing or symlinked')
manifest_bytes=manifest_path.read_bytes()
manifest_sha=hashlib.sha256(manifest_bytes).hexdigest()
if manifest_sha != expected_manifest_sha: raise ValueError('manifest SHA-256 does not match MANIFEST_SHA')
manifest=json.loads(manifest_bytes.decode('utf-8'))
run_id=manifest.get('run_id')
snapshot_id=manifest.get('snapshot_id')
data_through=manifest.get('data_through')
if manifest.get('schema_version')!='management_dashboard_release.v1': raise ValueError('unsupported release manifest')
if not isinstance(run_id,str) or not re.fullmatch(r'run_[a-z0-9_-]{3,45}',run_id): raise ValueError('manifest run_id is invalid')
if not isinstance(snapshot_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',snapshot_id): raise ValueError('manifest snapshot_id is invalid')
if not isinstance(data_through,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',data_through): raise ValueError('manifest data_through is invalid')
try:
    if date.fromisoformat(data_through).isoformat()!=data_through: raise ValueError('manifest data_through is invalid')
except ValueError as error: raise ValueError('manifest data_through is invalid') from error
files=manifest.get('files')
if not isinstance(files,list) or len(files)!=len(allow) or {entry.get('path') for entry in files}!=allow: raise ValueError('manifest file allowlist is invalid')
if {entry.name for entry in release.iterdir()} != allow|{'manifest.json'}: raise ValueError('release directory contains missing or unapproved files')
for entry in files:
    path=release/entry['path']
    if path.is_symlink() or not path.is_file(): raise ValueError(f'release asset is missing or symlinked: {entry["path"]}')
    content=path.read_bytes()
    if len(content)!=entry.get('size_bytes') or hashlib.sha256(content).hexdigest()!=entry.get('sha256'): raise ValueError(f'release asset hash mismatch: {entry["path"]}')

if config_path.is_symlink() or not config_path.is_file(): raise ValueError('Nginx configuration must be a regular local file')
config=config_path.read_text(encoding='utf-8')
expected_locations={'/','/healthz',*('/'+name for name in allow)}
locations=re.findall(r'^\s*location\s*=\s*(/[^\s{]*)\s*\{',config,re.MULTILINE)
if len(locations)!=len(expected_locations) or set(locations)!=expected_locations: raise ValueError('Nginx configuration must expose exactly the 18 static resources plus root and healthz')
for required in ('server_name dashboard.apinova.cn;','root /var/www/dashboard/current;','auth_basic "内部看板";','auth_basic_user_file /etc/nginx/dashboard.htpasswd;','return 200 "ok\\n";','location ~ "^/notify/[0-9a-f]{32}/(offline_youth|offline_high_school|offline_university|online_private|online_platform)/people\\.png$"','location ~ "^/notify/[0-9a-f]{32}/(offline_youth|offline_high_school|offline_university|online_private|online_platform)/details\\.xlsx$"','return 404;'):
    if required not in config: raise ValueError(f'Nginx configuration is missing required route or boundary: {required.splitlines()[0]}')
if config.count('root /var/www/dashboard;') != 2: raise ValueError('notify routes must retain the existing /var/www/dashboard root')
if 'location / {\n        return 404;\n    }' not in config: raise ValueError('Nginx configuration must deny all unlisted paths')
print('\t'.join((run_id,snapshot_id,data_through,manifest_sha,hashlib.sha256(config_path.read_bytes()).hexdigest())))
PY
)"
read -r run_id snapshot_id data_through manifest_sha config_sha <<< "$validated"

if [[ "$dry_run" == true ]]; then
  printf '{"status":"validated","run_id":"%s","snapshot_id":"%s","data_through":"%s","manifest_sha256":"%s","nginx_config_sha256":"%s","uploaded":false}\n' \
    "$run_id" "$snapshot_id" "$data_through" "$manifest_sha" "$config_sha"
  exit 0
fi

if [[ "${ALLOW_LEGACY_STATIC_PUBLISH:-0}" != "1" ]]; then
  echo "Legacy static publication is retired; use native BI P5. Authorized recovery requires ALLOW_LEGACY_STATIC_PUBLISH=1." >&2
  exit 2
fi

for name in REMOTE_RELEASE_DIR REMOTE_NGINX_CONF; do
  test -n "${!name}" || { echo "$name is required for activation" >&2; exit 2; }
done
[[ "$REMOTE_RELEASE_DIR" == /* && "${REMOTE_RELEASE_DIR##*/}" == "$run_id" ]] || {
  echo "REMOTE_RELEASE_DIR must be an absolute path ending in $run_id" >&2; exit 2;
}
[[ "$REMOTE_NGINX_CONF" == /* && "$REMOTE_CURRENT_LINK" == /* && "$REMOTE_STAGING_DIR" == /* ]] || {
  echo "remote paths must be absolute" >&2; exit 2;
}
test -r "$ENV_FILE" || { echo "missing server environment file: $ENV_FILE" >&2; exit 2; }
set -a
. "$ENV_FILE"
set +a
export ENV_FILE
for name in SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD; do
  test -n "${!name:-}" || { echo "missing $name in $ENV_FILE" >&2; exit 2; }
done
[[ "$SERVER_PORT" =~ ^[0-9]+$ ]] && (( SERVER_PORT > 0 && SERVER_PORT < 65536 )) || {
  echo "SERVER_PORT must be between 1 and 65535" >&2; exit 2;
}

remote_config_upload="${REMOTE_STAGING_DIR%/}/pawsy-management-${run_id}.conf"
remote_receipt_file="${REMOTE_NGINX_CONF}.activation-${run_id}.json"
receipt_file="${RECEIPT_FILE:-$(dirname "$RELEASE_DIR")/activation-receipt-${run_id}.json}"
export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD

run_password_command() {
  local timeout="$1"
  shift
  python3 - "$timeout" "$@" <<'PY'
import os, sys
from monitoring_product.delivery_transport import run_password_command
run_password_command(sys.argv[2:], env_file=os.environ['ENV_FILE'], timeout=int(sys.argv[1]))
PY
}

ssh_options=(-o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no)
run_password_command 180 /usr/bin/scp -O "${ssh_options[@]}" -P "$SERVER_PORT" \
  "$NGINX_CONFIG" "$SERVER_USER@$SERVER_HOST:$remote_config_upload"

read -r -d '' remote_activation_py <<'PY' || true
import hashlib,json,os,pathlib,re,subprocess,sys,tempfile

allow={'index.html','prep_high.html','university.html','online.html','styles.css','app.js','boards.css','boards.js','data.json','university.data.json','prep_high.data.json',*(f'prep_high.{i}.data.json' for i in range(1,8))}
params=json.loads(__import__('base64').b64decode(sys.argv[2]).decode('utf-8'))
release_s,manifest_sha,config_upload_s,config_target_s,current_s,receipt_s,run_id,snapshot_id,data_through,config_sha=params
release=pathlib.Path(release_s); manifest_path=release/'manifest.json'; config_upload=pathlib.Path(config_upload_s); config_target=pathlib.Path(config_target_s); current=pathlib.Path(current_s); receipt=pathlib.Path(receipt_s)
old_config=None; old_mode=None; old_uid=None; old_gid=None; old_link=None; config_changed=False; current_changed=False
current_tmp=None; current_tmp_created=False

def run(args):
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if result.returncode:
        detail=(result.stderr or result.stdout).strip()[-1000:]
        raise RuntimeError(f'{args[0]} {args[1:]!r} failed with status {result.returncode}: {detail}')
    return result

def write_receipt(status,error=None,rollback_error=None):
    payload={'status':status,'run_id':run_id,'snapshot_id':snapshot_id,'data_through':data_through,'manifest_sha256':manifest_sha,'nginx_config_sha256':config_sha,'release_dir':release_s,'nginx_config':config_target_s,'current_link':current_s,'previous_current_target':old_link,'receipt_file':receipt_s}
    if error: payload['error']=error
    if rollback_error: payload['rollback_error']=rollback_error
    receipt.parent.mkdir(parents=False,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f'.{receipt.name}.',dir=str(receipt.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream: json.dump(payload,stream,ensure_ascii=False,sort_keys=True); stream.write('\n')
        os.chmod(tmp,0o644)
        os.replace(tmp,receipt)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def install_bytes(target,content,mode,uid=None,gid=None):
    fd,tmp=tempfile.mkstemp(prefix=f'.{target.name}.activation.',dir=str(target.parent))
    try:
        with os.fdopen(fd,'wb') as stream: stream.write(content)
        os.chmod(tmp,mode)
        if uid is not None and gid is not None: os.chown(tmp,uid,gid)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def restore_current():
    if not current_changed: return
    if old_link is None:
        if current.is_symlink(): current.unlink()
    else:
        tmp=current.parent/f'.{current.name}.rollback-{run_id}-{os.getpid()}'
        if tmp.exists() or tmp.is_symlink(): raise RuntimeError('rollback symlink path already exists')
        os.symlink(old_link,tmp)
        os.replace(tmp,current)

def restore_config():
    if not config_changed: return
    if old_config is None:
        if config_target.exists(): config_target.unlink()
    else:
        install_bytes(config_target,old_config,old_mode,old_uid,old_gid)

def verify_release():
    if release.is_symlink() or not release.is_dir(): raise ValueError('remote release directory is missing or symlinked')
    if manifest_path.is_symlink() or not manifest_path.is_file(): raise ValueError('remote manifest is missing or symlinked')
    mb=manifest_path.read_bytes()
    if hashlib.sha256(mb).hexdigest()!=manifest_sha: raise ValueError('remote manifest SHA-256 mismatch')
    m=json.loads(mb.decode('utf-8'))
    if m.get('schema_version')!='management_dashboard_release.v1' or (m.get('run_id'),m.get('snapshot_id'),m.get('data_through'))!=(run_id,snapshot_id,data_through): raise ValueError('remote manifest identity mismatch')
    files=m.get('files')
    if not isinstance(files,list) or len(files)!=len(allow) or {x.get('path') for x in files}!=allow: raise ValueError('remote manifest allowlist mismatch')
    if {x.name for x in release.iterdir()}!=allow|{'manifest.json'}: raise ValueError('remote release contains unapproved files')
    for entry in files:
        p=release/entry['path']
        if p.is_symlink() or not p.is_file(): raise ValueError(f'remote asset missing or symlinked: {entry["path"]}')
        b=p.read_bytes()
        if len(b)!=entry.get('size_bytes') or hashlib.sha256(b).hexdigest()!=entry.get('sha256'): raise ValueError(f'remote asset hash mismatch: {entry["path"]}')

try:
    verify_release()
    if config_upload.is_symlink() or not config_upload.is_file() or hashlib.sha256(config_upload.read_bytes()).hexdigest()!=config_sha: raise ValueError('uploaded Nginx configuration hash mismatch')
    if not config_target.is_absolute() or not config_target.parent.is_dir(): raise ValueError('Nginx configuration parent directory does not exist')
    if config_target.is_symlink(): raise ValueError('Nginx configuration target must be a regular file, not a symlink')
    if config_target.exists():
        if not config_target.is_file(): raise ValueError('Nginx configuration target is not a regular file')
        stat=config_target.stat(); old_config=config_target.read_bytes(); old_mode=stat.st_mode&0o777; old_uid=stat.st_uid; old_gid=stat.st_gid
    if not current.is_absolute() or not current.parent.is_dir(): raise ValueError('current symlink parent directory does not exist')
    if current.is_symlink(): old_link=os.readlink(current)
    elif current.exists(): raise ValueError('current path exists and is not a symlink')
    if not receipt.parent.is_dir(): raise ValueError('receipt parent directory does not exist')
    if receipt.is_symlink(): raise ValueError('receipt path must not be a symlink')
    config_bytes=config_upload.read_bytes()
    install_bytes(config_target,config_bytes,old_mode if old_mode is not None else 0o644,old_uid,old_gid)
    config_changed=True
    run(['nginx','-t'])
    current_tmp=current.parent/f'.{current.name}.activation-{run_id}-{os.getpid()}'
    if current_tmp.exists() or current_tmp.is_symlink(): raise ValueError('temporary current symlink path already exists')
    os.symlink(str(release),current_tmp)
    current_tmp_created=True
    os.replace(current_tmp,current)
    current_changed=True
    run(['nginx','-s','reload'])
    run(['curl','-fsS','-o','/dev/null','-H','Host: dashboard.apinova.cn','http://127.0.0.1/healthz'])
    write_receipt('activated')
    try: config_upload.unlink()
    except OSError: pass
    print(json.dumps({'status':'activated','run_id':run_id,'snapshot_id':snapshot_id,'data_through':data_through,'manifest_sha256':manifest_sha,'nginx_config_sha256':config_sha,'previous_current_target':old_link,'receipt_file':receipt_s},ensure_ascii=False,sort_keys=True))
except Exception as error:
    rollback_error=None
    if current_tmp_created and current_tmp is not None and (current_tmp.exists() or current_tmp.is_symlink()):
        try: current_tmp.unlink()
        except Exception as cleanup_error: rollback_error=str(cleanup_error)
    if config_changed or current_changed:
        errors=[]
        for restore in (restore_current,restore_config):
            try: restore()
            except Exception as rollback: errors.append(str(rollback))
        try:
            run(['nginx','-t'])
            run(['nginx','-s','reload'])
        except Exception as rollback: errors.append(str(rollback))
        if errors: rollback_error='; '.join(errors)
    status='rollback_failed' if rollback_error else ('failed_rolled_back' if config_changed or current_changed else 'failed_before_change')
    try: write_receipt(status,str(error),rollback_error)
    except Exception as receipt_error: rollback_error=rollback_error or f'could not save receipt: {receipt_error}'
    try: config_upload.unlink()
    except OSError: pass
    print(json.dumps({'status':status,'run_id':run_id,'error':str(error),'rollback_error':rollback_error,'receipt_file':receipt_s},ensure_ascii=False,sort_keys=True))
    sys.exit(1)
PY
remote_tx_b64="$(printf '%s' "$remote_activation_py" | base64 | tr -d '\n')"
remote_receipt_file="${REMOTE_NGINX_CONF}.activation-${run_id}.json"
remote_args_b64="$(python3 - "$REMOTE_RELEASE_DIR" "$manifest_sha" "$remote_config_upload" "$REMOTE_NGINX_CONF" "$REMOTE_CURRENT_LINK" "$remote_receipt_file" "$run_id" "$snapshot_id" "$data_through" "$config_sha" <<'PY'
import base64,json,sys
print(base64.b64encode(json.dumps(sys.argv[1:],separators=(',',':')).encode()).decode())
PY
)"
remote_command="python3 -c 'import base64,sys;exec(base64.b64decode(sys.argv[1]))' '$remote_tx_b64' '$remote_args_b64'"

run_password_command 180 /usr/bin/ssh "${ssh_options[@]}" -p "$SERVER_PORT" \
  "$SERVER_USER@$SERVER_HOST" "$remote_command"

unset SERVER_PASSWORD
python3 - "$receipt_file" "$REMOTE_RELEASE_DIR" "$REMOTE_NGINX_CONF" "$REMOTE_CURRENT_LINK" "$remote_receipt_file" "$run_id" "$snapshot_id" "$data_through" "$manifest_sha" "$config_sha" <<'PY'
import json,os,pathlib,sys,tempfile
receipt=pathlib.Path(sys.argv[1])
payload={'status':'activated','receipt_file':str(receipt),'release_dir':sys.argv[2],'nginx_config':sys.argv[3],'current_link':sys.argv[4],'remote_receipt_file':sys.argv[5],'run_id':sys.argv[6],'snapshot_id':sys.argv[7],'data_through':sys.argv[8],'manifest_sha256':sys.argv[9],'nginx_config_sha256':sys.argv[10]}
receipt.parent.mkdir(parents=True,exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix=f'.{receipt.name}.',dir=str(receipt.parent))
try:
    with os.fdopen(fd,'w',encoding='utf-8') as stream: json.dump(payload,stream,ensure_ascii=False,sort_keys=True); stream.write('\n')
    os.replace(tmp,receipt)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
print(json.dumps(payload,ensure_ascii=False,sort_keys=True))
PY
