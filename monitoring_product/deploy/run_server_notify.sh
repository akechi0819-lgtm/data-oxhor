#!/bin/bash
# Fixed, on-demand entry. No cron/timer is installed or enabled by this script.
set -euo pipefail
case "$-" in *x*) echo 'xtrace forbidden' >&2; exit 2;; esac
umask 077
[ "$(id -u)" -eq 0 ] || { echo 'root fixed entry required' >&2; exit 2; }
mode=${1:-preview}
case "$#" in 0|1|3) ;; *) exit 2;; esac
extra=()
if [ "$#" -eq 3 ]; then
  [[ "$2" =~ ^daily-[A-Za-z0-9_-]{1,96}$ ]] || exit 2
  [[ "$3" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || exit 2
  extra=(--expected-release "$2" --expected-date "$3")
fi
case "$mode" in status|preview|send-scheduled|send-published) ;; *) exit 2;; esac
exec 9>/run/shadow-bi-notify-entry.lock
flock -n 9 || exit 75
# Limit the service identity to the currently published derived library only.
/srv/shadow-bi/venv/bin/python - <<'PY'
import datetime,hashlib,json,os,pathlib,stat,subprocess
base=pathlib.Path('/var/lib/shadow-bi')
release=(base/'current').resolve(strict=True)
if release.parent!=base/'releases':raise ValueError('current outside formal releases')
library=release/'library'
candidate_path=library/'candidate.json'
release_path=library/'release.json'
sql_mode=any(p.exists() or p.is_symlink() for p in (candidate_path,release_path))
if sql_mode:
    readable=[release_path,candidate_path,library/'warehouse.duckdb',library/'notification-preview.json']
else:
    readable=[library/'library_manifest.json',library/'business.duckdb']
for p in [release,library,*readable]:
    s=p.lstat()
    if stat.S_ISLNK(s.st_mode) or s.st_uid!=0 or s.st_mode & 0o022:
        raise ValueError('formal release ownership or write boundary invalid')
if sql_mode:
    candidate=json.loads(candidate_path.read_bytes())
    manifest=json.loads(release_path.read_bytes())
    if candidate.get('schema_version')!='sql_warehouse_candidate.v1' or manifest.get('schema_version')!='sql_warehouse_release.v1':
        raise ValueError('unsupported SQL release schema')
    if manifest.get('release_id')!=release.name:raise ValueError('SQL release id mismatch')
    if not isinstance(candidate.get('batch_id'),str) or not candidate['batch_id'] or manifest.get('batch_id')!=candidate['batch_id']:
        raise ValueError('SQL release batch mismatch')
    as_of=candidate.get('as_of_date')
    if not isinstance(as_of,str) or datetime.date.fromisoformat(as_of).isoformat()!=as_of or manifest.get('as_of_date')!=as_of:
        raise ValueError('SQL release date mismatch')
    snapshots=candidate.get('snapshots')
    if (not isinstance(snapshots,dict) or set(snapshots)!={'training','abroad'}
            or not all(isinstance(value,str) and value for value in snapshots.values())
            or manifest.get('snapshots')!=snapshots):
        raise ValueError('SQL release Snapshot mismatch')
    coverage=manifest.get('coverage') or {}
    abroad=coverage.get('study_abroad_source') or {}
    through=candidate.get('through_date')
    if (not isinstance(through,str) or datetime.date.fromisoformat(through).isoformat()!=through
            or coverage.get('data_through')!=through or coverage.get('snapshot_id')!=snapshots['training']
            or abroad.get('snapshot_id')!=snapshots['abroad'] or abroad.get('through_date')!=through):
        raise ValueError('SQL release coverage mismatch')
    candidate_ref=manifest.get('candidate') or {}
    candidate_sha=hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    if (candidate_ref.get('path')!='candidate.json' or candidate_ref.get('sha256')!=candidate_sha
            or manifest.get('candidate_sha256')!=candidate_sha):
        raise ValueError('SQL candidate digest mismatch')
    database=candidate.get('database') or {}
    preview=candidate.get('notification_preview') or {}
    if (database.get('path')!='warehouse.duckdb' or preview.get('path')!='notification-preview.json'
            or database.get('sha256')!=manifest.get('database_sha256')):
        raise ValueError('SQL release file set mismatch')
for p in [base,base/'releases']:
    subprocess.run(['setfacl','-m','u:shadowbi-notify:--x',str(p)],check=True)
for p in [release,release/'library']:
    subprocess.run(['setfacl','-m','u:shadowbi-notify:r-x',str(p)],check=True)
for p in readable:
    subprocess.run(['setfacl','-m','u:shadowbi-notify:r--',str(p)],check=True)
PY
# A transient bounded process, never a recurring unit or a timer.
exec systemd-run --quiet --wait --pipe --collect --service-type=exec \
  --unit="shadow-bi-notify-job-$(date +%s)-$$" \
  --property=User=shadowbi-notify --property=Group=shadowbi-notify \
  --property=RuntimeMaxSec=600 --property=MemoryMax=768M --property=TasksMax=64 --property=CPUQuota=75% \
  --property=Nice=10 --property=NoNewPrivileges=yes --property=ProtectSystem=strict \
  --property=ProtectHome=yes --property=PrivateTmp=yes \
  --property='ReadWritePaths=/var/lib/shadow-bi-notify /var/www/dashboard/notify' \
  --setenv=PYTHONPATH=/srv/shadow-bi-notify/current \
  /usr/bin/time -f 'notify_resources elapsed=%e max_rss_kib=%M exit=%x' \
  /srv/shadow-bi/venv/bin/python -B -m monitoring_product.server_notify "$mode" "${extra[@]}"
