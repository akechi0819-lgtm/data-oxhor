#!/bin/bash
set -euo pipefail
base=/var/lib/shadow-bi
receiver=$base/receiver
pending_dir=$receiver/pending
failed_dir=$base/failed
root_copy=''
release=''
archive_hash=''
old=''
old_previous=''
success=0
finish() {
    status=$?
    if [ -n "$root_copy" ]; then
        rm -f "$root_copy" || true
        root_copy=''
    fi
    if [ "$success" -eq 1 ]; then
        exit "$status"
    fi
    if [ -n "$release" ]; then
        if [ -n "$old" ] && [ -e "$base/current" ] && [ "$(readlink -f "$base/current")" != "$old" ]; then
            /srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.activate "$old" >/dev/null 2>&1 || true
            if [ -n "$old_previous" ] && [ -d "$old_previous" ]; then ln -sfn "$old_previous" "$base/previous" || true; fi
        fi
        mkdir -p -m 0700 "$failed_dir" || true
        stamp=$(date +%s%N 2>/dev/null || date +%s)
        if [ -d "$base/incoming/$release" ] && [ "$(readlink -f "$base/incoming/$release")" != "$(readlink -f "$base/current" 2>/dev/null || true)" ] && [ "$(readlink -f "$base/incoming/$release")" != "$(readlink -f "$base/previous" 2>/dev/null || true)" ]; then
            mv "$base/incoming/$release" "$failed_dir/${release}.incoming.${stamp}" 2>/dev/null || true
        fi
        if [ -d "$base/releases/$release" ] && [ "$(readlink -f "$base/releases/$release")" != "$(readlink -f "$base/current" 2>/dev/null || true)" ] && [ "$(readlink -f "$base/releases/$release")" != "$(readlink -f "$base/previous" 2>/dev/null || true)" ]; then
            mv "$base/releases/$release" "$failed_dir/${release}.target.${stamp}" 2>/dev/null || true
        fi
        printf '%s\t%s\t%s\n' "$release" "${archive_hash:-unknown}" "failed" > "$receiver/last_failed" || true
        rm -f "$pending_dir/$release" || true
    fi
    exit "$status"
}
trap finish EXIT
if [ "${1:-}" = "--preflight" ]; then
    test -n "${2:-}"
    /srv/shadow-bi/venv/bin/python - "$2" <<'PY'
import sys
from pathlib import Path
from dashboard_product.shadow_bi.p5.receiver import validate_archive
validate_archive(Path(sys.argv[1]))
print('preflight-ok')
PY
    exit 0
fi
exec 9>/run/shadow-bi-receiver.lock
flock -n 9 || exit 75
trap 'printf "%s\\n" "$release" > "$receiver/last_failed"' ERR
release=''
for marker in "$pending_dir"/daily-*; do
    if [ -f "$marker" ]; then release=$(basename "$marker"); break; fi
done
test -n "$release"
[[ "$release" =~ ^daily-[A-Za-z0-9_-]{1,96}$ ]]
archive="$receiver/$release/tables.tar.gz"
test -f "$archive"
incoming="$base/incoming/$release"
target="$base/releases/$release"
test ! -e "$incoming"
test ! -e "$target"
root_copy=$(/srv/shadow-bi/venv/bin/python - "$archive" <<'PY'
import os, shutil, sys, tempfile
source = sys.argv[1]
fd_source = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
fd_destination, destination = tempfile.mkstemp(prefix='archive.', dir='/run/shadow-bi-receiver-private')
try:
    with os.fdopen(fd_source, 'rb') as source_file, os.fdopen(fd_destination, 'wb') as destination_file:
        shutil.copyfileobj(source_file, destination_file, 1024 * 1024)
finally:
    try: os.close(fd_source)
    except OSError: pass
    try: os.close(fd_destination)
    except OSError: pass
os.chmod(destination, 0o600)
print(destination)
PY
)
archive_hash=$(sha256sum "$root_copy" | awk '{print $1}')
/srv/shadow-bi/venv/bin/python - "$root_copy" <<'PY'
import os, shutil, sys, tarfile
from pathlib import Path
from dashboard_product.shadow_bi.p5.receiver import validate_archive
archive = Path(sys.argv[1])
validate_archive(archive)
with tarfile.open(archive, 'r:gz') as tf:
    expanded = sum(member.size for member in tf)
free = shutil.disk_usage('/var/lib/shadow-bi').free
reserve = int(os.environ.get('SHADOW_RECEIVER_REBUILD_RESERVE_BYTES', str(2 * 1024 * 1024 * 1024)))
if free < expanded + reserve:
    raise ValueError('insufficient disk for expanded archive and rebuild reserve')
PY
mkdir -m 0700 "$incoming"
tar -xzf "$root_copy" -C "$incoming" --no-same-owner --no-same-permissions
test -f "$incoming/library_manifest.json"
set -a
. /etc/shadow-bi.env
set +a
cd /srv/shadow-bi/code
old=$(readlink -f "$base/current")
old_previous=$(readlink -f "$base/previous")
mkdir "$target"
/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.rebuild --incoming "$incoming" --target "$target/library"
chown -R root:shadowbi "$target"
find "$target" -type d -exec chmod 750 {} +
find "$target" -type f -exec chmod 640 {} +
bash dashboard_product/shadow_bi/p4/backup.sh
/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.activate "$target"
if ! runuser -u shadowbi --preserve-environment -- /srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p5.verify_daily --output "$base/app/audit/p3/evidence/p5-daily-receiver-${release#daily-}.json"; then
    /srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.activate "$old"
    if [ -d "$old_previous" ]; then ln -sfn "$old_previous" "$base/previous"; fi
    exit 1
fi
trap - ERR
printf '%s\n' "$release" > "$receiver/last_published"
printf '%s\n' "$archive_hash" > "$receiver/last_published_hash"
rm -f "$receiver/last_failed"
rm -f "$pending_dir/$release"
success=1
