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
import os,pathlib,stat,subprocess
base=pathlib.Path('/var/lib/shadow-bi')
release=(base/'current').resolve(strict=True)
if release.parent!=base/'releases':raise ValueError('current outside formal releases')
for p in [release,release/'library',release/'library/library_manifest.json',release/'library/business.duckdb']:
    s=p.lstat()
    if stat.S_ISLNK(s.st_mode) or s.st_uid!=0 or s.st_mode & 0o022:
        raise ValueError('formal release ownership or write boundary invalid')
for p in [base,base/'releases']:
    subprocess.run(['setfacl','-m','u:shadowbi-notify:--x',str(p)],check=True)
for p in [release,release/'library']:
    subprocess.run(['setfacl','-m','u:shadowbi-notify:r-x',str(p)],check=True)
for p in [release/'library/library_manifest.json',release/'library/business.duckdb']:
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
