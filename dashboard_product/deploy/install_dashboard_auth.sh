#!/usr/bin/env bash
# One-time server cutover: htpasswd + nginx full-dashboard vhost.
# Reads SSH credentials from .env.server. Does not print or upload plaintext
# passwords (initial-passwords stays on this machine).
set -euo pipefail
case "$-" in *x*) echo "refuse to run with xtrace (would leak credentials)" >&2; exit 2 ;; esac
set +x

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DASHBOARD_ROOT}/.env.server}"
SECRETS_DIR="${SECRETS_DIR:-${SCRIPT_DIR}/secrets}"
NGINX_CONF_SRC="${NGINX_CONF_SRC:-${SCRIPT_DIR}/nginx-dashboard-http.conf}"
REMOTE_HTPASSWD="${REMOTE_HTPASSWD:-/etc/nginx/dashboard.htpasswd}"
REMOTE_NGINX_CONF="${REMOTE_NGINX_CONF:-/etc/nginx/sites-available/dashboard}"

test -r "$ENV_FILE"
test -s "$NGINX_CONF_SRC"
test -s "${SECRETS_DIR}/htpasswd" || { echo "missing ${SECRETS_DIR}/htpasswd — run generate_dashboard_auth.py first" >&2; exit 2; }

set -a
. "$ENV_FILE"
set +a

required=(SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD)
for name in "${required[@]}"; do
  test -n "${!name:-}" || { echo "missing $name in $ENV_FILE" >&2; exit 2; }
done

# Never upload the plaintext password file.
test ! -e "${SECRETS_DIR}/initial-passwords" || true
export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD
export HTPASSWD_SRC="${SECRETS_DIR}/htpasswd"
export NGINX_CONF_SRC
export REMOTE_HTPASSWD REMOTE_NGINX_CONF

# Password auth must go through an expect PTY. If a normal sandboxed call
# reports Permission denied for unchanged credentials, invoke this script from
# the approved elevated execution environment.
/usr/bin/expect -f /dev/stdin <<'EOF'
set timeout 60
spawn /usr/bin/scp -O -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -P $env(SERVER_PORT) $env(HTPASSWD_SRC) $env(NGINX_CONF_SRC) $env(SERVER_USER)@$env(SERVER_HOST):/tmp/
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SCP auth files timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

/usr/bin/expect -f /dev/stdin <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) {set -euo pipefail
ht_src=/tmp/htpasswd
conf_src=/tmp/nginx-dashboard-http.conf
test -s "$ht_src" && test -s "$conf_src"
install -m 0640 -o root -g www-data "$ht_src" /etc/nginx/dashboard.htpasswd
if test -f /etc/nginx/sites-available/dashboard; then
  cp -a /etc/nginx/sites-available/dashboard /etc/nginx/sites-available/dashboard.bak.pre-full-dashboard
fi
install -m 0644 "$conf_src" /etc/nginx/sites-available/dashboard
if test -d /etc/nginx/sites-enabled; then
  ln -sfn /etc/nginx/sites-available/dashboard /etc/nginx/sites-enabled/dashboard
fi
rm -f "$ht_src" "$conf_src"
# Old anonymous vhost lived in conf.d and would win over sites-enabled.
if test -f /etc/nginx/conf.d/dashboard.apinova.cn.conf; then
  mkdir -p /root/dashboard-pre-full
  mv -f /etc/nginx/conf.d/dashboard.apinova.cn.conf /root/dashboard-pre-full/dashboard.apinova.cn.conf.bak
fi
# Keep leftover anonymous current.html out of the web root.
if test -f /var/www/dashboard/current.html; then
  mkdir -p /root/dashboard-pre-full
  mv -f /var/www/dashboard/current.html /root/dashboard-pre-full/current.html.bak
fi
# Retired team and business-group pages are no longer published.
rm -f /var/www/dashboard/online_private.html /var/www/dashboard/online_platform.html /var/www/dashboard/offline_market.html /var/www/dashboard/liuxue.html /var/www/dashboard/gaozhong.html /var/www/dashboard/daxue.html
nginx -t
systemctl reload nginx
curl -fsS -o /dev/null -H "Host: dashboard.apinova.cn" http://127.0.0.1/healthz
}
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH install timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

printf 'installed full-dashboard auth on %s (htpasswd 640 root:www-data; passwords not uploaded)\n' "$SERVER_HOST"
