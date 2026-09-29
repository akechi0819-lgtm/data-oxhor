#!/usr/bin/env bash
set -euo pipefail
# Never allow xtrace: it would print SERVER_PASSWORD from .env.server.
case "$-" in *x*) echo "refuse to run with xtrace (would leak credentials)" >&2; exit 2 ;; esac
set +x

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${DASHBOARD_ROOT}/.." && pwd)}"
WORKSPACE="${WORKSPACE:-customers/bi_operations}"
ENV_FILE="${ENV_FILE:-${DASHBOARD_ROOT}/.env.server}"
LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/.local/logs/dashboard}"
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
data_workspace="$(python3 -c 'from pathlib import Path; import sys; print((Path(sys.argv[1])/sys.argv[2]).resolve())' "$PROJECT_ROOT" "$WORKSPACE")"

if [[ -n "${ARTIFACT_JSON:-}" ]]; then
  artifact="${ARTIFACT_JSON}"
  test -s "$artifact" || { echo "ARTIFACT_JSON is missing or empty: $artifact" >&2; exit 2; }
else
  artifact="${data_workspace}/Output/Dashboard/${run_id}/artifact.json"
  cd "$PROJECT_ROOT"
  python3 -m dashboard_product.refresh refresh --workspace "$data_workspace" --run-id "$run_id"
fi

test -s "$artifact"
# Render the single full dashboard from the same artifact. Do not upload artifact.json.
cd "$PROJECT_ROOT"
python3 -m dashboard_product.refresh validate-publish-artifact --artifact "$artifact"
python3 -m dashboard_product.refresh render --artifact "$artifact"

# The accepted online-team page follows the same explicit Snapshot in this daily run.
snapshot_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["snapshot_id"])' "$artifact")"
online_run_id="run_online_team_${stamp}"
online_output="${data_workspace}/Output/DashboardOnline/${online_run_id}"
python3 -m dashboard_product.online_team.build \
  --workspace "$data_workspace" --snapshot-id "$snapshot_id" \
  --run-id "$online_run_id" --output-dir "$online_output" \
  --as-of-date "$(TZ=Asia/Shanghai date +%F)"
python3 -m dashboard_product.online_team.export \
  --site-dir "${online_output}/site" --output "${online_output}/online_market_special.html"
online_sha="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${online_output}/online_market_special.html")"

html_dir="$(cd "$(dirname "$artifact")" && pwd)"
stage="$(mktemp -d "${TMPDIR:-/tmp}/dashboard-publish.XXXXXX")"
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT
src="${html_dir}/full.html"
test -s "$src" || { echo "missing dashboard $src" >&2; exit 2; }
grep -qi '<!doctype html>' "$src" || { echo "refusing to publish non-HTML $src" >&2; exit 2; }
cp -p "$src" "${stage}/full.html"
cp -p "${online_output}/online_market_special.html" "${stage}/online_market_special.html"
test ! -e "${stage}/artifact.json"

remote_tmp="/tmp/dashboard-publish-${stamp}"
export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD stage remote_tmp online_sha

# Password auth must go through an expect PTY. If a normal sandboxed call
# reports Permission denied for unchanged credentials, invoke this script from
# the approved elevated execution environment.
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
set timeout 180
spawn /usr/bin/scp -O -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -P $env(SERVER_PORT) $env(stage)/full.html $env(stage)/online_market_special.html $env(SERVER_USER)@$env(SERVER_HOST):$env(remote_tmp)/
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SCP timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

# Install the full dashboard to .tmp first; only then mv. A failed publish leaves the live page untouched.
/usr/bin/expect -f /dev/stdin <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) "set -euo pipefail; src='$env(remote_tmp)'; dest=/var/www/dashboard; install -d -m 0755 \"\$dest\"; test -s \"\$src/full.html\"; grep -qi '<!doctype html>' \"\$src/full.html\"; echo '$env(online_sha)  $env(remote_tmp)/online_market_special.html' | sha256sum -c -; install -m 0644 \"\$src/full.html\" \"\$dest/.full.html.tmp\"; install -m 0644 \"\$src/online_market_special.html\" \"\$dest/.online_market_special.html.tmp\"; mv -f \"\$dest/.online_market_special.html.tmp\" \"\$dest/online_market_special.html\"; mv -f \"\$dest/.full.html.tmp\" \"\$dest/full.html\"; sha256sum \"\$dest/online_market_special.html\"; rm -f \"\$dest/online_private.html\" \"\$dest/online_platform.html\" \"\$dest/offline_market.html\" \"\$dest/online_market_training.html\" \"\$dest/liuxue.html\" \"\$dest/gaozhong.html\" \"\$dest/daxue.html\"; rm -rf \"\$src\"; curl -fsS -o /dev/null -H 'Host: dashboard.apinova.cn' http://127.0.0.1/healthz"
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH publish timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

printf 'published full dashboard from %s at %s\n' "$html_dir" "$(date -Iseconds)" | tee -a "$LOG_DIR/publish.log"
