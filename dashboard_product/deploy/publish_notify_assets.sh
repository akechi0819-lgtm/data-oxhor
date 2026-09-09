#!/usr/bin/env bash
set -euo pipefail
# Never allow xtrace: it would print SERVER_PASSWORD from .env.server.
case "$-" in *x*) echo "refuse to run with xtrace (would leak credentials)" >&2; exit 2 ;; esac
set +x

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DASHBOARD_ROOT}/.env.server}"
STAGE="${NOTIFY_STAGE:-}"
TOKEN="${NOTIFY_TOKEN:-}"
ALLOWED_TEAMS=' offline_youth offline_high_school offline_university online_private online_platform '

test -r "$ENV_FILE"
test -n "$STAGE" || { echo "missing NOTIFY_STAGE" >&2; exit 2; }
test -n "$TOKEN" || { echo "missing NOTIFY_TOKEN" >&2; exit 2; }
[[ "$TOKEN" =~ ^[0-9a-f]{32}$ ]] || { echo "NOTIFY_TOKEN must be 32 hex chars" >&2; exit 2; }
test -d "$STAGE" || { echo "missing stage dir $STAGE" >&2; exit 2; }

set -a
. "$ENV_FILE"
set +a

required=(SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD)
for name in "${required[@]}"; do
  test -n "${!name:-}" || { echo "missing $name in $ENV_FILE" >&2; exit 2; }
done

# Only png/xlsx for the three team boards. Never upload the warehouse artifact or HTML.
found=0
while IFS= read -r -d '' file; do
  rel="${file#"$STAGE"/}"
  case "$rel" in
    offline_youth/people.png|offline_youth/details.xlsx|offline_high_school/people.png|offline_high_school/details.xlsx|offline_university/people.png|offline_university/details.xlsx|online_private/people.png|online_private/details.xlsx|online_platform/people.png|online_platform/details.xlsx)
      test -s "$file" || { echo "empty $rel" >&2; exit 2; }
      found=$((found + 1))
      ;;
    *)
      echo "refusing to upload $rel" >&2
      exit 2
      ;;
  esac
done < <(find "$STAGE" -type f -print0)
test "$found" -gt 0 || { echo "stage has no notify files" >&2; exit 2; }

remote_tmp="/tmp/dashboard-notify-${TOKEN}"
export SERVER_HOST SERVER_PORT SERVER_USER SERVER_PASSWORD STAGE TOKEN remote_tmp

/usr/bin/expect <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) "mkdir -p $env(remote_tmp) && chmod 700 $env(remote_tmp)"
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH mkdir timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

test -d "$STAGE/offline_youth" -o -d "$STAGE/offline_high_school" -o -d "$STAGE/offline_university" -o -d "$STAGE/online_private" -o -d "$STAGE/online_platform" || { echo "no team dirs to upload" >&2; exit 2; }

/usr/bin/expect <<'EOF'
set timeout 180
spawn /usr/bin/scp -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -r -P $env(SERVER_PORT) $env(STAGE)/. $env(SERVER_USER)@$env(SERVER_HOST):$env(remote_tmp)/
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SCP timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

/usr/bin/expect <<'EOF'
set timeout 60
spawn /usr/bin/ssh -o StrictHostKeyChecking=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o GSSAPIAuthentication=no -p $env(SERVER_PORT) $env(SERVER_USER)@$env(SERVER_HOST) "set -euo pipefail; src='$env(remote_tmp)'; dest=/var/www/dashboard/notify/$env(TOKEN); install -d -m 0755 /var/www/dashboard/notify \"\$dest\"; for team in offline_youth offline_high_school offline_university online_private online_platform; do if test -d \"\$src/\$team\"; then test -s \"\$src/\$team/people.png\"; test -s \"\$src/\$team/details.xlsx\"; case \"\$src/\$team/people.png\" in *.json|*.html) exit 2 ;; esac; install -d -m 0755 \"\$dest/\$team\"; install -m 0644 \"\$src/\$team/people.png\" \"\$dest/\$team/people.png\"; install -m 0644 \"\$src/\$team/details.xlsx\" \"\$dest/\$team/details.xlsx\"; fi; done; rm -rf \"\$src\""
expect {
  -re {assword:} { send -- "$env(SERVER_PASSWORD)\r"; exp_continue }
  eof { set status [lindex [wait] 3]; exit $status }
  timeout { puts "SSH install timed out"; catch {close}; catch {wait}; exit 124 }
}
EOF

printf 'published notify assets token=%s\n' "$TOKEN"
