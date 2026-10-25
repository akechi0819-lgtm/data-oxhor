#!/bin/sh
# 仅用于已授权的独立P4元数据库与服务配置恢复。
set -eu
backup_dir=$1
case "$backup_dir" in /var/lib/shadow-bi/backups/*) ;; *) exit 2;; esac
sha256sum --check "$backup_dir/SHA256SUMS"
touch /run/shadow-bi-maintenance
systemctl stop shadow-bi
runuser -u postgres -- pg_restore --clean --if-exists --exit-on-error -d shadowbi < "$backup_dir/metadata.dump"
install -m 0600 "$backup_dir/shadow-bi.env" /etc/shadow-bi.env
install -m 0644 "$backup_dir/shadow-bi.service" /etc/systemd/system/shadow-bi.service
install -m 0644 "$backup_dir/nginx.conf" /etc/nginx/sites-available/shadow-bi
target=$(cat "$backup_dir/current.txt")
case "$target" in /var/lib/shadow-bi/releases/*) ;; *) exit 2;; esac
test -f "$target/library/library_manifest.json"
ln -s "$target" /var/lib/shadow-bi/restore-next
mv -Tf /var/lib/shadow-bi/restore-next /var/lib/shadow-bi/current
systemctl daemon-reload
nginx -t
systemctl reload nginx
systemctl start shadow-bi

set -a
. /etc/shadow-bi.env
set +a
for attempt in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:18090/health >/dev/null 2>&1; then break; fi
    sleep 1
done
cd /srv/shadow-bi/code
/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.activate "$target" --verify-only
rm /run/shadow-bi-maintenance
