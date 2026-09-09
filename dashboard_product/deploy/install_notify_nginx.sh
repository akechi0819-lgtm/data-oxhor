#!/usr/bin/env bash
# Install only the anonymous /notify/ locations. Does not touch htpasswd or booklet maps.
set -euo pipefail
case "$-" in *x*) echo "refuse to run with xtrace (would leak credentials)" >&2; exit 2 ;; esac
set +x

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DASHBOARD_ROOT}/.env.server}"
NGINX_CONF_SRC="${NGINX_CONF_SRC:-${SCRIPT_DIR}/nginx-dashboard-http.conf}"

test -r "$ENV_FILE"
test -s "$NGINX_CONF_SRC"
grep -q '/notify/' "$NGINX_CONF_SRC" || { echo "nginx conf missing /notify/ locations" >&2; exit 2; }

set -a
. "$ENV_FILE"
set +a

required=(SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD)
for name in "${required[@]}"; do
  test -n "${!name:-}" || { echo "missing $name in $ENV_FILE" >&2; exit 2; }
done

export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD NGINX_CONF_SRC

/usr/bin/expect <<'EOF'
set timeout 60
spawn /usr/bin/scp -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -P $env(SERVER_PORT) $env(NGINX_CONF_SRC) $env(SERVER_USER)@$env(SERVER_HOST):/tmp/nginx-dashboard-http.conf
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SCP nginx conf timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

/usr/bin/expect <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) {set -euo pipefail
conf_src=/tmp/nginx-dashboard-http.conf
test -s "$conf_src"
grep -q '/notify/' "$conf_src"
if test -f /etc/nginx/sites-available/dashboard; then
  cp -a /etc/nginx/sites-available/dashboard /etc/nginx/sites-available/dashboard.bak.pre-notify
fi
install -m 0644 "$conf_src" /etc/nginx/sites-available/dashboard
if test -d /etc/nginx/sites-enabled; then
  ln -sfn /etc/nginx/sites-available/dashboard /etc/nginx/sites-enabled/dashboard
fi
rm -f "$conf_src"
install -d -m 0755 /var/www/dashboard/notify
nginx -t
systemctl reload nginx
curl -fsS -o /dev/null -H "Host: dashboard.apinova.cn" http://127.0.0.1/healthz
}
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH nginx install timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

printf 'installed anonymous /notify/ on %s (htpasswd untouched)\n' "$SERVER_HOST"
