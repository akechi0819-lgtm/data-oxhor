#!/usr/bin/env bash
set -euo pipefail
# Never allow xtrace: the legacy server file contains a password.
case "$-" in *x*) echo "refuse to run with xtrace" >&2; exit 2 ;; esac
set +x

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${DASHBOARD_ROOT}/.." && pwd)}"
ENV_FILE="${ENV_FILE:-${DASHBOARD_ROOT}/.env.server}"
SHARED_RESULT="${SHARED_RESULT:-}"

usage() {
  echo "usage: SHARED_RESULT=/path/to/shared_result.json $0 [--dry-run]" >&2
}

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--dry-run" ) ]]; then
  usage
  exit 2
fi
dry_run=false
if [[ $# -eq 1 ]]; then dry_run=true; fi
test -n "$SHARED_RESULT" || { usage; echo "SHARED_RESULT is required" >&2; exit 2; }
test -s "$SHARED_RESULT" || { echo "SHARED_RESULT is missing or empty" >&2; exit 2; }

stage="$(mktemp -d "${TMPDIR:-/tmp}/management-dashboard-stage.XXXXXX")"
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT
package_dir="${stage}/package"
cd "$PROJECT_ROOT"
python3 -m dashboard_product.management.publication \
  --shared-result "$SHARED_RESULT" \
  --output-dir "$package_dir" >/dev/null

read -r run_id snapshot_id data_through manifest_sha <<EOF
$(python3 - "$package_dir/manifest.json" <<'PY'
import hashlib, json, pathlib, sys
p = pathlib.Path(sys.argv[1])
m = json.loads(p.read_text(encoding='utf-8'))
print(m['run_id'], m['snapshot_id'], m['data_through'], hashlib.sha256(p.read_bytes()).hexdigest())
PY
)
EOF

if [[ "$dry_run" == true ]]; then
  printf '{"status":"validated","run_id":"%s","snapshot_id":"%s","data_through":"%s","manifest_sha256":"%s","uploaded":false}\n' \
    "$run_id" "$snapshot_id" "$data_through" "$manifest_sha"
  exit 0
fi

if [[ "${ALLOW_LEGACY_STATIC_PUBLISH:-0}" != "1" ]]; then
  echo "Legacy static publication is retired; use native BI P5. Authorized recovery requires ALLOW_LEGACY_STATIC_PUBLISH=1." >&2
  exit 2
fi

# Credentials are only read in the real staging path. Never print or trace them.
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

remote_parent="/var/www/dashboard/releases"
remote_release="${remote_parent}/${run_id}"
remote_incoming="${remote_parent}/.${run_id}.incoming-${$}-$(TZ=Asia/Shanghai date +%Y%m%d%H%M%S)"
export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD package_dir remote_parent remote_release remote_incoming run_id

ssh_command="set -eu; install -d -m 0755 '$remote_parent'; test ! -e '$remote_release'; mkdir -m 0700 '$remote_incoming'"

run_password_command() {
  local timeout="$1"
  shift
  python3 - "$timeout" "$@" <<'PY'
import os, sys
from monitoring_product.delivery_transport import run_password_command
run_password_command(sys.argv[2:], env_file=os.environ['ENV_FILE'], timeout=int(sys.argv[1]))
PY
}

run_password_command 60 /usr/bin/ssh \
  -o StrictHostKeyChecking=yes \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  -o GSSAPIAuthentication=no \
  -p "$SERVER_PORT" "$SERVER_USER@$SERVER_HOST" "$ssh_command"

package_files=("$package_dir"/*)
run_password_command 900 /usr/bin/scp \
  -O \
  -o StrictHostKeyChecking=yes \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  -o GSSAPIAuthentication=no \
  -P "$SERVER_PORT" "${package_files[@]}" "$SERVER_USER@$SERVER_HOST:$remote_incoming/"

read -r -d '' remote_verify_py <<'PY' || true
import hashlib,json,pathlib,sys
r=pathlib.Path(sys.argv[1]); manifest_bytes=(r/'manifest.json').read_bytes(); m=json.loads(manifest_bytes.decode('utf-8'))
expected_run,expected_snapshot,expected_through,expected_manifest_sha=json.loads(__import__('base64').b64decode(sys.argv[2]).decode('utf-8'))
allow={'index.html','prep_high.html','university.html','online.html','styles.css','app.js','boards.css','boards.js','data.json','university.data.json','prep_high.data.json',*(f'prep_high.{i}.data.json' for i in range(1,8))}
files=m.get('files')
assert hashlib.sha256(manifest_bytes).hexdigest()==expected_manifest_sha
assert m.get('schema_version')=='management_dashboard_release.v1' and m.get('run_id')==expected_run
assert m.get('snapshot_id')==expected_snapshot and m.get('data_through')==expected_through
assert isinstance(files,list) and len(files)==len(allow) and {x.get('path') for x in files}==allow
assert {p.name for p in r.iterdir()}==allow|{'manifest.json'}
for x in files:
 p=r/x['path']
 assert p.is_file() and not p.is_symlink() and p.stat().st_size==x.get('size_bytes')
 assert hashlib.sha256(p.read_bytes()).hexdigest()==x.get('sha256')
print('manifest hashes verified')
PY
remote_verify_b64="$(printf '%s' "$remote_verify_py" | base64 | tr -d '\n')"
remote_identity_b64="$(python3 -c 'import base64,json,sys; print(base64.b64encode(json.dumps(sys.argv[1:],separators=(",",":")).encode()).decode())' "$run_id" "$snapshot_id" "$data_through" "$manifest_sha")"
remote_command="set -eu; python3 -c \"import base64;exec(base64.b64decode('$remote_verify_b64'))\" '$remote_incoming' '$remote_identity_b64'; chmod -R u=rwX,go=rX '$remote_incoming'; test ! -e '$remote_release'; mv -- '$remote_incoming' '$remote_release'; printf 'staged release %s\\n' '$remote_release'"
run_password_command 180 /usr/bin/ssh \
  -o StrictHostKeyChecking=yes \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  -o GSSAPIAuthentication=no \
  -p "$SERVER_PORT" "$SERVER_USER@$SERVER_HOST" "$remote_command"

# Passwords must not be available to any further child processes.
unset SERVER_PASSWORD
python3 - "$package_dir/manifest.json" "$remote_release" "$manifest_sha" <<'PY'
import json, pathlib, sys
m=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
print(json.dumps({'status':'staged','run_id':m['run_id'],'snapshot_id':m['snapshot_id'],
                  'data_through':m['data_through'],'release_dir':sys.argv[2],
                  'manifest_sha256':sys.argv[3],'live_root_changed':False},ensure_ascii=False,sort_keys=True))
PY
