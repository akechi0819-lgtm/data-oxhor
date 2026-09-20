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
BOOKLETS=(full online_private online_platform offline_market)

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

if [[ -n "${ARTIFACT_JSON:-}" ]]; then
  artifact="${ARTIFACT_JSON}"
  test -s "$artifact" || { echo "ARTIFACT_JSON is missing or empty: $artifact" >&2; exit 2; }
else
  artifact="${PROJECT_ROOT}/${WORKSPACE}/Output/Dashboard/${run_id}/artifact.json"
  cd "$PROJECT_ROOT"
  python3 -m dashboard_product.refresh refresh --workspace "$WORKSPACE" --run-id "$run_id"
fi

test -s "$artifact"
# Render team-board booklets from the same full artifact. Do not upload artifact.json.
cd "$PROJECT_ROOT"
python3 -m dashboard_product.refresh render --artifact "$artifact" --all-booklets

html_dir="$(cd "$(dirname "$artifact")" && pwd)"
stage="$(mktemp -d "${TMPDIR:-/tmp}/dashboard-booklets.XXXXXX")"
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT
for booklet in "${BOOKLETS[@]}"; do
  src="${html_dir}/${booklet}.html"
  test -s "$src" || { echo "missing booklet $src" >&2; exit 2; }
  grep -qi '<!doctype html>' "$src" || { echo "refusing to publish non-HTML $src" >&2; exit 2; }
  # Guard: never stage the full warehouse artifact.
  case "$src" in *.json) echo "refusing to publish json" >&2; exit 2 ;; esac
  cp -p "$src" "${stage}/${booklet}.html"
done
test ! -e "${stage}/artifact.json"

remote_tmp="/tmp/dashboard-booklets-${stamp}"
export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD stage remote_tmp

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
spawn /usr/bin/scp -O -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -P $env(SERVER_PORT) $env(stage)/full.html $env(stage)/online_private.html $env(stage)/online_platform.html $env(stage)/offline_market.html $env(SERVER_USER)@$env(SERVER_HOST):$env(remote_tmp)/
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SCP timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

# Install all four to .tmp first; only then mv. A failed booklet leaves live files untouched.
/usr/bin/expect -f /dev/stdin <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) "set -euo pipefail; src='$env(remote_tmp)'; dest=/var/www/dashboard; install -d -m 0755 \"\$dest\"; for f in full.html online_private.html online_platform.html offline_market.html; do test -s \"\$src/\$f\"; grep -qi '<!doctype html>' \"\$src/\$f\"; install -m 0644 \"\$src/\$f\" \"\$dest/.\$f.tmp\"; done; for f in full.html online_private.html online_platform.html offline_market.html; do mv -f \"\$dest/.\$f.tmp\" \"\$dest/\$f\"; done; rm -f \"\$dest/liuxue.html\" \"\$dest/gaozhong.html\" \"\$dest/daxue.html\"; rm -rf \"\$src\"; curl -fsS -o /dev/null -H 'Host: dashboard.apinova.cn' http://127.0.0.1/healthz"
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH publish timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

printf 'published booklets full,online_private,online_platform,offline_market from %s at %s\n' "$html_dir" "$(date -Iseconds)" | tee -a "$LOG_DIR/publish.log"
