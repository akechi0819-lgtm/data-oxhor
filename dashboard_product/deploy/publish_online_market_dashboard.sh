#!/usr/bin/env bash
set -euo pipefail

# Publish the independent shadow-data board and the total-board navigation.
# This never refreshes or replaces the four existing team booklets.
case "$-" in *x*) echo "refuse to run with xtrace (would leak SERVER_PASSWORD)" >&2; exit 2 ;; esac
set +x

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${DASHBOARD_ROOT}/.." && pwd)}"
ENV_FILE="${ENV_FILE:-${DASHBOARD_ROOT}/.env.server}"
ARTIFACT_JSON="${ARTIFACT_JSON:-}"
FULL_HTML="${FULL_HTML:-}"

test -r "$ENV_FILE"
test -s "$ARTIFACT_JSON" || { echo "ARTIFACT_JSON is missing or empty" >&2; exit 2; }
test -s "$FULL_HTML" || { echo "FULL_HTML is missing or empty" >&2; exit 2; }

set -a
. "$ENV_FILE"
set +a

required=(SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD)
for name in "${required[@]}"; do
  test -n "${!name:-}" || { echo "missing $name in $ENV_FILE" >&2; exit 2; }
done

cd "$PROJECT_ROOT"
python3 -m dashboard_product.online_market_render --artifact "$ARTIFACT_JSON"
html_dir="$(cd "$(dirname "$ARTIFACT_JSON")" && pwd)"
src="${html_dir}/online_market_special.html"
test -s "$src"
grep -qi '<!doctype html>' "$src"
grep -qi '<!doctype html>' "$FULL_HTML"

stage="$(mktemp -d "${TMPDIR:-/tmp}/online-market-dashboard.XXXXXX")"
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT
cp -p "$src" "${stage}/online_market_special.html"
cp -p "$FULL_HTML" "${stage}/full.html"

stamp="$(TZ="${TZ:-Asia/Shanghai}" date +%Y%m%d_%H%M%S)"
remote_tmp="/tmp/online-market-dashboard-${stamp}"
export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD stage remote_tmp

/usr/bin/expect -f /dev/stdin <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) "mkdir -p $env(remote_tmp) && chmod 700 $env(remote_tmp)"
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH mkdir timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

/usr/bin/expect -f /dev/stdin <<'EOF'
set timeout 120
spawn /usr/bin/scp -O -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -P $env(SERVER_PORT) $env(stage)/full.html $env(stage)/online_market_special.html $env(SERVER_USER)@$env(SERVER_HOST):$env(remote_tmp)/
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SCP timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

/usr/bin/expect -f /dev/stdin <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) "set -euo pipefail; src='$env(remote_tmp)'; dest=/var/www/dashboard; for f in full.html online_market_special.html; do test -s \"\$src/\$f\"; install -m 0644 \"\$src/\$f\" \"\$dest/.\$f.tmp\"; done; for f in full.html online_market_special.html; do mv -f \"\$dest/.\$f.tmp\" \"\$dest/\$f\"; done; rm -rf '$env(remote_tmp)'; curl -fsS -o /dev/null -H 'Host: dashboard.apinova.cn' http://127.0.0.1/healthz"
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH publish timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

printf 'published full.html and online_market_special.html from %s at %s\n' "$src" "$(date -Iseconds)"
