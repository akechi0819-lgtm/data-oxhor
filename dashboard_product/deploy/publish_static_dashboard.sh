#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${DASHBOARD_ROOT}/.." && pwd)}"
WORKSPACE="${WORKSPACE:-customers/bi_operations}"
ENV_FILE="${ENV_FILE:-${DASHBOARD_ROOT}/.env.server}"
LOG_DIR="${LOG_DIR:-${DASHBOARD_ROOT}/runtime/publish_logs}"

test -r "$ENV_FILE"
set -a
. "$ENV_FILE"
set +a

required=(SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD)
for name in "${required[@]}"; do
  test -n "${!name:-}" || { echo "missing $name in $ENV_FILE" >&2; exit 2; }
done

mkdir -p "$LOG_DIR"
stamp="$(TZ="${TZ:-Asia/Shanghai}" date +%Y%m%d_%H%M%S)"
run_id="run_dashboard_${stamp}"
artifact="${PROJECT_ROOT}/${WORKSPACE}/Output/Dashboard/${run_id}/artifact.json"
html="${artifact%.json}.html"

cd "$PROJECT_ROOT"
python3 -m dashboard_product.refresh refresh --workspace "$WORKSPACE" --run-id "$run_id"
python3 -m dashboard_product.refresh render --artifact "$artifact"
test -s "$html"

export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD html
/usr/bin/expect <<'EOF'
set timeout 120
spawn /usr/bin/scp -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -P $env(SERVER_PORT) $env(html) $env(SERVER_USER)@$env(SERVER_HOST):/tmp/dashboard-current.html
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SCP timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

/usr/bin/expect <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) {install -m 0644 /tmp/dashboard-current.html /var/www/dashboard/.current.html.tmp; mv -f /var/www/dashboard/.current.html.tmp /var/www/dashboard/current.html; curl -fsS -o /dev/null -H 'Host: dashboard.apinova.cn' http://127.0.0.1/}
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH publish timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

printf 'published %s at %s\n' "$html" "$(date -Iseconds)" | tee -a "$LOG_DIR/publish.log"
