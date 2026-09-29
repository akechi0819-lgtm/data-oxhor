#!/usr/bin/env bash
set -euo pipefail
# Publish only the accepted, self-contained online-team page.
case "$-" in *x*) echo "refuse to run with xtrace" >&2; exit 2 ;; esac
set +x
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${DASHBOARD_ROOT}/.." && pwd)}"
ENV_FILE="${ENV_FILE:-${DASHBOARD_ROOT}/.env.server}"
SITE_HTML="${SITE_HTML:-}"
test -s "$SITE_HTML" || { echo "SITE_HTML is missing or empty" >&2; exit 2; }
cd "$PROJECT_ROOT"
python3 -m dashboard_product.online_team.export --validate-html "$SITE_HTML"
if [[ "${1:-}" == "--dry-run" ]]; then
  echo "validated only; no credentials loaded, no upload"
  exit 0
fi
[[ $# -eq 0 ]] || { echo "usage: SITE_HTML=... $0 [--dry-run]" >&2; exit 2; }
test -r "$ENV_FILE"
set -a
. "$ENV_FILE"
set +a
for name in SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD; do
  test -n "${!name:-}" || { echo "missing $name" >&2; exit 2; }
done
stage="$(mktemp -d "${TMPDIR:-/tmp}/online-team-publish.XXXXXX")"
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT
cp "$SITE_HTML" "$stage/online_market_special.html"
expected_sha="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$stage/online_market_special.html")"
gzip -9 -c "$stage/online_market_special.html" > "$stage/online_market_special.html.gz"
stamp="$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)"
remote_tmp="/tmp/online-team-${stamp}-$$"
export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD stage remote_tmp expected_sha
/usr/bin/expect -f /dev/stdin <<'EXPECT_MKDIR'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) "mkdir -p $env(remote_tmp) && chmod 700 $env(remote_tmp)"
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { exit [lindex [wait] 3] }
  timeout { puts "SSH mkdir timed out"; exit 124 }
}
EXPECT_MKDIR
/usr/bin/expect -f /dev/stdin <<'EXPECT_UPLOAD'
set timeout 900
spawn /usr/bin/scp -O -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -P $env(SERVER_PORT) $env(stage)/online_market_special.html.gz $env(SERVER_USER)@$env(SERVER_HOST):$env(remote_tmp)/
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { exit [lindex [wait] 3] }
  timeout { puts "SCP timed out"; exit 124 }
}
EXPECT_UPLOAD
/usr/bin/expect -f /dev/stdin <<'EXPECT_INSTALL'
set timeout 120
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) "set -eu; src='$env(remote_tmp)'; dest='/var/www/dashboard'; gzip -dc \"\$src/online_market_special.html.gz\" > \"\$src/online_market_special.html\"; echo '$env(expected_sha)  $env(remote_tmp)/online_market_special.html' | sha256sum -c -; install -m 0644 \"\$src/online_market_special.html\" \"\$dest/.online_market_special.html.tmp\"; mv -f \"\$dest/.online_market_special.html.tmp\" \"\$dest/online_market_special.html\"; sha256sum \"\$dest/online_market_special.html\"; rm -rf \"\$src\"; curl -fsS -o /dev/null -H 'Host: dashboard.apinova.cn' http://127.0.0.1/healthz"
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { exit [lindex [wait] 3] }
  timeout { puts "SSH install timed out"; exit 124 }
}
EXPECT_INSTALL
printf 'published online_market_special.html sha256=%s\n' "$expected_sha"
