#!/bin/sh
set -eu
umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir=/var/lib/shadow-bi/backups/$stamp
mkdir -p "$backup_dir"
runuser -u postgres -- pg_dump -Fc shadowbi > "$backup_dir/metadata.dump"
cp /etc/shadow-bi.env "$backup_dir/shadow-bi.env"
cp /etc/systemd/system/shadow-bi.service "$backup_dir/shadow-bi.service"
cp /etc/nginx/sites-available/shadow-bi "$backup_dir/nginx.conf"
readlink -f /var/lib/shadow-bi/current > "$backup_dir/current.txt"
sha256sum "$backup_dir"/* > "$backup_dir/SHA256SUMS"
printf '%s\n' "$backup_dir"
